import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from app.main import parse_model
from app.providers import PRESETS
from app.tools import _canonical, _safe_rel, needs_approval, tool_specs


class CoreContractTests(unittest.TestCase):
    def test_model_identifier_keeps_colon_inside_free_model_id(self):
        self.assertEqual(parse_model("openrouter:cohere/north-mini-code:free"), ("openrouter", "cohere/north-mini-code:free"))

    def test_workspace_path_cannot_escape(self):
        self.assertEqual(_safe_rel("src/main.py"), "src/main.py")
        with self.assertRaises(ValueError):
            _safe_rel("../../etc/passwd")

    def test_external_tool_names_are_provider_safe(self):
        names = [item["function"]["name"] for item in tool_specs()]
        self.assertIn("terminal_exec", names)
        self.assertNotIn("terminal.exec", names)
        self.assertEqual(_canonical("terminal_exec"), "terminal.exec")

    def test_approval_policy(self):
        self.assertTrue(needs_approval("terminal_exec", "ask"))
        self.assertFalse(needs_approval("workspace_read", "ask"))
        self.assertFalse(needs_approval("terminal_exec", "always_allow"))

    def test_requested_provider_presets_exist(self):
        ids = {item["id"] for item in PRESETS}
        self.assertTrue({"openrouter", "groq", "opencode", "gemini", "ollama", "qwen", "claude"}.issubset(ids))


if __name__ == "__main__":
    unittest.main()
