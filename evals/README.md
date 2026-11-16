# Eval

Can a small model drive the brainspace correctly from the skill text alone?

`scenarios.jsonl` holds 27 scenarios (15 steward, 12 orchestrator). Each builds a brainspace, shows
the model `GOAL.md`, the ledger and the unacked mail, and gives it one event. The model replies
with `space.py` commands; the runner executes them, shows the output, and allows two more rounds.
Then `check()` in `run.py` compares the ledger and mailboxes with the scenario's `expect` by rule.

Two whole skill versions are compared, prompt and script together:

- `v01`: the first release, kept in `v01/`. Prose protocol; the script accepts any state change.
- `v02`: the current skill in `../skills/steward/`.

```sh
python3 evals/run.py --selfcheck
python3 evals/run.py --model claude-haiku-5-5 --repeats 3
```

`--selfcheck` runs each scenario's reference solution under both versions and confirms that doing
nothing fails. Raw replies and command logs are in `results/`.

## Result (Claude Haiku 5.5, 3 trials each, 2026-11-16)

| Version | Steward | Orchestrator | All |
|---|---|---|---|
| v01 | 36/45 | 20/36 | 56/81 |
| v02 | 43/45 | 32/36 | 75/81 |

Where v01 lost and v02 did not:

- **Closing an item whose check passes** (0/3 → 3/3). Under v01 the model would not close the item
  because it could not run the check itself. In v02 `done` runs it.
- **Sending `finished`** (0/3 → 3/3, and 0/3 → 2/3 when work remained). `done` now prints whether
  the run may finish.
- **A steer to finished work, and a question mixed with a cancellation** (0/3 → 3/3 each). One
  verb replaced a two- or three-command sequence.

What v02 still gets wrong:

- **A destructive instruction with two readings**: 0/3 here, 3/3 in the run before. The model
  sometimes assigns a harmless inventory task instead of escalating. Nothing in the script can
  detect this; it is judgment.
- **A `finished` report** (1/3): the steward ran the gate but did not always ack the report.

## How much to trust this

- It is a development result. The first run on these scenarios scored v02 at 54/84 against 51/84
  for v01, on a one-shot harness. That run exposed real defects, which were then fixed: `ack`
  required a mailbox name the model kept omitting, `done` did not say when to send `finished`, and
  the steward sent a `note` beside every answer. The scores above are after those fixes, on the
  same scenarios. A fresh scenario set is needed to claim the gain generalizes.
- Three changes were made to the eval itself after seeing results: the harness became multi-round
  so the model can read error messages, `GOAL.md` was added to what the model sees, and one
  scenario was removed because it required evidence the model could not obtain without a shell
  (the model correctly refused). One over-strict assertion was relaxed. These apply to both
  versions.
- Three trials per scenario is few. Scenario-level numbers move between runs.
- Only state commands are tested. The model cannot launch subagents or run a shell here.
- The scenarios were written by one model from the skill text, so they share its reading of it.
