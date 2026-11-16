#!/usr/bin/env bash
# usage: full.sh <name> <task text>. Runs the Haiku team, then surveys every session by resume.
# FIXTURE=<dir under evals/e2e> (default base). MODE=single runs one agent with no skill.
B=${E2E_DIR:-/tmp/steward-e2e}; S=$(cd "$(dirname "$0")/../.." && pwd); n=$1; task=$2; d=$B/$n
rm -rf $d; mkdir -p $B; cp -r $S/evals/e2e/${FIXTURE:-base} $d; cd $d; git init -q
if [ "$MODE" != single ]; then mkdir -p .opencode/skills/steward .opencode/agents && cp -r $S/skills/steward/. .opencode/skills/steward/ && cp $S/skills/steward/adapters/opencode/agents/*.md .opencode/agents/
sed -i 's|^# model: provider/model|model: claude-agent/haiku|' .opencode/agents/*.md
printf '{\n  "experimental": { "subagent_depth": 2 }\n}\n' > opencode.json
python3 .opencode/skills/steward/scripts/space.py --dir .steward init >/dev/null; python3 .opencode/skills/steward/scripts/space.py --dir .steward debug on >/dev/null; fi
git add -A; git -c user.name=e2e -c user.email=e2e@x commit -qm skill
s=$(date +%s); PWD=$d timeout 3600 opencode run --model claude-agent/haiku --auto --format json "$([ "$MODE" = single ] || echo "Use the steward skill for this goal. ")$task" > $B/$n.events.jsonl 2> $B/$n.err; e=$(date +%s)
echo "$n: $((e-s))s, check: $(./check.sh | tr '\n' ' ')" >> $B/summary.txt
report() {
  { [ -d .steward ] && python3 $S/skills/steward/scripts/space.py --dir .steward debug report || echo "no brainspace: the skill was not used"
    echo "subagent launches by the steward: $(python3 -c "import json,sys;print(sum(1 for l in open(sys.argv[1]) if l.startswith('{') and json.loads(l).get('type')=='tool_use' and json.loads(l)['part'].get('tool')=='subagent'))" $B/$n.events.jsonl)"
    echo "files changed: $(git status --short -- . ':!.steward' ':!.opencode' ':!.survey' | tr '\n' ' ')"; } > $B/$n.report.txt
}
report
mk() { python3 - "$1" "$S/evals/e2e/survey.txt" "$B/$n.report.txt" "$d/.survey/$1.md" "${THREAD:-$B/thread.md}" <<'PY'
import sys
who, tpl, rep, ans, thread = sys.argv[1:]
lines = open(tpl).read().splitlines()[1:-1]
lines[0] = f"This is the user who started this run. Your task is done; this request does not change it. You are {who}."
t = "\n".join(lines)
print(t.replace("{WHO}", who).replace("{ANSWER}", ans).replace("{THREAD}", thread).replace("{REPORT}", open(rep).read().strip()))
PY
}
sid=$(python3 -c "import json;print(json.loads(open('$B/$n.events.jsonl').readline())['sessionID'])")
pids=""
for pair in "steward:$sid" "orchestrator:$(cat .steward/SESSION 2>/dev/null)" $(for a in .steward/agents/*/; do l=$(basename $a); echo "worker-$l:$(cat $a/SESSION 2>/dev/null)"; done); do
  who=${pair%%:*}; ses=${pair#*:}; [ -n "$ses" ] || { echo "$n $who: no session" >> $B/summary.txt; continue; }
  PWD=$d timeout 1200 opencode run --session $ses --auto --format json "$(mk $who)" > $B/$n.survey-$who.jsonl 2>&1 & pids="$pids $!"; sleep 3
done
wait $pids
echo "$n surveys: $(ls $d/.survey 2>/dev/null | tr '\n' ' ')" >> $B/summary.txt
