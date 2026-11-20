<p align="center">
  <img src="assets/header.png" alt="Steward" width="100%" />
</p>

<p align="center">
  <em>A three-tier Agent Skill: keep a frontier model in charge without paying frontier prices for the whole run.</em>
</p>

<p align="center">
  <a href="#setup-opencode-2x">Setup</a> ·
  <a href="#usage">Usage</a> ·
  <a href="skills/steward/SKILL.md">Skill</a> ·
  <a href="ARCHITECTURE.md">Architecture</a> ·
  <a href="evals/README.md">Evals</a>
</p>

- **Steward** (frontier model) — talks to you, turns your requests into tasks, and wakes up when a decision is needed or the work is done.
- **Orchestrator** (mid-tier subagent) — breaks tasks down, assigns them to workers, and checks their results.
- **Workers** (small, cheap subagents) — each handles one subtask at a time.

You only ever talk to the steward. The tiers coordinate through plain files in a `.steward/` directory inside your project, managed by a small Python script (`space.py`).

## Setup (OpenCode 2.x)

Requires Python 3.10+ (on Windows, run under WSL).

Copy the skill and the two subagent definitions into your project:

```sh
mkdir -p .opencode/skills/steward .opencode/agents
cp -r skills/steward/. .opencode/skills/steward/
cp skills/steward/adapters/opencode/agents/*.md .opencode/agents/
```

For a global install instead, copy them to `~/.config/opencode/skills/steward/` and `~/.config/opencode/agents/`.

Next, open `.opencode/agents/steward-orchestrator.md` and `.opencode/agents/steward-worker.md`, uncomment `model:`, and pick the mid-tier and cheap models you want to use. If you skip this, both subagents inherit your main model.

Finally, allow two levels of nested subagents in `opencode.json` (or `opencode.jsonc`) so the orchestrator can launch workers:

```jsonc
{
  "experimental": {
    "subagent_depth": 2
  }
}
```

## Usage

Start a session on your main model, describe what you want done, and ask it to use the `steward` skill.

The steward will create `.steward/`, kick off `steward-orchestrator` in the background, and hand control back to you. Whenever you send a follow-up — a change of plans, a new task, or a status question — the steward routes it without interrupting the orchestrator directly. When the orchestrator needs a decision or finishes the goal, the steward wakes up and reports back.

`.steward/` includes its own `.gitignore`, so temporary run state stays out of your repository.

## Development & More Info

- **Skill prompts:** [`skills/steward/SKILL.md`](skills/steward/SKILL.md) and [`skills/steward/orchestrator-prompt.md`](skills/steward/orchestrator-prompt.md)
- **Design notes:** [`ARCHITECTURE.md`](ARCHITECTURE.md)
- **Evals:** [`evals/README.md`](evals/README.md)

Run the test suite locally:

```sh
python3 -m unittest discover -s skills/steward/tests
```

## License

MIT — see [`LICENSE`](LICENSE).
