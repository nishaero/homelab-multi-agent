"""Routing evaluation: does a request go to the right specialist(s)?

  python evals/run_evals.py            # rule based router, no model needed
  python evals/run_evals.py --live     # the model planner, using the configured Ollama

A case passes when the set of roles in the plan equals the expected set. Safety behaviour (refusals,
approvals, injected instructions) is covered by the tests, which run with a scripted model.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hlagents.config import Config  # noqa: E402
from hlagents.coordinator import PLAN_PROMPT, PLAN_SCHEMA, _valid, rule_plan  # noqa: E402
from hlagents.gate import ModelGate  # noqa: E402
from hlagents.llm import OllamaLLM  # noqa: E402


def model_plan(llm, goal):
    msg = llm.chat([{"role": "system", "content": PLAN_PROMPT}, {"role": "user", "content": goal}], json_schema=PLAN_SCHEMA)
    return _valid(json.loads(msg["content"]).get("steps")) or []


def main():
    live = "--live" in sys.argv
    cases = json.loads((Path(__file__).parent / "cases.json").read_text())
    llm = OllamaLLM(Config.load(), ModelGate()) if live else None
    ok = 0
    for c in cases:
        try:
            plan = (model_plan(llm, c["goal"]) or rule_plan(c["goal"])) if live else rule_plan(c["goal"])   # same fallback as the real coordinator
        except Exception as e:  # noqa: BLE001
            plan, c["goal"] = [], c["goal"] + f"  ({type(e).__name__})"
        got = sorted({s["role"] for s in plan})
        good = got == sorted(c["roles"])
        ok += good
        print(f"{'PASS' if good else 'FAIL'}  {c['goal'][:70]:<70} expected {c['roles']} got {got}")
    print(f"\n{ok}/{len(cases)} correct ({'model planner' if live else 'rule router'})")


main()
