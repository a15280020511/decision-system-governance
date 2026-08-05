#!/usr/bin/env python3
from pathlib import Path

path = Path('.github/workflows/control-plane-validate.yml')
text = path.read_text(encoding='utf-8')
start_marker = '      - name: Validate disabled ServerChan installation\n'
end_marker = '      - name: Validate P0 and P1 resilience contract\n'
start = text.find(start_marker)
end = text.find(end_marker, start)
if start < 0 or end < 0:
    raise SystemExit('legacy ServerChan validation block not found')
replacement = '''      - name: Validate governed external integrations
        run: |
          python - <<'PY'
          import json
          from pathlib import Path

          serverchan = json.loads(Path("integrations/serverchan/integration.json").read_text(encoding="utf-8"))
          expected = {
              "id": "serverchan",
              "installation_status": "installed",
              "activation_status": "enabled",
              "implementation_status": "implemented",
          }
          for key, value in expected.items():
              if serverchan.get(key) != value:
                  raise SystemExit(f"ServerChan integration field mismatch: {key}")
          if serverchan.get("required_secrets") != ["SERVERCHAN_SENDKEY"]:
              raise SystemExit("ServerChan must require exactly SERVERCHAN_SENDKEY")
          required_entries = {
              ".github/workflows/governance-failure-notify.yml",
              "tools/serverchan_notify.py",
          }
          if set(serverchan.get("runtime_entrypoints") or []) != required_entries:
              raise SystemExit("ServerChan runtime entrypoints mismatch")
          if not serverchan.get("network_endpoints"):
              raise SystemExit("ServerChan endpoint templates missing")

          expected_integrations = {
              "osv": ("enabled", []),
              "depsdev": ("enabled", []),
              "cisa-kev": ("enabled", []),
              "healthchecks": ("pending_secret", ["HEALTHCHECKS_PING_URL"]),
          }
          for integration_id, (activation, secrets) in expected_integrations.items():
              data = json.loads(Path(f"integrations/{integration_id}/integration.json").read_text(encoding="utf-8"))
              if data.get("id") != integration_id:
                  raise SystemExit(f"integration id mismatch: {integration_id}")
              if data.get("installation_status") != "installed":
                  raise SystemExit(f"integration not installed: {integration_id}")
              if data.get("activation_status") != activation:
                  raise SystemExit(f"activation mismatch: {integration_id}")
              if data.get("implementation_status") != "implemented":
                  raise SystemExit(f"implementation mismatch: {integration_id}")
              if data.get("required_secrets") != secrets:
                  raise SystemExit(f"secret contract mismatch: {integration_id}")
          PY

'''
path.write_text(text[:start] + replacement + text[end:], encoding='utf-8')
