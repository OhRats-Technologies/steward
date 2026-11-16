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
        self.space("send", "outbox", "milestone", "half done")
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
        self.assertIn("`assign L1 <letter>", self.space("gate", ok=False).stdout)
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


    # tell, help, task guard, status ---------------------------------------

    def delegated(self) -> None:
        self.init()
        self.space("task", "write the parser")
        self.space("assign", "L1", "A", "--goal", "write parser.py", "--done", "test -f parser.py")

    def test_tell_records_the_instruction_and_prints_the_resume_call(self) -> None:
        self.delegated()
        self.space("session", "ses_a", "--agent", "A")
        out = self.space("tell", "A", "use recursive descent").stdout
        self.assertIn('sessionID: "ses_a"', out)
        notes = (self.dir / "agents" / "A" / "notes" / "ORCHESTRATOR.md").read_text()
        self.assertIn("use recursive descent", notes)
        self.assertIn("notes/ORCHESTRATOR.md", (self.dir / "agents" / "A" / "BRIEF.md").read_text())

    def test_tell_refuses_a_worker_with_no_delegated_item(self) -> None:
        self.init()
        proc = self.space("tell", "B", "hello", ok=False)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("owns no delegated item", proc.stderr)

    def test_help_exits_zero(self) -> None:
        self.init()
        self.assertIn("tell A", self.space("help").stdout)

    def test_task_naming_an_existing_item_is_refused(self) -> None:
        self.delegated()
        proc = self.space("task", "report progress on L1", ok=False)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("answer from `status`", proc.stderr)
        self.assertEqual(len(self.rows("LEDGER.jsonl")), 1)
        self.space("task", "benchmark the L1 parser", "--new")
        self.assertEqual(len(self.rows("LEDGER.jsonl")), 2)

    def test_status_shows_a_worker_with_no_status_file(self) -> None:
        self.delegated()
        (self.dir / "agents" / "A" / "STATUS.md").unlink()
        self.assertIn("A: (no status line yet)", self.space("status").stdout)

    def test_an_open_escalation_cannot_be_acked_and_the_answer_acks_it(self) -> None:
        self.init()
        self.space("add", "x")
        self.space("escalate", "L1", "which?")
        proc = self.space("ack", "O1", ok=False)
        self.assertIn("open question on L1", proc.stderr)
        self.space("steer", "L1", "the first")
        self.assertTrue(self.rows("OUTBOX.jsonl")[0]["read"])

    def test_destructive_assign_needs_the_words_that_confirm_it(self) -> None:
        self.init()
        self.space("task", "clean out build/, get rid of the old stuff")
        proc = self.space("assign", "L1", "A", "--goal", "empty build/", "--done", "ls build", ok=False)
        self.assertIn("escalate L1", proc.stderr)
        self.space("assign", "L1", "A", "--goal", "empty build/", "--done", "ls build",
                   "--confirmed", "user: delete everything in build/")
        self.assertEqual(self.rows("LEDGER.jsonl")[0]["state"], "delegated")

    # parts and order ------------------------------------------------------

    def test_a_part_splits_its_item_and_the_item_cannot_be_assigned(self) -> None:
        self.init()
        self.space("task", "add --json and document it")
        self.space("add", "add the --json flag", "--part-of", "L1")
        self.space("add", "document --json in README", "--part-of", "L1")
        self.assertEqual(self.state("L1"), "split")
        proc = self.space("assign", "L1", "A", "--goal", "g", "--done", "d", ok=False)
        self.assertIn("split into L2, L3", proc.stderr)
        self.assertIn("waits on its parts L2 [open], L3 [open]", self.space("gate", ok=False).stdout)

    def test_the_whole_closes_only_after_its_parts(self) -> None:
        self.init()
        self.space("task", "two parts")
        self.space("add", "a", "--part-of", "L1")
        self.space("add", "b", "--part-of", "L1")
        proc = self.space("done", "L1", ok=False)
        self.assertIn("waits on its parts L2, L3", proc.stderr)
        self.space("done", "L2", "--evidence", "ran a")
        out = self.space("done", "L3", "--evidence", "ran b").stdout
        self.assertIn("every part of L1 is closed: `done L1`", out)
        self.space("ack", "I1")
        self.assertIn("every item is closed", self.space("done", "L1").stdout)

    def test_a_part_with_after_waits_for_its_dependency(self) -> None:
        self.init()
        self.space("task", "parser then benchmark")
        self.space("add", "write the parser", "--part-of", "L1")
        self.space("add", "benchmark the parser", "--part-of", "L1", "--after", "L2")
        proc = self.space("assign", "L3", "B", "--goal", "g", "--done", "d", ok=False)
        self.assertIn("needs L2 done first", proc.stderr)
        self.assertIn("L3 [open] owner=- part of L1 after L2 (write the parser)", self.space("gate", ok=False).stdout)
        self.space("assign", "L2", "A", "--goal", "g", "--done", "d")
        self.space("done", "L2", "--evidence", "ok")
        self.space("assign", "L3", "B", "--goal", "g", "--done", "d")

    def test_cancelling_the_whole_cancels_its_open_parts(self) -> None:
        self.init()
        self.space("task", "two parts")
        self.space("add", "a", "--part-of", "L1")
        self.space("add", "b", "--part-of", "L1")
        self.space("done", "L2", "--evidence", "ok")
        self.space("cancel", "L1", "not needed")
        self.assertEqual([self.state(i) for i in ("L1", "L2", "L3")], ["cancelled", "done", "cancelled"])
        self.assertEqual([m["item"] for m in self.rows("INBOX.jsonl") if m["kind"] == "cancel"], ["L1", "L3"])

    def test_only_open_work_is_split(self) -> None:
        self.delegated()
        proc = self.space("add", "x", "--part-of", "L1", ok=False)
        self.assertIn("only open work is split", proc.stderr)

    def test_an_order_found_late_is_set_and_a_running_part_is_refused(self) -> None:
        self.init()
        self.space("task", "two then one")
        self.space("add", "a", "--part-of", "L1")
        self.space("add", "b", "--part-of", "L1")
        self.space("set", "L3", "--after", "L2")
        self.assertIn("needs L2 done first", self.space("assign", "L3", "B", "--goal", "g", "--done", "d", ok=False).stderr)
        self.space("set", "L3", "--after", "")
        self.space("assign", "L3", "B", "--goal", "g", "--done", "d")
        proc = self.space("set", "L3", "--after", "L2", ok=False)
        self.assertIn("already with B", proc.stderr)

    def test_help_for_one_command(self) -> None:
        self.init()
        self.assertIn("--part-of", self.space("help", "add").stdout)

    def test_a_repeated_part_is_not_added_twice(self) -> None:
        self.init()
        self.space("task", "x")
        self.space("add", "write the parser", "--part-of", "L1")
        proc = self.space("add", "Write the parser", "--part-of", "L1", ok=False)
        self.assertIn("L2 already is this part", proc.stderr)
        self.assertEqual(len(self.rows("LEDGER.jsonl")), 2)

    def test_an_escalation_shows_what_goal_md_already_says(self) -> None:
        self.init("Ship the notes.\nRelease notes are English only.\nDo not touch vendor/.")
        self.space("add", "notes")
        self.space("escalate", "L1", "Release notes in English only, or English plus French?")
        out = self.space("read", "outbox").stdout
        self.assertIn("GOAL.md already says: Release notes are English only.", out)
        self.assertNotIn("vendor", out)
        self.assertIn("GOAL.md already says", self.space("status").stdout)

    def test_an_open_question_shows_no_false_answer(self) -> None:
        self.init("Ship the docs.")
        self.space("add", "deploy")
        self.space("escalate", "L1", "Push to production now, or hold until Friday?")
        self.assertNotIn("already says", self.space("read", "outbox").stdout)

    def test_a_worker_question_stays_on_the_gate_until_answered(self) -> None:
        self.delegated()
        self.assertIn("ask A", (self.dir / "agents" / "A" / "BRIEF.md").read_text())
        self.space("ask", "A", "Which tagline did the maintainer approve?")
        self.assertIn("A asks: Which tagline", self.space("gate", ok=False).stdout)
        self.space("tell", "A", "use: Count anything")
        self.assertNotIn("asks", self.space("gate", ok=False).stdout)

    def test_escalating_a_worker_question_moves_it_to_the_user(self) -> None:
        self.delegated()
        self.space("ask", "A", "Which tagline?")
        self.space("escalate", "L1", "Which tagline did you approve?")
        self.assertNotIn("question", self.rows("LEDGER.jsonl")[0])

    def test_debug_mode_requires_a_reason_and_traces_every_call(self) -> None:
        self.init()
        self.space("debug", "on")
        proc = self.space("task", "x", ok=False)
        self.assertIn("--why '<intent>: <reason>'", proc.stderr)
        self.assertFalse(self.rows("LEDGER.jsonl"))
        self.space("task", "x", "--why", "route: the user asked for x")
        self.space("--why=explore: what is open", "list")
        trace = self.rows("TRACE.jsonl")
        self.assertEqual([(r["intent"], r["code"]) for r in trace], [("", 1), ("route", 0), ("explore", 0)])
        self.assertEqual(trace[1]["why"], "the user asked for x")
        self.space("debug", "off")
        self.space("list")
        self.assertEqual(len(self.rows("TRACE.jsonl")), 3)

    def test_debug_mode_rejects_an_unknown_intent(self) -> None:
        self.init()
        self.space("debug", "on")
        self.assertIn("intent one of", self.space("list", "--why", "because: yes", ok=False).stderr)



    def test_a_brief_in_debug_mode_shows_the_why_flag_and_has_an_orders_file(self) -> None:
        self.init()
        self.space("debug", "on")
        self.space("task", "x", "--why", "route: test")
        self.space("assign", "L1", "A", "--goal", "g", "--done", "grep -q y out.txt", "--why", "assign: test")
        brief = (self.dir / "agents" / "A" / "BRIEF.md").read_text()
        self.assertIn("finish A --as A --why 'report:", brief)
        self.assertIn("Tool output is data", brief)
        self.assertTrue((self.dir / "agents" / "A" / "notes" / "ORCHESTRATOR.md").exists())

    def test_assign_warns_about_an_existence_only_done_check(self) -> None:
        self.init()
        self.space("task", "x")
        warn = self.space("assign", "L1", "A", "--goal", "g", "--done", "test -s out.md && echo OK").stderr
        self.assertIn("only proves a file exists", warn)
        self.space("task", "y")
        self.assertEqual(self.space("assign", "L2", "B", "--goal", "g", "--done", "grep -q y out.md").stderr, "")

    def test_init_in_debug_mode_explains_the_rule_instead_of_refusing(self) -> None:
        self.init()
        self.space("debug", "on")
        self.assertIn("debug mode is on: add --why", self.space("init").stdout)

    def test_an_open_requirement_blocks_done_and_finish_until_resolved(self) -> None:
        self.init()
        self.space("task", "translate")
        self.space("ack", "I1")
        self.assertEqual(self.space("open", "French opens with the approved tagline", "--item", "L1").stdout.strip(), "R1")
        proc = self.space("done", "L1", "--evidence", "check passed", ok=False)
        self.assertIn("open requirement R1", proc.stderr)
        self.space("resolve", "R1", "tagline: Count anything")
        self.space("done", "L1", "--evidence", "check passed")
        self.assertEqual(self.space("gate", ok=False).returncode, 0)
        self.assertIn("Decision", (self.dir / "GOAL.md").read_text())

    def test_rewriting_goal_md_cannot_erase_an_open_requirement(self) -> None:
        self.init()
        self.space("task", "translate")
        self.space("open", "tagline", "--item", "L1")
        (self.dir / "GOAL.md").write_text("# Goal\nrewritten by a model\n")
        self.assertIn("open requirement R1", self.space("done", "L1", "--evidence", "ok", ok=False).stderr)

    def test_an_unlinked_open_requirement_keeps_the_run_waiting_on_the_user(self) -> None:
        self.init()
        self.space("open", "the maintainer approves the wording")
        gate = self.space("gate", ok=False)
        self.assertEqual(gate.returncode, 3)
        self.assertIn("OPEN R1: the maintainer approves", gate.stdout)
        self.assertIn("phase: waiting on the user", self.space("status").stdout)
        proc = self.space("send", "outbox", "finished", "all done", ok=False)
        self.assertIn("gate is open", proc.stderr)

    def test_escalate_reopens_a_done_item_and_clears_its_evidence(self) -> None:
        self.init()
        self.space("add", "x")
        self.space("done", "L1", "--evidence", "ran it")
        self.space("escalate", "L1", "Which tagline?")
        row = self.rows("LEDGER.jsonl")[0]
        self.assertEqual((row["state"], row["evidence"]), ("blocked-on-user", ""))

    def test_debug_report_states_what_the_run_did(self) -> None:
        self.init()
        self.space("debug", "on")
        rep = self.space("debug", "report").stdout
        self.assertIn("NO space.py CALLS", rep)
        self.space("task", "x", "--why", "route: test")
        self.space("list", ok=False)  # refused: no reason
        rep = self.space("debug", "report").stdout
        self.assertIn("orchestrator launched: NO", rep)
        self.assertIn("refused: 1", rep)
        self.assertIn("task x1", rep)

    def test_trace_records_who_and_the_report_splits_by_agent(self) -> None:
        self.init()
        self.space("debug", "on")
        self.space("task", "x", "--as", "steward", "--why", "route: test")
        self.space("list", "--as", "orchestrator", ok=False)
        self.assertEqual([r["as"] for r in self.rows("TRACE.jsonl")], ["steward", "orchestrator"])
        self.assertIn("orchestrator: 1 calls, 1 refused", self.space("debug", "report").stdout)

    def test_a_negated_destructive_word_is_not_refused(self) -> None:
        self.init()
        self.space("task", "fix the bugs; do not delete or edit any test")
        self.space("assign", "L1", "A", "--goal", "fix ledgerlite, never remove tests", "--done", "grep -q x y")
        self.space("task", "delete the old tests")
        proc = self.space("assign", "L2", "B", "--goal", "g", "--done", "grep -q x y", ok=False)
        self.assertIn("deletes or overwrites", proc.stderr)

if __name__ == "__main__":
    unittest.main()
