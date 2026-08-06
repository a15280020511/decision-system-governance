import unittest
from pathlib import Path


WORKFLOW = Path(".github/workflows/control-plane-ticket.yml")
PREPARE_STEP = "      - name: Parse and validate selected ticket before classification\n"
NEXT_STEP = "\n      - name: Verify governance status ownership\n"
SECRET_BINDING = "          OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}\n"


class ExpertPlanWorkflowSecretTests(unittest.TestCase):
    def test_prepare_step_receives_openrouter_key(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        start = text.index(PREPARE_STEP)
        end = text.index(NEXT_STEP, start)
        prepare_block = text[start:end]

        self.assertIn("        env:\n", prepare_block)
        self.assertIn(SECRET_BINDING, prepare_block)
        self.assertEqual(text.count(SECRET_BINDING), 1)
        self.assertIn(
            "python control-plane/resilient_control.py prepare",
            prepare_block,
        )


if __name__ == "__main__":
    unittest.main()
