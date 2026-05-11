#!/usr/bin/env bash
# Run one TDD iteration of the rule-expansion loop.
#
# Drop this in the repo and either:
#   1. Run by hand:
#        scripts/loop_iteration.sh
#   2. Or schedule via cron, every 12 minutes for 4 hours:
#        */12 * * * * cd /home/user/healthcraft && timeout 600 scripts/loop_iteration.sh \
#          >>/tmp/agents-assemble-loop.log 2>&1
#
# What this script does NOT do: pick which rules to add. That's a human
# (or LLM) call. The script enforces the TDD invariants and refuses to
# commit anything that breaks them — so a runaway "auto-add" pass cannot
# corrupt the bundled rule library.
#
# To use this with an LLM (Claude Code, GPT, etc.) on each cron tick:
#   1. Cron fires this script.
#   2. The LLM is invoked with the prompt-template at the bottom of this
#      file (or you wire it via your CI / agent harness).
#   3. The LLM appends new rule(s) + tests, then exits.
#   4. This script verifies, commits, pushes — or rejects.
#
# Without an LLM this script is still useful: run it after editing the
# rule file by hand to catch score-range gaps before they hit CI.

set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== loop iteration $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

# 1. Inventory.
COUNT=$(python3 -c "from healthcraft.entities.decision_rules import load_decision_rules; print(len(load_decision_rules()))")
echo "current rule count: $COUNT"

if [ "$COUNT" -ge 100 ]; then
  echo "target reached (>=100 rules); exiting clean."
  exit 0
fi

# 2. Run the breadth + property tests.
if ! python3 -m pytest tests/test_agents_assemble/ -q --no-header > /tmp/loop-pytest.log 2>&1; then
  echo "FAIL: pytest failed before adding new rule. State is bad — investigate."
  tail -20 /tmp/loop-pytest.log
  exit 2
fi
echo "pytest pre-check passed: $(grep -E 'passed' /tmp/loop-pytest.log | tail -1)"

# 3. Run the fuzz harness; pass-rate must be 1.0.
if ! python3 scripts/fuzz_agents_assemble.py > /tmp/loop-fuzz.log 2>&1; then
  echo "FAIL: fuzz harness exited non-zero."
  tail -10 /tmp/loop-fuzz.log
  exit 3
fi
PASS_RATE=$(grep "pass_rate:" /tmp/loop-fuzz.log | awk '{print $2}')
if [ "$PASS_RATE" != "1.0" ]; then
  echo "FAIL: fuzz pass_rate $PASS_RATE != 1.0"
  exit 4
fi
echo "fuzz pre-check passed: pass_rate=$PASS_RATE"

# 4. Lint check.
if ! python3 -m ruff check src/healthcraft/entities/decision_rules_extended.py tests/test_agents_assemble/ >/tmp/loop-ruff.log 2>&1; then
  echo "FAIL: ruff check failed."
  cat /tmp/loop-ruff.log
  exit 5
fi
if ! python3 -m ruff format --check src/healthcraft/entities/decision_rules_extended.py tests/test_agents_assemble/ >>/tmp/loop-ruff.log 2>&1; then
  echo "auto-formatting..."
  python3 -m ruff format src/healthcraft/entities/decision_rules_extended.py tests/test_agents_assemble/
fi
echo "lint check passed."

# 5. If git working tree has uncommitted changes (e.g. an LLM just appended
# a rule), commit + push them. Otherwise nothing to do this tick.
if git diff --quiet -- src/healthcraft/entities/decision_rules_extended.py \
                        tests/test_agents_assemble/test_extended_rules_breadth.py; then
  echo "no rule-file changes to commit this tick."
  exit 0
fi

NEW_COUNT=$(python3 -c "from healthcraft.entities.decision_rules import load_decision_rules; print(len(load_decision_rules()))")
ADDED=$((NEW_COUNT - COUNT))
echo "committing $ADDED new rule(s); total $NEW_COUNT"

git add src/healthcraft/entities/decision_rules_extended.py \
        tests/test_agents_assemble/test_extended_rules_breadth.py
git commit -m "feat(agents-assemble): +${ADDED} rule(s) (${NEW_COUNT} total) [TDD loop]"

# Retry push up to 4 times on transient network errors.
for delay in 0 2 4 8 16; do
  [ "$delay" -gt 0 ] && sleep "$delay"
  if git push; then
    echo "pushed."
    exit 0
  fi
  echo "push failed; retrying after ${delay}s..."
done
echo "push failed after retries; commit is local only."
exit 6


# -----------------------------------------------------------------------------
# Prompt template for an LLM-driven loop (separate from this script).
# -----------------------------------------------------------------------------
#
# Per iteration, hand the LLM this prompt:
#
#   You are extending /home/user/healthcraft on branch
#   claude/agents-assemble-ideas-Rl9X3. Add 1-3 PURELY ADDITIVE
#   ED decision rules. Process:
#
#   1. Inventory:
#      python3 -c "from healthcraft.entities.decision_rules import load_decision_rules;
#                  rs=load_decision_rules(); print('count:', len(rs));
#                  [print(' ', r.name) for r in sorted(rs.values(), key=lambda x: x.name)]"
#      If count >= 100, exit cleanly without changes.
#
#   2. Pick rules NOT already in inventory. Skip:
#      - Anything with regression / logistic / categorical scoring.
#      - Anything obscure or non-validated.
#
#   3. Append failing tests to
#      tests/test_agents_assemble/test_extended_rules_breadth.py:
#      - loader returns rule by name
#      - low-input -> low risk
#      - high-input -> high (or appropriate) risk
#
#   4. Append rule entries to
#      src/healthcraft/entities/decision_rules_extended.py.
#      score_ranges MUST cover [0, sum(max_value)] with no gaps.
#
#   5. Run scripts/loop_iteration.sh — it lints, tests, and commits.
#
# The script refuses to commit a regression. The LLM cannot break the
# library by adding a bad rule.
