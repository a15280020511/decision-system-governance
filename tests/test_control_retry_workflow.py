from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "control-plane-retry.yml"


class ControlRetryWorkflowTests(unittest.TestCase):
    def test_reopened_control_issue_only_wakes_existing_serial_worker(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("types: [reopened]", text)
        self.assertIn("github.event.issue.title == '[control]'", text)
        self.assertIn(
            "github.event.issue.user.login == github.repository_owner",
            text,
        )
        self.assertIn("actions: write", text)
        self.assertIn(
            "gh workflow run control-plane-ticket.yml --ref main",
            text,
        )
        self.assertNotIn("issues: write", text)
        self.assertNotIn("CONTROL_PLANE_TOKEN", text)


if __name__ == "__main__":
    unittest.main()
