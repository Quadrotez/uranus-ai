from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

TEST_WORKSPACE = Path(tempfile.mkdtemp(prefix="uranus-sandbox-test-"))
os.environ["WORKSPACE_DIR"] = str(TEST_WORKSPACE)
os.environ["INTERNAL_SERVICE_TOKEN"] = "test-token"
sys.path.insert(0, str(Path(__file__).parents[1]))

import server


class SandboxFilesystemTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        for child in TEST_WORKSPACE.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        await server.startup()

    async def test_mkdir_then_write_nested_file(self) -> None:
        created = await server.make_directory(server.DirectoryRequest(path="site"), None)
        self.assertTrue(created["ok"])
        written = await server.write_file(server.FileRequest(path="site/index.html", content="<h1>Uranus</h1>"), None)
        self.assertTrue(written["ok"])
        self.assertEqual((TEST_WORKSPACE / "site/index.html").read_text(), "<h1>Uranus</h1>")

    async def test_empty_directory_like_write_is_rejected_with_recovery_hint(self) -> None:
        result = await server.write_file(server.FileRequest(path="site", content=""), None)
        self.assertFalse(result["ok"])
        self.assertIn("workspace.mkdir", result["error"])
        self.assertFalse((TEST_WORKSPACE / "site").exists())

    async def test_parent_file_conflict_is_structured(self) -> None:
        await server.write_file(server.FileRequest(path="parent", content="not a directory"), None)
        result = await server.write_file(server.FileRequest(path="parent/child.txt", content="x"), None)
        self.assertFalse(result["ok"])
        self.assertIn("parent", result["error"])
        self.assertIn("file", result["error"])

    async def test_traversal_is_rejected(self) -> None:
        with self.assertRaises(Exception):
            server.safe_path("../../etc/passwd")


if __name__ == "__main__":
    unittest.main()
