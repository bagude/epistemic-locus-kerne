"""
Evaluator-side grader for task_04_policy_validity smoke runs.

Grades raw decoder JSON answers against probes/probes.json. Grading is
deliberately mechanical and normalization is declared here, in code, so a
graded record can be re-derived from the raw answers alone:

  bool     "no"/"false" -> False, "yes"/"true" -> True, judged on the leading
           clause of the answer; INSUFFICIENT never matches a bool
  number   first integer token in the answer must equal expected
  list     every expected token must appear (case-insensitive substring) and
           the answer must not be INSUFFICIENT
  string   expected must appear as a case-insensitive substring

An answer of INSUFFICIENT is graded like any other answer: wrong whenever the
probe's expectation is a concrete value. That is the point of the ladder --
a window too small to answer produces distortion, whether the decoder
confabulates or correctly declares insufficiency. The two failure modes are
distinguished descriptively in the record (`insufficient_declared`), never in
the score.

Usage: python3 grade_task04.py <answers.json> [probes.json]
"""

from __future__ import annotations

import json
import re
import sys


def norm(s: str) -> str:
    return s.strip().lower()


def grade_one(expected, answer: str) -> bool:
    a = norm(answer)
    if isinstance(expected, bool):
        if a.startswith(("insufficient",)):
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


def grade(answers: dict, probes: list[dict]) -> dict:
    per = []
    for p in probes:
        ans = answers.get(p["id"], "")
        per.append({
            "probe_id": p["id"],
            "answer": ans,
            "correct": grade_one(p["expected"], ans),
            "insufficient_declared": norm(ans).startswith("insufficient"),
        })
    wrong = sum(0 if q["correct"] else 1 for q in per)
    k = len(probes)
    return {"k": k, "wrong": wrong, "distortion": round(wrong / k, 4),
            "per_probe": per}


if __name__ == "__main__":
    answers = json.load(open(sys.argv[1]))
    ppath = (sys.argv[2] if len(sys.argv) > 2 else
             "CET_REAL_TASKS_v1/task_04_policy_validity/probes/probes.json")
    probes = json.load(open(ppath))["probes"]
    print(json.dumps(grade(answers, probes), indent=2))
