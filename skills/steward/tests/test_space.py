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

    def test_add_rejects_a_path_owner(self) -> None:
        self.init()
        proc = self.space("add", "x", "--owner", "../A", ok=False)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("owner must be", proc.stderr)

    def test_set_rejects_a_path_owner(self) -> None:
        self.init()
        self.space("add", "x")
        proc = self.space("set", "L1", "--owner", "../A", ok=False)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("owner must be", proc.stderr)

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

    def test_send_targeted_kinds_need_an_item(self) -> None:
        self.init()
        for box, kind in (("inbox", "task"), ("inbox", "steer"), ("inbox", "cancel")):
            with self.subTest(kind=kind):
                proc = self.space("send", box, kind, "go", ok=False)
                self.assertEqual(proc.returncode, 1)
                self.assertIn("needs --item", proc.stderr)
        proc = self.space("send", "outbox", "escalate", "question", ok=False)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("needs --item", proc.stderr)

    def test_escalate_requires_a_blocked_item(self) -> None:
        self.init()
        self.space("add", "delete old data")
        proc = self.space("send", "outbox", "escalate", "approve?", "--item", "L1", ok=False)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("blocked-on-user", proc.stderr)
        self.space("set", "L1", "--state", "blocked-on-user")
        self.assertEqual(
            self.space("send", "outbox", "escalate", "approve?", "--item", "L1").stdout.strip(),
            "O1",
        )

    def test_finished_requires_a_closed_gate(self) -> None:
        self.init()
        self.space("add", "write it")
        proc = self.space("send", "outbox", "finished", "done", ok=False)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("gate is open", proc.stderr)
        self.space("set", "L1", "--state", "done", "--evidence", "true")
        self.assertEqual(self.space("send", "outbox", "finished", "done").stdout.strip(), "O1")

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

    def test_done_without_evidence_is_refused(self) -> None:
        self.init()
        self.space("add", "write it")
        for extra in ([], ["--evidence", "   "]):
            proc = self.space("set", "L1", "--state", "done", *extra, ok=False)
            self.assertEqual(proc.returncode, 1)
            self.assertIn("without evidence", proc.stderr)
        self.assertEqual(self.rows("LEDGER.jsonl")[0]["state"], "open")

    def test_gate_catches_a_hand_edited_done_without_evidence(self) -> None:
        self.init()
        self.space("add", "write it")
        row = self.rows("LEDGER.jsonl")[0] | {"state": "done"}
        (self.dir / "LEDGER.jsonl").write_text(json.dumps(row) + "\n")
        proc = self.space("gate", ok=False)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("NO EVIDENCE L1", proc.stdout)
        self.space("set", "L1", "--evidence", "make check: 3 passed")
        self.assertEqual(self.space("gate").returncode, 0)

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

    def test_agent_reads_a_brief_from_stdin(self) -> None:
        self.init()
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--dir", str(self.dir), "agent", "B", "--stdin"],
            input='do the thing\nwith a "quote" and $HOME\n',
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertEqual(
            (self.dir / "agents" / "B" / "BRIEF.md").read_text().strip(),
            'do the thing\nwith a "quote" and $HOME',
        )

    def test_agent_rejects_a_path_letter(self) -> None:
        self.init()
        proc = self.space("agent", "../A", "brief", ok=False)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("single word", proc.stderr)
        self.assertFalse((self.dir.parent / "A").exists())

    def test_agent_requires_a_brief(self) -> None:
        self.init()
        proc = self.space("agent", "A", ok=False)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("needs a brief", proc.stderr)

    def test_agent_rejects_an_empty_brief(self) -> None:
        self.init()
        proc = self.space("agent", "A", "   ", ok=False)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("needs a brief", proc.stderr)

    def test_agent_rejects_brief_and_stdin_together(self) -> None:
        self.init()
        proc = self.space("agent", "A", "brief", "--stdin", ok=False)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("not both", proc.stderr)

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

    # lifecycle --------------------------------------------------------------

    def state(self, item: str = "L1") -> str:
        return next(r["state"] for r in self.rows("LEDGER.jsonl") if r["id"] == item)

    def test_illegal_transitions_are_refused(self) -> None:
        self.init()
        self.space("add", "x")
        self.space("set", "L1", "--state", "cancelled")
        proc = self.space("set", "L1", "--state", "done", "--evidence", "ok", ok=False)
        self.assertIn("cannot become done", proc.stderr)
        self.space("set", "L1", "--state", "open")
        self.space("set", "L1", "--state", "blocked-on-user")
        proc = self.space("set", "L1", "--state", "done", "--evidence", "ok", ok=False)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(self.state(), "blocked-on-user")

    def test_reopening_clears_old_evidence(self) -> None:
        self.init()
        self.space("add", "x")
        self.space("done", "L1", "--evidence", "ran it")
        self.space("steer", "L1", "use tabs instead")
        row = self.rows("LEDGER.jsonl")[0]
        self.assertEqual((row["state"], row["evidence"]), ("open", ""))
        proc = self.space("set", "L1", "--state", "done", ok=False)
        self.assertIn("without evidence", proc.stderr)

    def test_task_adds_one_item_and_one_directive(self) -> None:
        self.init()
        self.assertEqual(self.space("task", "write docs", "--check", "true").stdout.strip(), "L1")
        self.assertEqual(len(self.rows("LEDGER.jsonl")), 1)
        msg = self.rows("INBOX.jsonl")[0]
        self.assertEqual((msg["kind"], msg["item"], msg["text"]), ("task", "L1", "write docs"))

    def test_escalate_then_steer_round_trip(self) -> None:
        self.init()
        self.space("add", "delete old data", "--owner", "A")
        self.space("set", "L1", "--state", "delegated")
        self.space("escalate", "L1", "Delete data/v1 or data/v2?")
        self.assertEqual(self.state(), "blocked-on-user")
        self.assertEqual(self.rows("OUTBOX.jsonl")[0]["kind"], "escalate")
        self.assertEqual(self.space("gate", ok=False).returncode, 3)
        self.space("steer", "L1", "data/v1 only")
        self.assertEqual(self.state(), "delegated")
        self.assertEqual(self.space("gate", ok=False).returncode, 2)

    def test_steer_restores_an_unowned_item_to_open(self) -> None:
        self.init()
        self.space("add", "x")
        self.space("escalate", "L1", "which?")
        self.space("steer", "L1", "the first")
        self.assertEqual(self.state(), "open")

    def test_steer_refuses_a_cancelled_item(self) -> None:
        self.init()
        self.space("add", "x")
        self.space("cancel", "L1", "not needed")
        self.assertEqual(self.state(), "cancelled")
        self.assertEqual(self.rows("INBOX.jsonl")[0]["kind"], "cancel")
        proc = self.space("steer", "L1", "actually", ok=False)
        self.assertIn("new `task`", proc.stderr)

    def test_cancel_refuses_a_done_item(self) -> None:
        self.init()
        self.space("add", "x")
        self.space("done", "L1", "--evidence", "ran it")
        proc = self.space("cancel", "L1", "stop", ok=False)
        self.assertIn("already done", proc.stderr)
        self.assertEqual(self.rows("INBOX.jsonl"), [])

    def test_note_reaches_the_goal_and_every_later_brief(self) -> None:
        self.init()
        self.space("add", "x")
        self.space("note", "never touch the Jupyter kernels")
        self.assertIn("never touch the Jupyter kernels", (self.dir / "GOAL.md").read_text())
        self.space("assign", "L1", "A", "--goal", "do x", "--done", "make check")
        brief = (self.dir / "agents" / "A" / "BRIEF.md").read_text()
        self.assertIn("never touch the Jupyter kernels", brief)
        for part in ("**Goal.**", "**Done.**", "**Known", "**Your directory.**", "**Survive.**", "**Report.**"):
            self.assertIn(part, brief)
        row = self.rows("LEDGER.jsonl")[0]
        self.assertEqual((row["state"], row["owner"]), ("delegated", "A"))

    def test_assign_keeps_one_worker_on_one_item(self) -> None:
        self.init()
        self.space("add", "x")
        self.space("add", "y")
        self.space("assign", "L1", "A", "--goal", "g", "--done", "d")
        proc = self.space("assign", "L2", "A", "--goal", "g", "--done", "d", ok=False)
        self.assertIn("already owns L1", proc.stderr)
        proc = self.space("assign", "L1", "B", "--goal", "g", "--done", "d", ok=False)
        self.assertIn("belongs to A", proc.stderr)
        proc = self.space("assign", "L2", "B", "--goal", "g", ok=False)
        self.assertIn("--goal and --done", proc.stderr)
        self.assertEqual(self.state("L2"), "open")

    def test_assign_only_takes_open_work(self) -> None:
        self.init()
        self.space("add", "x")
        self.space("escalate", "L1", "which?")
        proc = self.space("assign", "L1", "A", "--goal", "g", "--done", "d", ok=False)
        self.assertIn("waits on the user", proc.stderr)
        self.space("cancel", "L1", "no")
        proc = self.space("assign", "L1", "A", "--goal", "g", "--done", "d", ok=False)
        self.assertIn("is cancelled", proc.stderr)
        proc = self.space("cancel", "L1", "again", ok=False)
        self.assertIn("already cancelled", proc.stderr)
        self.assertEqual(len(self.rows("INBOX.jsonl")), 1)

    def test_ack_infers_the_mailbox_from_the_id(self) -> None:
        self.init()
        self.space("add", "x")
        self.space("task", "y")
        self.space("escalate", "L1", "which?")
        self.assertEqual(self.space("ack", "I1", "O1").stdout.strip(), "acked 2")
        proc = self.space("ack", "inbox", "O1", ok=False)
        self.assertIn("not an inbox id", proc.stderr)
        proc = self.space("ack", "L1", ok=False)
        self.assertIn("ids look like", proc.stderr)

    def test_an_answered_escalation_is_recorded_in_the_goal(self) -> None:
        self.init()
        self.space("add", "x")
        self.space("steer", "L1", "plain steer")
        self.assertNotIn("plain steer", (self.dir / "GOAL.md").read_text())
        self.space("escalate", "L1", "which?")
        self.space("steer", "L1", "the first one")
        self.assertIn("Decision", (self.dir / "GOAL.md").read_text())
        self.assertIn("the first one", (self.dir / "GOAL.md").read_text())

    def test_done_says_when_to_send_finished(self) -> None:
        self.init()
        self.space("add", "x")
        self.space("add", "y")
        self.assertIn("work remains", self.space("done", "L1", "--evidence", "ran").stdout)
        self.assertIn("send outbox finished", self.space("done", "L2", "--evidence", "ran").stdout)

    def test_done_runs_the_item_check(self) -> None:
        self.init()
        self.space("add", "make the flag", "--check", "test -f flag")
        proc = self.space("done", "L1", "--evidence", "trust me", ok=False)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("check failed", proc.stderr)
        self.assertEqual(self.state(), "open")
        proc = self.space("set", "L1", "--state", "done", "--evidence", "trust me", ok=False)
        self.assertIn("has a check", proc.stderr)
        (self.dir.parent / "flag").touch()
        self.space("done", "L1")
        self.assertIn("exit 0", self.rows("LEDGER.jsonl")[0]["evidence"])
        self.assertEqual(self.space("gate").returncode, 0)

    def test_done_without_a_check_needs_evidence(self) -> None:
        self.init()
        self.space("add", "x")
        proc = self.space("done", "L1", ok=False)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("--evidence", proc.stderr)

    def test_session_is_not_silently_replaced(self) -> None:
        self.init()
        self.space("session", "ses_1")
        self.space("session", "ses_1")
        proc = self.space("session", "ses_2", ok=False)
        self.assertIn("already recorded", proc.stderr)
        self.space("session", "ses_2", "--replace")
        self.assertEqual(self.space("session").stdout.strip(), "ses_2")

    def test_gate_says_what_to_do_next(self) -> None:
        self.init()
        self.space("add", "x")
        self.assertIn("assign it", self.space("gate", ok=False).stdout)
        self.space("assign", "L1", "A", "--goal", "g", "--done", "d")
        self.assertIn("no session", self.space("gate", ok=False).stdout)
        self.space("session", "ses_a", "--agent", "A")
        self.assertIn("waiting on A", self.space("gate", ok=False).stdout)

    def test_status_shows_phase_last_line_and_stale_workers(self) -> None:
        self.init()
        self.assertIn("phase: empty", self.space("status").stdout)
        self.space("add", "x")
        self.space("assign", "L1", "A", "--goal", "g", "--done", "d")
        status = self.dir / "agents" / "A" / "STATUS.md"
        status.write_text("step 1 done\nstep 2 running\n")
        out = self.space("status").stdout
        self.assertIn("phase: working (gate 2)", out)
        self.assertIn("A: step 2 running", out)
        self.assertNotIn("STALE", out)
        old = status.stat().st_mtime - 3600
        os.utime(status, (old, old))
        self.assertIn("STALE: silent 60m", self.space("status").stdout)
        self.space("escalate", "L1", "which?")
        self.assertIn("phase: waiting on the user", self.space("status").stdout)
        self.assertIn("unacked outbox O1 [escalate]", self.space("status").stdout)


    @unittest.skipUnless(os.name == "posix", "flock is POSIX")
    def test_parallel_adds_get_unique_ids(self) -> None:
        self.init()
        with ThreadPoolExecutor(max_workers=8) as pool:
            ids = list(pool.map(lambda i: self.space("add", f"request {i}").stdout.strip(), range(10)))
        self.assertEqual(sorted(ids, key=lambda item: int(item[1:])), [f"L{i}" for i in range(1, 11)])
        self.assertEqual(len(self.rows("LEDGER.jsonl")), 10)


if __name__ == "__main__":
    unittest.main()
