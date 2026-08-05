#!/usr/bin/env python3
from __future__ import annotations

import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
runpy.run_path(str(ROOT / "tools" / "apply_true_async_patch.py"), run_name="__main__")

path = ROOT / "security" / "access_contract.py"
text = path.read_text(encoding="utf-8")
old = '''    if token_lines != [expected_token_line, expected_token_line]:
        errors.append(
            "CONTROL_PLANE_TOKEN must appear exactly twice as a step env assignment; "
            f"got {token_lines}"
        )
'''
new = '''    if token_lines != [expected_token_line]:
        errors.append(
            "CONTROL_PLANE_TOKEN must appear exactly once in the dispatch workflow; "
            "asynchronous reconciliation owns its separate step assignment; "
            f"got {token_lines}"
        )
'''
if old not in text:
    raise SystemExit("legacy access-contract token assertion not found")
path.write_text(text.replace(old, new, 1), encoding="utf-8")

async_test = ROOT / "tests" / "test_async_reconcile.py"
test_text = async_test.read_text(encoding="utf-8")
insert = '''
    def test_workflow_owns_one_separate_child_token_assignment(self):
        workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "control-plane-reconcile.yml").read_text(encoding="utf-8")
        line = "CONTROL_PLANE_TOKEN: ${{ secrets.CONTROL_PLANE_TOKEN }}"
        self.assertEqual(workflow.count(line), 2)
        self.assertNotIn("deferred_poll.py", workflow)
'''
marker = '\n\nif __name__ == "__main__":\n'
if insert.strip() not in test_text:
    if marker not in test_text:
        raise SystemExit("async test insertion point not found")
    test_text = test_text.replace(marker, insert + marker, 1)
async_test.write_text(test_text, encoding="utf-8")
print("access contract aligned with asynchronous split ownership")
