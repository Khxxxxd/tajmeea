"""Runs the real engine process and talks to it the way the Mac app does."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent.parent
TESTS_DIR = Path(__file__).resolve().parent


class ProtocolTest(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as home:
            env = dict(os.environ, TAJMEEA_HOME=home, PYTHONPATH=f"{ENGINE_DIR}{os.pathsep}{TESTS_DIR}",
                       PYTHON_KEYRING_BACKEND="fakes.MemoryKeyring")
            requests = [
                {"id": 1, "method": "app.state"},
                {"id": 2, "method": "key.parse", "params": {"text": "api_id: 2041733 api_hash: 7f3c1e9a0b2d4c6e8f0a1b2c3d4e5f60"}},
                {"id": 3, "method": "key.parse", "params": {"text": "nothing here"}},
                {"id": 4, "method": "no.such.method"},
                {"id": 5, "method": "channel.inspect", "params": {"link": "https://t.me/+private"}},
                {"id": 6, "method": "library.search", "params": {"query": "قانون"}},
                {"id": 7, "method": "shelf.list"},
                {"id": 8, "method": "shelf.create", "params": {"name": "   "}},
                {"id": 9, "method": "shelf.create", "params": {"name": "بحثي"}},
            ]
            stdin = "\n".join(json.dumps(r) for r in requests) + "\n"
            proc = subprocess.run([sys.executable, "-m", "tajmeea_engine"], input=stdin, capture_output=True,
                                  text=True, env=env, timeout=60)
            lines = [json.loads(line) for line in proc.stdout.splitlines()]
            self.assertEqual(lines[0]["event"], "engine.ready")
            replies = {line["id"]: line for line in lines if "id" in line}
            self.assertEqual(set(replies), set(range(1, 10)))
            self.assertFalse(replies[1]["result"]["hasKey"])
            self.assertEqual(replies[2]["result"]["apiId"], 2041733)
            self.assertEqual(replies[3]["error"]["code"], "key_not_found")
            self.assertEqual(replies[4]["error"]["code"], "unknown_method")
            self.assertEqual(replies[5]["error"]["code"], "private")
            self.assertEqual(replies[6]["result"]["results"], [])
            self.assertEqual(replies[7]["result"], [{"id": 1, "name": "", "files": 0, "favorites": True}])
            self.assertEqual(replies[8]["error"]["code"], "shelf_name")
            self.assertEqual(replies[9]["result"]["name"], "بحثي")
            self.assertTrue((Path(home) / "library.sqlite3").exists())


if __name__ == "__main__":
    unittest.main()
