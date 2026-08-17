"""
Evaluator-side grader v3 for task_04_policy_validity: three-valued outcomes.

Per probe:  PASS            outcome CORRECT and basis cited from the current
                            world (token rule, unchanged from v2)
            CONFIDENT_FAIL  outcome WRONG, or CORRECT with a wrong basis
            ABSTAINED       answer begins with INSUFFICIENT

Per run:    decision_failure   any probe not PASS          (strict; decision)
            confident_failure  any probe CONFIDENT_FAIL    (descriptive)
            abstention_run     no CONFIDENT_FAIL, >=1 ABSTAINED (descriptive)

Q5 outcome is CORRECT iff 'v4' is in the answer, or 'current policy' is in
the answer and 'v4' is in the basis -- the v2 literal-filename substring
graded title-level naming of the correct authority as wrong (17/20 of the
pilot's failures).

Usage: python3 grade_task04_v3.py <answers.json> [probes_v3.json]
"""

from __future__ import annotations

import json
import re
import sys


def norm(s: str) -> str:
    return str(s or "").strip().lower()


def outcome_of(p: dict, answer: str, basis: str) -> str:
    a = norm(answer)
    if a.startswith("insufficient"):
        return "ABSTAINED"
    exp = p["expected_outcome"]
    if p.get("outcome_rule") == "q5_normalization":
        if "v4" in a or ("current policy" in a and "v4" in norm(basis)):
            return "CORRECT"
        return "WRONG"
    if isinstance(exp, bool):
        head = re.split(r"[.,;:\s]", a, 1)[0]
        if head in ("no", "false", "not"):
            return "CORRECT" if exp is False else "WRONG"
        if head in ("yes", "true"):
            return "CORRECT" if exp is True else "WRONG"
        return "WRONG"
    if isinstance(exp, (int, float)):
        m = re.search(r"-?\d+(\.\d+)?", a)
        return ("CORRECT" if m and float(m.group()) == float(exp) else "WRONG")
    if isinstance(exp, list):
        return ("CORRECT" if all(norm(t) in a for t in exp) else "WRONG")
    return "CORRECT" if norm(str(exp)) in a else "WRONG"


def classify(p: dict, cell) -> dict:
    ans = cell.get("answer", "") if isinstance(cell, dict) else str(cell)
    bas = cell.get("basis", "") if isinstance(cell, dict) else ""
    out = outcome_of(p, ans, bas)
    if out == "ABSTAINED":
        cls = "ABSTAINED"
    else:
        bc = any(norm(t) in norm(bas) for t in p["required_basis_tokens"])
        cls = "PASS" if (out == "CORRECT" and bc) else "CONFIDENT_FAIL"
    return {"probe_id": p["id"], "answer": ans, "basis": bas,
            "outcome": out, "class": cls}


def grade(answers: dict, probes: list[dict]) -> dict:
    per = [classify(p, answers.get(p["id"], {}) or {}) for p in probes]
    conf = [q["probe_id"] for q in per if q["class"] == "CONFIDENT_FAIL"]
    abst = [q["probe_id"] for q in per if q["class"] == "ABSTAINED"]
    return {
        "k": len(probes),
        "confident_fail_probes": conf,
        "abstained_probes": abst,
        "decision_failure": bool(conf or abst),
        "confident_failure": bool(conf),
        "abstention_run": bool(abst) and not conf,
        "per_probe": per,
    }


if __name__ == "__main__":
    answers = json.load(open(sys.argv[1]))
    ppath = (sys.argv[2] if len(sys.argv) > 2 else
             "CET_REAL_TASKS_v1/task_04_policy_validity/probes/probes_v3.json")
    probes = json.load(open(ppath))["probes"]
    print(json.dumps(grade(answers, probes), indent=2))
