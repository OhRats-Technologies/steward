"""Tests for the brainspace state script. Stdlib only: python3 -m unittest discover -s tests"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "space.py"


class SpaceTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name) / "brain"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def space(self, *args: str, ok: bool = True) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--dir", str(self.dir), *args],
            capture_output=True,
            text=True,
        )
        if ok:
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        return proc

    def init(self, goal: str = "goal") -> None:
        self.space("init", goal)

    def rows(self, name: str) -> list[dict]:
        return [
            json.loads(line)
            for line in (self.dir / name).read_text().splitlines()
            if line.strip()
        ]

    # init -----------------------------------------------------------------

    def test_init_creates_the_brainspace(self) -> None:
        self.init()
        for name in ("GOAL.md", "LEDGER.jsonl", "INBOX.jsonl", "OUTBOX.jsonl", ".gitignore"):
            self.assertTrue((self.dir / name).exists(), name)
        self.assertTrue((self.dir / "agents").is_dir())

    def test_init_keeps_an_existing_goal(self) -> None:
        self.dir.mkdir(parents=True)
        (self.dir / "GOAL.md").write_text("# Goal\n\nBuild the parser.\n\nDone: make check\n")
        self.init("one line")
        self.assertIn("Build the parser", (self.dir / "GOAL.md").read_text())
        self.assertNotIn("one line", (self.dir / "GOAL.md").read_text())

    def test_init_fills_an_empty_goal(self) -> None:
        self.dir.mkdir(parents=True)
        (self.dir / "GOAL.md").touch()
        self.init("seeded")
        self.assertEqual((self.dir / "GOAL.md").read_text().strip(), "seeded")

    def test_commands_require_init(self) -> None:
        proc = self.space("add", "x", ok=False)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("run init", proc.stderr)

    def test_gate_requires_init(self) -> None:
        self.dir.mkdir(parents=True)
        proc = self.space("gate", ok=False)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("run init", proc.stderr)

    # ledger ---------------------------------------------------------------

    def test_add_and_list(self) -> None:
        self.init()
        self.assertEqual(self.space("add", "write it").stdout.strip(), "L1")
        self.assertEqual(self.space("add", "test it", "--owner", "A").stdout.strip(), "L2")
        out = self.space("list").stdout
        self.assertIn("L1 [open] owner=-: write it", out)
        self.assertIn("L2 [open] owner=A: test it", out)

    def test_add_rejects_empty_request(self) -> None:
        self.init()
        proc = self.space("add", "   ", ok=False)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("needs a request", proc.stderr)

    def test_set_unknown_id(self) -> None:
        self.init()
        proc = self.space("set", "L9", "--state", "done", ok=False)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("no ledger item L9", proc.stderr)

    def test_delegated_needs_an_owner(self) -> None:
        self.init()
        self.space("add", "x")
        proc = self.space("set", "L1", "--state", "delegated", ok=False)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("needs an owner", proc.stderr)

    def test_list_open_includes_blocked_and_excludes_finished(self) -> None:
        self.init()
        self.space("add", "a")
        self.space("add", "b")
        self.space("set", "L1", "--state", "blocked-on-user")
        self.space("set", "L2", "--state", "done", "--evidence", "true")
        out = self.space("list", "--open").stdout
        self.assertIn("L1", out)
        self.assertNotIn("L2", out)

    # inbox ----------------------------------------------------------------

    def test_send_rejects_unknown_kind(self) -> None:
        self.init()
        self.space("add", "x")
        proc = self.space("send", "outbox", "task", "x", ok=False)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("outbox kinds", proc.stderr)

    def test_send_rejects_unknown_item(self) -> None:
        self.init()
        proc = self.space("send", "inbox", "task", "x", "--item", "L9", ok=False)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("no ledger item L9", proc.stderr)

    def test_send_rejects_empty_text(self) -> None:
        self.init()
        proc = self.space("send", "inbox", "task", "   ", ok=False)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("needs text", proc.stderr)

    def test_send_prints_the_message_id(self) -> None:
        self.init()
        self.space("add", "x")
        self.assertEqual(
            self.space("send", "inbox", "task", "x", "--item", "L1").stdout.strip(), "I1"
        )

    def test_read_does_not_consume_until_ack(self) -> None:
        self.init()
        self.space("add", "write it")
        self.space("send", "inbox", "task", "write it", "--item", "L1")
        self.assertEqual(self.space("read", "inbox").stdout.strip(), "I1 [task] item=L1: write it")
        self.assertIn("UNREAD I1", self.space("gate", ok=False).stdout)
        self.assertEqual(self.space("ack", "inbox", "I1").stdout.strip(), "acked 1")
        self.assertNotIn("UNREAD", self.space("gate", ok=False).stdout)

    def test_ack_unknown_id(self) -> None:
        self.init()
        proc = self.space("ack", "inbox", "I9", ok=False)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("no message I9", proc.stderr)

    def test_hand_edited_message_without_read_flag(self) -> None:
        self.init()
        (self.dir / "INBOX.jsonl").write_text(
            json.dumps({"id": "I1", "kind": "task", "text": "x"}) + "\n"
        )
        proc = self.space("read", "inbox")
        self.assertIn("I1 [task] item=-: x", proc.stdout)
        self.assertEqual(self.space("ack", "inbox", "I1").stdout.strip(), "acked 1")

    # gate -----------------------------------------------------------------

    def test_gate_empty_is_finished(self) -> None:
        self.init()
        proc = self.space("gate")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("may end", proc.stdout)

    def test_gate_blocks_open_work(self) -> None:
        self.init()
        self.space("add", "write it")
        proc = self.space("gate", ok=False)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("NOT DONE L1 [open]", proc.stdout)

    def test_gate_blocks_done_without_evidence(self) -> None:
        self.init()
        self.space("add", "write it")
        self.space("set", "L1", "--state", "done")
        proc = self.space("gate", ok=False)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("NO EVIDENCE L1", proc.stdout)
        self.space("set", "L1", "--evidence", "make check: 3 passed")
        self.assertEqual(self.space("gate").returncode, 0)

    def test_gate_rejects_blank_evidence(self) -> None:
        self.init()
        self.space("add", "write it")
        self.space("set", "L1", "--state", "done", "--evidence", "   ")
        proc = self.space("gate", ok=False)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("NO EVIDENCE L1", proc.stdout)

    def test_gate_waits_on_the_user(self) -> None:
        self.init()
        self.space("add", "delete old data", "--owner", "A")
        self.space("set", "L1", "--state", "blocked-on-user")
        proc = self.space("gate", ok=False)
        self.assertEqual(proc.returncode, 3)
        self.assertIn("WAITING L1", proc.stdout)

    def test_gate_keeps_working_while_an_item_is_active(self) -> None:
        self.init()
        self.space("add", "a")
        self.space("add", "b")
        self.space("set", "L1", "--state", "blocked-on-user")
        proc = self.space("gate", ok=False)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("NOT DONE L2", proc.stdout)
        self.assertNotIn("WAITING", proc.stdout)

    def test_unread_directive_beats_waiting(self) -> None:
        self.init()
        self.space("add", "a", "--owner", "A")
        self.space("set", "L1", "--state", "blocked-on-user")
        self.space("send", "inbox", "steer", "go", "--item", "L1")
        proc = self.space("gate", ok=False)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("UNREAD I1", proc.stdout)

    # agents and sessions --------------------------------------------------

    def test_agent_creates_its_directory(self) -> None:
        self.init()
        self.space("agent", "B", "do the thing")
        home = self.dir / "agents" / "B"
        self.assertEqual((home / "BRIEF.md").read_text().strip(), "do the thing")
        self.assertTrue((home / "STATUS.md").exists())
        self.assertTrue((home / "notes").is_dir())
        self.assertTrue((home / "out").is_dir())

    def test_agent_rejects_a_path_letter(self) -> None:
        self.init()
        proc = self.space("agent", "../A", "brief", ok=False)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("single word", proc.stderr)
        self.assertFalse((self.dir.parent / "A").exists())

    def test_agent_rejects_an_empty_brief(self) -> None:
        self.init()
        proc = self.space("agent", "A", "   ", ok=False)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("needs a brief", proc.stderr)

    def test_session_round_trip(self) -> None:
        self.init()
        self.assertEqual(self.space("session", "ses_abc").stdout.strip(), "ses_abc")
        self.assertEqual(self.space("session").stdout.strip(), "ses_abc")

    def test_worker_session_round_trip(self) -> None:
        self.init()
        self.space("agent", "A", "brief")
        self.space("session", "ses_worker", "--agent", "A")
        self.assertEqual(self.space("session", "--agent", "A").stdout.strip(), "ses_worker")

    def test_missing_session_is_an_error(self) -> None:
        self.init()
        proc = self.space("session", ok=False)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("no session recorded", proc.stderr)

    def test_session_rejects_a_path_letter(self) -> None:
        self.init()
        proc = self.space("session", "--agent", "../A", ok=False)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("single word", proc.stderr)

    # concurrency ----------------------------------------------------------

    @unittest.skipUnless(os.name == "posix", "flock is POSIX")
    def test_parallel_adds_get_unique_ids(self) -> None:
        self.init()
        with ThreadPoolExecutor(max_workers=8) as pool:
            ids = list(pool.map(lambda i: self.space("add", f"request {i}").stdout.strip(), range(10)))
        self.assertEqual(sorted(ids, key=lambda item: int(item[1:])), [f"L{i}" for i in range(1, 11)])
        self.assertEqual(len(self.rows("LEDGER.jsonl")), 10)


if __name__ == "__main__":
    unittest.main()
