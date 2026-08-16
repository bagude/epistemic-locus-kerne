"""
Task-04 powered family: preregistered protocol record.

A NEW experiment family, superseding nothing: Task04 Smoke v1 (record
805adc1be2d59585) is preserved untouched -- it discovered the two defects
this protocol fixes. Changes justified by that run and frozen here, before
any decoder instance executes:

1. Outcome-plus-basis grading. Score is (y == y*) AND (B == B*): a probe
   passes only if the surface answer matches AND the stated basis cites the
   currently authoritative grounding (mechanical token test, declared in
   probes_v2.json). Motivated by W4/Q4: correct 'No' from 'v3 already
   permits 30 days' -- correct answer, wrong reconstructed world.

2. Exact 5-probe/5-rung statistics. The run-level failure condition is
   stated directly: Y_j = 1[any preregistered probe fails], i.e.
   allowed_probe_failures_per_run = 0. It is NOT spelled 'eps=0.05': with
   k=5 the distortion support is {0, .2, .4, .6, .8, 1} and a 5% tolerance
   is a misleading spelling of zero. The binomial lookup table is
   recalibrated for Bonferroni over L=5 candidate windows.

Running this script (re)computes the record deterministically from the
committed artifacts; the protocol_hash changes iff an artifact or parameter
changes. Substrate remains c871cc8e2994639c, unchanged.

Run from repo root: python3 experiment_task04_powered.py
"""

from __future__ import annotations

import hashlib
import json

from harness.core import _sha, _canon
from harness.reliability import cutoff_table, power_analysis, n_recommended
from taskpack import verify_pack
from make_decoder_prompt_v2 import build_prompt

ALPHA_GOOD, ALPHA_BAD = 0.10, 0.20
FAMILYWISE_BUDGET = 0.05
TARGET_POWER = 0.80
RUNGS = ["W4", "W3", "W2", "W1", "W0"]     # rate-ascending order
L = len(RUNGS)
CONF_RUNG = 1 - FAMILYWISE_BUDGET / L      # 0.99, Bonferroni over 5 rungs
N_PER_RUNG = 150                            # == n_recommended at these params

OUT = "results/task04_powered_n150"


def fsha(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def main() -> None:
    table = cutoff_table(N_PER_RUNG, ALPHA_GOOD, ALPHA_BAD, CONF_RUNG)
    pa = power_analysis(N_PER_RUNG, ALPHA_GOOD, ALPHA_BAD, CONF_RUNG)
    n_min = n_recommended(ALPHA_GOOD, ALPHA_BAD, TARGET_POWER, CONF_RUNG)
    assert N_PER_RUNG >= n_min, (N_PER_RUNG, n_min)
    assert pa["power_at_alpha_good"] >= TARGET_POWER

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
        "experiment_family": "CET0-REALTASK-004-POWERED",
        "protocol_version": 1,
        "frozen": True,
        "justified_by": "Task04 Smoke v1, record 805adc1be2d59585 "
                        "(preserved; not part of this family)",
        "substrate_hash": substrate,
        "pack_hash": pack_hash,
        "task_id": "task_04_policy_validity",
        "probe_count": 5,
        "probe_set_id": probes_v2["probe_set_id"],
        "probes_v2_hash": _sha(_canon(probes_v2)),
        "scoring": "probe pass iff outcome_correct AND basis_correct; "
                   "see probes_v2.json for the declared mechanical rules",
        "run_failure_condition": "Y_j = 1[any preregistered probe fails]",
        "allowed_probe_failures_per_run": 0,
        "distortion_support": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
        "alpha_good": ALPHA_GOOD,
        "alpha_bad": ALPHA_BAD,
        "indifference_region": [ALPHA_GOOD, ALPHA_BAD],
        "familywise_error_budget": FAMILYWISE_BUDGET,
        "multiple_comparison_rule": f"Bonferroni over L={L} rungs",
        "per_rung_confidence": round(CONF_RUNG, 6),
        "n_per_rung": N_PER_RUNG,
        "n_min_adequate": n_min,
        "target_power": TARGET_POWER,
        "power_at_alpha_good": round(pa["power_at_alpha_good"], 5),
        "false_cert_at_alpha_bad": round(pa["false_cert_at_alpha_bad"], 5),
        "cutoff_table": table,
        "rung_order": "rate-ascending (W4,W3,W2,W1,W0); decision arm stops "
                      "at first RELIABLE; every rung measured descriptively",
        "ladder_rungs": prompt_index,
        "decoder_identity_declared": {
            "provider": "anthropic",
            "name": "claude-fable-5",
            "version_or_snapshot": "session-configured claude-fable-5",
            "tokenizer_if_used": None,
            "reasoning_effort": "low",
            "interface": "one fresh rung-blind Claude Code workflow "
                         "subagent per instance; prompt passed verbatim in "
                         "the byte-identical Smoke-v1 wrapper; answers "
                         "returned via schema-enforced structured output",
            "sealing": "A_DECODER_SEALED: ASSUMED_UNVERIFIED -- instances "
                       "are instructed, not mechanically deprived, of "
                       "external channels; recorded zero tool use is "
                       "control evidence, not effect evidence",
        },
        "measurement_program": {
            "workflow_script": "workflow_task04_powered.js",
            "workflow_script_sha256": fsha("workflow_task04_powered.js"),
            "builder_sha256": fsha("build_workflow_task04.py"),
            "reference_grader_sha256": fsha("grade_task04_v2.py"),
            "prompt_generator_sha256": fsha("make_decoder_prompt_v2.py"),
            "cross_check": "in-flight JS grading must agree exactly with "
                           "grade_task04_v2.py re-applied to the raw "
                           "answers in the workflow journal; disagreement "
                           "voids the run",
        },
        "empirical_questions": {
            "sufficiency": "W3 vs W2 -- is the supersession statement inside "
                           "policy_v4 enough, or is the version manifest "
                           "load-bearing?",
            "contamination": "W1/W0 vs W2 -- does adding coherent superseded "
                             "evidence degrade reconstruction "
                             "(non-monotonic epistemic-window effect)?",
            "invalid_world_reconstruction": "W4 -- frequency of confident "
                                            "reconstruction of the obsolete "
                                            "world vs abstention",
        },
        "limitations": [
            "no operating-characteristic guarantee inside the indifference "
            "region",
            "decoder/model-relative: scoped to the declared decoder "
            "identity; curves do not merge across models or configurations",
            "basis grading is a token-level proxy for cited grounding; it "
            "cannot verify reasoning, and a decoder that name-drops v4 "
            "while reasoning from v3 would pass it",
            "a RELIABLE verdict means the failure count fell in the "
            "preregistered acceptance region, not P(p<=alpha_good|data)",
        ],
    }
    proto["protocol_hash"] = _sha(_canon(proto))
    with open(f"{OUT}/protocol_powered.json", "w") as f:
        json.dump(proto, f, indent=2, sort_keys=True)
    print(f"protocol {proto['protocol_hash'][:16]} -> "
          f"{OUT}/protocol_powered.json")
    print(f"  n={N_PER_RUNG}/rung (min adequate {n_min}), conf/rung "
          f"{CONF_RUNG}, power {pa['power_at_alpha_good']:.4f}")
    print(f"  table: RELIABLE k<={table['reliable_max_failures']}, "
          f"UNRELIABLE k>={table['unreliable_min_failures']}, "
          f"indeterminate {table['reliable_max_failures']+1}.."
          f"{table['unreliable_min_failures']-1}")


if __name__ == "__main__":
    main()
