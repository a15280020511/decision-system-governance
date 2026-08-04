#!/usr/bin/env python3
"""Generate the exact governance release manifest without mutating the repository."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    manifest_path = root / "governance-release-manifest.json"
    previous = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = []
    total_bytes = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or ".git" in path.parts or path == manifest_path:
            continue
        data = path.read_bytes()
        relative = path.relative_to(root).as_posix()
        rows.append(
            {
                "path": relative,
                "size_bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
        total_bytes += len(data)
    payload = {
        "schema_version": "governance-release-manifest-v1",
        "governance_version": args.version,
        "migration_source_repository": previous["migration_source_repository"],
        "migration_source_commit": previous["migration_source_commit"],
        "file_count": len(rows),
        "total_bytes": total_bytes,
        "files": rows,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "GENERATED", "file_count": len(rows), "total_bytes": total_bytes}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
