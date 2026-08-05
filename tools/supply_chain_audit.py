#!/usr/bin/env python3
"""Audit pinned Python dependencies against OSV, deps.dev and CISA KEV."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "governance-supply-chain-audit-v1"
OSV_URL = "https://api.osv.dev/v1/querybatch"
DEPS_URL = "https://api.deps.dev/v3/systems/pypi/packages/{package}/versions/{version}"
KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
REQ_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*==\s*([^\s;#]+)")
USES_RE = re.compile(r"(?m)^\s*-?\s*uses:\s*([^\s#]+)")


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def request_json(url: str, *, payload: Any | None = None, timeout: int = 45) -> Any:
    data = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="POST" if data is not None else "GET",
        headers={"Accept": "application/json", "Content-Type": "application/json", "User-Agent": "governance-supply-chain-audit"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(25 * 1024 * 1024 + 1)
    if len(raw) > 25 * 1024 * 1024:
        raise RuntimeError(f"response too large from {urllib.parse.urlsplit(url).netloc}")
    return json.loads(raw.decode("utf-8"))


def inventory(root: Path) -> dict[str, Any]:
    packages: dict[tuple[str, str], dict[str, Any]] = {}
    unpinned: list[dict[str, str]] = []
    for path in sorted(root.rglob("requirements*.txt")) + sorted(root.rglob("requirements*.in")):
        if any(part.startswith(".") and part not in {".github"} for part in path.parts):
            continue
        for number, raw in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith(("#", "-r", "--")):
                continue
            match = REQ_RE.match(line)
            if match:
                name, version = match.group(1), match.group(2)
                key = (name.lower().replace("_", "-"), version)
                row = packages.setdefault(key, {"ecosystem": "PyPI", "name": name, "version": version, "locations": []})
                row["locations"].append({"path": path.as_posix(), "line": number})
            else:
                unpinned.append({"path": path.as_posix(), "line": str(number), "requirement": line[:300]})
    actions: dict[str, list[str]] = {}
    workflow_root = root / ".github" / "workflows"
    if workflow_root.exists():
        for path in sorted(list(workflow_root.glob("*.yml")) + list(workflow_root.glob("*.yaml"))):
            for action in USES_RE.findall(path.read_text(encoding="utf-8", errors="replace")):
                actions.setdefault(action, []).append(path.as_posix())
    return {"packages": list(packages.values()), "unpinned_requirements": unpinned,
            "github_actions": [{"uses": key, "workflows": value} for key, value in sorted(actions.items())]}


def osv_audit(packages: list[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    rows, errors = [], []
    for start in range(0, len(packages), 1000):
        batch = packages[start:start + 1000]
        try:
            payload = {"queries": [{"package": {"ecosystem": "PyPI", "name": row["name"]}, "version": row["version"]} for row in batch]}
            response = request_json(OSV_URL, payload=payload)
            results = response.get("results", []) if isinstance(response, Mapping) else []
            for package, result in zip(batch, results):
                vulns = result.get("vulns", []) if isinstance(result, Mapping) else []
                for vuln in vulns:
                    if not isinstance(vuln, Mapping):
                        continue
                    aliases = [str(value) for value in vuln.get("aliases", []) if value]
                    rows.append({"package": package["name"], "version": package["version"],
                                 "id": vuln.get("id"), "aliases": aliases,
                                 "summary": vuln.get("summary"), "modified": vuln.get("modified")})
        except Exception as exc:
            errors.append(f"OSV query failed for batch {start // 1000 + 1}: {type(exc).__name__}: {exc}")
    return rows, errors


def deps_audit(packages: list[Mapping[str, Any]], limit: int) -> tuple[list[dict[str, Any]], list[str]]:
    rows, errors = [], []
    for package in packages[:limit]:
        url = DEPS_URL.format(package=urllib.parse.quote(str(package["name"]), safe=""),
                              version=urllib.parse.quote(str(package["version"]), safe=""))
        try:
            response = request_json(url)
            links = response.get("links", []) if isinstance(response, Mapping) else []
            advisory_keys = []
            for key in response.get("advisoryKeys", []) if isinstance(response, Mapping) else []:
                if isinstance(key, Mapping):
                    advisory_keys.append({"id": key.get("id")})
            rows.append({"package": package["name"], "version": package["version"],
                         "published_at": response.get("publishedAt") if isinstance(response, Mapping) else None,
                         "is_default": response.get("isDefault") if isinstance(response, Mapping) else None,
                         "licenses": response.get("licenses", []) if isinstance(response, Mapping) else [],
                         "advisories": advisory_keys, "links": links[:20] if isinstance(links, list) else []})
        except urllib.error.HTTPError as exc:
            errors.append(f"deps.dev {package['name']}=={package['version']}: HTTP {exc.code}")
        except Exception as exc:
            errors.append(f"deps.dev {package['name']}=={package['version']}: {type(exc).__name__}: {exc}")
    return rows, errors


def kev_catalog() -> tuple[dict[str, dict[str, Any]], list[str]]:
    try:
        response = request_json(KEV_URL)
        rows = response.get("vulnerabilities", []) if isinstance(response, Mapping) else []
        return {str(row.get("cveID")): dict(row) for row in rows if isinstance(row, Mapping) and row.get("cveID")}, []
    except Exception as exc:
        return {}, [f"CISA KEV fetch failed: {type(exc).__name__}: {exc}"]


def build_manifest(root: Path) -> None:
    rows = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            rows.append({"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size,
                         "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    dump(root / "manifest.json", {"schema_version": SCHEMA, "created_at": now(), "files": rows,
                                  "security": {"secret_values_included": False}})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--output-dir", default="supply-chain-audit")
    parser.add_argument("--deps-limit", type=int, default=150)
    parser.add_argument("--fail-on-kev", action="store_true")
    args = parser.parse_args()
    root, out = Path(args.root), Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    inv = inventory(root)
    packages = inv["packages"]
    osv, osv_errors = osv_audit(packages)
    deps, deps_errors = deps_audit(packages, max(0, min(args.deps_limit, 500)))
    kev, kev_errors = kev_catalog()
    kev_matches = []
    for vuln in osv:
        identifiers = {str(vuln.get("id") or ""), *[str(value) for value in vuln.get("aliases", [])]}
        for cve in sorted(identifiers & set(kev)):
            kev_matches.append({"package": vuln["package"], "version": vuln["version"],
                                "osv_id": vuln["id"], "cve": cve,
                                "kev": {key: kev[cve].get(key) for key in ("vendorProject", "product", "vulnerabilityName", "dateAdded", "dueDate", "knownRansomwareCampaignUse", "requiredAction")}})
    errors = osv_errors + deps_errors + kev_errors
    dump(out / "inventory.json", {"schema_version": SCHEMA, "created_at": now(), **inv})
    dump(out / "osv-findings.json", {"schema_version": SCHEMA, "findings": osv})
    dump(out / "deps-dev-metadata.json", {"schema_version": SCHEMA, "packages": deps})
    dump(out / "cisa-kev-correlation.json", {"schema_version": SCHEMA, "matches": kev_matches})
    dump(out / "api-errors.json", {"schema_version": SCHEMA, "errors": errors})
    status = "critical" if kev_matches else "warning" if osv or inv["unpinned_requirements"] or errors else "pass"
    summary = {
        "schema_version": SCHEMA, "created_at": now(), "status": status,
        "counts": {"pinned_packages": len(packages), "unpinned_requirements": len(inv["unpinned_requirements"]),
                   "github_actions": len(inv["github_actions"]), "osv_findings": len(osv),
                   "cisa_kev_matches": len(kev_matches), "api_errors": len(errors)},
        "policy": {"report_only": not args.fail_on_kev, "fail_on_kev": args.fail_on_kev,
                   "secret_values_included": False},
    }
    dump(out / "summary.json", summary)
    md = ["# Supply-chain audit", "", f"- Status: **{status.upper()}**",
          f"- Pinned Python packages: **{len(packages)}**", f"- Unpinned requirements: **{len(inv['unpinned_requirements'])}**",
          f"- OSV findings: **{len(osv)}**", f"- CISA KEV matches: **{len(kev_matches)}**",
          f"- API errors: **{len(errors)}**", "", "This audit is read-only and does not transmit source code, artifacts, prompts, business data, or secrets.", ""]
    (out / "summary.md").write_text("\n".join(md), encoding="utf-8")
    build_manifest(out)
    if args.fail_on_kev and kev_matches:
        print("::error::one or more dependencies correlate with CISA KEV", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
