"""
Task-04 PILOT family: preregistered protocol record. Estimation-only.

Purpose: size any confirmatory run from observed rates instead of guessing.
The unanswered Task-04 questions are COMPARISONS (W3 vs W2 sufficiency;
W1/W0 vs W2 contamination), and the n they need depends on effect sizes no
one has measured. This pilot estimates the per-rung run-failure rates with
exact intervals and makes NO reliability claims:

  - no verdicts, no certification, no cutoff table, no selection rule
  - per-rung two-sided 95% Clopper-Pearson intervals on p = P(run failure)
  - declared comparisons, reported as interval overlap + exact
    Fisher-style p-values, all DESCRIPTIVE

W4 is not re-sampled: the archived aborted-run data (77 instances, journal
preserved, summary 692e55d4d64a6ef7) is carried as its estimate, clearly
labeled as coming from a different decoder identity (fable, not haiku) --
the two are never pooled.

Decoder: claude-haiku-4-5 at low reasoning effort. This is a deliberately
DIFFERENT decoder identity from Smoke v1 and the aborted powered run;
distortion is decoder-relative and none of these curves merge. The pilot
sizes the pilot's decoder; a confirmatory run must re-declare its own.

Run from repo root: python3 experiment_task04_pilot.py
"""

from __future__ import annotations

import hashlib
import json

from harness.core import _sha, _canon
from taskpack import verify_pack
from make_decoder_prompt_v2 import build_prompt

N_PER_RUNG = 40
BATCH_SIZE = 10
RUNGS = ["W3", "W2", "W1", "W0"]
OUT = "results/task04_pilot_n40"


def fsha(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def main() -> None:
    ok, bad, pack_hash = verify_pack("CET_REAL_TASKS_v1")
    assert ok, bad
    substrate = json.load(open("MILESTONE.json"))["substrate_hash"]
    probes_v2 = json.load(open(
        "CET_REAL_TASKS_v1/task_04_policy_validity/probes/probes_v2.json"))

    prompt_index = []
    for r in RUNGS:
        rec = build_prompt("CET_REAL_TASKS_v1", "task_04_policy_validity", r)
        prompt_index.append({k: v for k, v in rec.items() if k != "prompt"})

    proto = {
        "experiment_family": "CET0-REALTASK-004-PILOT",
        "protocol_version": 1,
        "frozen": True,
        "purpose": "estimation-only pilot to measure per-rung run-failure "
                   "rates and size a confirmatory comparison run; no "
                   "reliability claim of any kind is derivable from this "
                   "family",
        "substrate_hash": substrate,
        "pack_hash": pack_hash,
        "task_id": "task_04_policy_validity",
        "probes_v2_hash": _sha(_canon(probes_v2)),
        "scoring": "outcome_correct AND basis_correct per probes_v2.json; "
                   "run failure Y_j = 1[any probe fails]; "
                   "allowed_probe_failures_per_run = 0",
        "rungs": RUNGS,
        "n_per_rung": N_PER_RUNG,
        "batching": {
            "batch_size": BATCH_SIZE,
            "order": "round-robin across rungs (W3#j,W2#j,W1#j,W0#j,...), "
                     "sequential batches; truncation at any point leaves "
                     "near-balanced per-rung counts",
        },
        "estimation": {
            "interval": "two-sided 95% Clopper-Pearson per rung",
            "comparisons_declared": [
                "sufficiency: W3 vs W2",
                "contamination: W1 vs W2",
                "contamination: W0 vs W2",
            ],
            "comparison_statistic": "two-sided Fisher exact p-value, "
                                    "descriptive only (no alpha, no "
                                    "decision)",
        },
        "w4_handling": "not re-sampled; archived aborted-run estimate "
                       "(77/77 failures, fable decoder) carried alongside, "
                       "never pooled -- different decoder identity",
        "decoder_identity_declared": {
            "provider": "anthropic",
            "name": "claude-haiku-4-5",
            "version_or_snapshot": "claude-haiku-4-5-20251001 (via workflow "
                                   "model alias 'haiku')",
            "tokenizer_if_used": None,
            "reasoning_effort": "low",
            "interface": "one fresh rung-blind workflow subagent per "
                         "instance; byte-identical Smoke-v1 wrapper; "
                         "schema-enforced structured output",
            "sealing": "A_DECODER_SEALED: ASSUMED_UNVERIFIED -- instructed, "
                       "not mechanically deprived, of external channels",
            "note": "token-minimized configuration chosen deliberately; "
                    "rates measured here are rates OF THIS DECODER and do "
                    "not transfer to any other identity",
        },
        "prompts": "byte-identical to the powered family's committed "
                   "prompts (results/task04_powered_n150/prompts)",
        "ladder_rungs": prompt_index,
        "measurement_program": {
            "workflow_script": "workflow_task04_pilot.js",
            "workflow_script_sha256": fsha("workflow_task04_pilot.js"),
            "builder_sha256": fsha("build_workflow_task04_pilot.py"),
            "reference_grader_sha256": fsha("grade_task04_v2.py"),
            "prompt_generator_sha256": fsha("make_decoder_prompt_v2.py"),
            "cross_check": "reference grader re-applied to journal raw "
                           "answers must agree exactly with in-flight "
                           "grading; disagreement voids the run",
        },
        "limitations": [
            "estimation-only: nothing in this family certifies or rejects "
            "any window",
            "n=40 intervals are wide (zero failures gives upper bound "
            "~0.088); the pilot exists to size a real run, not replace it",
            "decoder-relative: haiku rates say nothing about any other "
            "model's rates",
            "basis grading remains a token-level proxy for cited grounding",
        ],
    }
    proto["protocol_hash"] = _sha(_canon(proto))
    import os
    os.makedirs(OUT, exist_ok=True)
    with open(f"{OUT}/protocol_pilot.json", "w") as f:
        json.dump(proto, f, indent=2, sort_keys=True)
    print(f"protocol {proto['protocol_hash'][:16]} -> {OUT}/protocol_pilot.json")
    print(f"  {len(RUNGS)} rungs x n={N_PER_RUNG} = "
          f"{len(RUNGS) * N_PER_RUNG} instances, batches of {BATCH_SIZE}, "
          f"decoder haiku/low-effort")


if __name__ == "__main__":
    main()
