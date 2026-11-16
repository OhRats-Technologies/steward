# Worker brief

`space.py assign` writes this brief: you supply parts 1 to 3 (`--goal`, `--done`, `--known`) and
it fills parts 4 to 6 and the standing rules. The worker reads the brief, its agent prompt and its
directory.

1. **Goal.** One task, and what it is for.
2. **Done.** A command whose output shows it is done, or the exact file that must exist.
3. **Known and off-limits.** Facts already established. Files and processes you must not touch.
   Standing rules from the inbox notes.
4. **Your directory.** `<brainspace>/agents/<letter>/` (absolute). Notes go in `notes/`, results in
   `out/`. Write nothing outside it unless the task names the file.
5. **Survive.** After each step, append one line to `STATUS.md`: what is done, where it is, what is
   next. You may be stopped without warning; this file is how the work survives.
6. **Report.** Under 200 words: what you did, the output of the done command, exact paths,
   anything you could not determine.

The worker does not ask questions and does not launch subagents. If the brief is wrong or a step is
unsafe, it stops that step and reports.
