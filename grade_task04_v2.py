"""
Evaluator-side grader v2 for task_04_policy_validity: outcome AND basis.

A probe passes iff BOTH hold:

  outcome_correct   same normalization rules as grade_task04.py v1:
                      bool    leading clause "no"/"false"/"not" vs "yes"/"true"
                      number  first numeric token equals expected
                      list    every expected token present (ci substring)
                      string  expected present (ci substring)
                      INSUFFICIENT never matches a concrete expectation
  basis_correct     any required_basis_token appears as a case-insensitive
                    substring of the decoder's stated basis for that probe

Run-level failure is Y_j = 1[any probe fails]: allowed_probe_failures_per_run
is 0 by declaration, not "5% distortion" -- with k=5 the distortion support is
{0, .2, .4, .6, .8, 1} and a 0.05 tolerance is just a misleading spelling of
zero.

Both failure components are recorded separately so basis-only failures
(correct answer, wrong epistemic grounding -- the Smoke v1 Q4 phenomenon)
stay measurable.

Usage: python3 grade_task04_v2.py <answers.json> [probes_v2.json]
where answers.json maps probe id -> {"answer": str, "basis": str}
"""

from __future__ import annotations

import json
import re
import sys


def norm(s: str) -> str:
    return s.strip().lower()


def outcome_correct(expected, answer: str) -> bool:
    a = norm(answer)
    if isinstance(expected, bool):
        if a.startswith("insufficient"):
            return False
        head = re.split(r"[.,;:\s]", a, 1)[0]
        if head in ("no", "false", "not"):
            return expected is False
        if head in ("yes", "true"):
            return expected is True
        return False
    if isinstance(expected, (int, float)):
        m = re.search(r"-?\d+(\.\d+)?", a)
        return m is not None and float(m.group()) == float(expected)
    if isinstance(expected, list):
        return not a.startswith("insufficient") and all(
            norm(tok) in a for tok in expected)
    return norm(str(expected)) in a


def basis_correct(tokens: list[str], basis: str) -> bool:
    b = norm(basis)
    return any(norm(t) in b for t in tokens)


def grade(answers: dict, probes: list[dict]) -> dict:
    per = []
    for p in probes:
        cell = answers.get(p["id"], {}) or {}
        ans = cell.get("answer", "") if isinstance(cell, dict) else str(cell)
        bas = cell.get("basis", "") if isinstance(cell, dict) else ""
        oc = outcome_correct(p["expected_outcome"], ans)
        bc = basis_correct(p["required_basis_tokens"], bas)
        per.append({
            "probe_id": p["id"], "answer": ans, "basis": bas,
            "outcome_correct": oc, "basis_correct": bc,
            "pass": oc and bc,
            "insufficient_declared": norm(ans).startswith("insufficient"),
        })
    k = len(probes)
    failed = [q["probe_id"] for q in per if not q["pass"]]
    outcome_failed = [q["probe_id"] for q in per if not q["outcome_correct"]]
    basis_only = [q["probe_id"] for q in per
                  if q["outcome_correct"] and not q["basis_correct"]]
    return {
        "k": k,
        "failed_probes": failed,
        "outcome_failed_probes": outcome_failed,
        "basis_only_failed_probes": basis_only,
        "distortion": round(len(failed) / k, 4),
        "run_failure": len(failed) > 0,
        "per_probe": per,
    }


if __name__ == "__main__":
    answers = json.load(open(sys.argv[1]))
    ppath = (sys.argv[2] if len(sys.argv) > 2 else
             "CET_REAL_TASKS_v1/task_04_policy_validity/probes/probes_v2.json")
    probes = json.load(open(ppath))["probes"]
    print(json.dumps(grade(answers, probes), indent=2))
