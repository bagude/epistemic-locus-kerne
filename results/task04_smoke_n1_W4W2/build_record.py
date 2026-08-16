"""Assemble the content-addressed run record for the task_04 n=1 smoke.

Pulls together what EXECUTION_GUIDE step 4 requires -- substrate hash,
decoder identity, window hashes, probe hash, instance/evaluation ids --
plus the graded results and the n=1 classification. Run from repo root:

    python3 results/task04_smoke_n1_W4W2/build_record.py
"""

import json
import os
import sys

sys.path.insert(0, os.getcwd())
from harness.core import _sha, _canon                      # noqa: E402
from harness.reliability import cutoff_table, classify_from_table  # noqa: E402
from taskpack import verify_pack                           # noqa: E402

OUT = "results/task04_smoke_n1_W4W2"
EPSILON, ALPHA_GOOD, ALPHA_BAD = 0.05, 0.10, 0.20
N = 1
CONF_RUNG = 1 - 0.05 / 2          # Bonferroni over the 2 rungs actually run

index = {e["rung"]: e for e in json.load(open("prompts/prompt_index.json"))}
ok, bad, pack_hash = verify_pack("CET_REAL_TASKS_v1")
assert ok, bad
substrate = json.load(open("MILESTONE.json"))["substrate_hash"]
table = cutoff_table(N, ALPHA_GOOD, ALPHA_BAD, CONF_RUNG)

rungs = []
for rung, inst_id in [("W4", "subagent-W4-inst1"), ("W2", "subagent-W2-inst1")]:
    g = json.load(open(f"{OUT}/graded_{rung}_inst1.json"))
    failures = 1 if g["distortion"] > EPSILON else 0
    e = index[rung]
    rungs.append({
        "window_id": rung, "window_hash": e["window_hash"],
        "rate_bytes": e["rate_bytes"], "prompt_hash": e["prompt_hash"],
        "ladder_file": e["ladder_file"],
        "n": N, "instance_id": inst_id,
        "k_probes": g["k"], "wrong": g["wrong"],
        "task_distortion": g["distortion"],
        "run_failures": failures,
        "verdict": classify_from_table(failures, table),
        "insufficient_declared_on": [q["probe_id"] for q in g["per_probe"]
                                     if q["insufficient_declared"]],
        "wrong_probes": [q["probe_id"] for q in g["per_probe"]
                         if not q["correct"]],
    })

record = {
    "experiment_id": "CET0-REALTASK-004-SMOKE-n1-W4W2",
    "task_id": "task_04_policy_validity",
    "purpose": "first real-decoder smoke of the exp004 machinery on a real "
               "task pack: n=1 on the two compositionally extreme rungs "
               "(W2 current-only, W4 stale-historical-only); no statistical "
               "claim",
    "substrate_hash": substrate,
    "pack_hash": pack_hash,
    "probe_set_hash": index["W2"]["probe_set_hash"],
    "world_version": "pack-static (CET_REAL_TASKS_v1 world/, no CET-0 "
                     "commit chain; windows sealed by prompt generator)",
    "decoder_identity": {
        "provider": "anthropic",
        "name": "claude-fable-5",
        "version_or_snapshot": "claude-fable-5 (session-configured; "
                               "last_served_model claude-fable-5)",
        "tokenizer_if_used": None,
        "interface": "fresh Claude Code subagent session per instance; "
                     "prompt passed verbatim inside a byte-identical "
                     "no-tools wrapper; harness recorded 0 tool uses for "
                     "each instance",
    },
    "contamination_attestation": {
        "observed_oracle_paths": [],
        "identity_complete": True,
        "basis": "oracle barrier enforced mechanically by "
                 "make_decoder_prompt.py (oracle/, probes.json excluded); "
                 "decoder instances were fresh sessions receiving only the "
                 "generated prompt; rung blindness held (wrapper "
                 "byte-identical across rungs, no mention of ladder or "
                 "measurement); the orchestrator/evaluator HAS seen "
                 "oracle material but never authored task prose into the "
                 "prompt -- binding text in probe_questions.json derives "
                 "from task.md wording only",
        "residual_assumption": "A_DECODER_SEALED: instances had tool access "
                               "and were instructed, not sandboxed, away "
                               "from it; 0 recorded tool uses is control "
                               "evidence, not effect evidence -- "
                               "ASSUMED_UNVERIFIED in the substrate's "
                               "risk-register sense",
    },
    "preregistered_blockers_carried": [
        "E_PROBE_COUNT_MISMATCH: k=5 vs frozen k=20; eps=0.05 on support "
        "1/5 means zero probe failures allowed, so run-failure == any "
        "wrong probe",
        "UNDERPOWERED: n=1; cutoff table admits no decision "
        f"(RELIABLE if k<={table['reliable_max_failures']}, UNRELIABLE if "
        f"k>={table['unreliable_min_failures']})",
    ],
    "decision_arm": "VOID -- underpowered and outside the frozen protocol "
                    "family; descriptive evidence only",
    "epsilon": EPSILON, "alpha_good": ALPHA_GOOD, "alpha_bad": ALPHA_BAD,
    "per_rung_confidence": round(CONF_RUNG, 6),
    "rungs": rungs,
    "selection": {"verdict": "NO_WINDOW_CERTIFIED",
                  "selected_window_id": None},
    "descriptive_findings": [
        "W2 (1009B, current docs): distortion 0.0 -- all five probes "
        "correct, grounded in policy_v4 precedence",
        "W4 (541B, stale docs only): distortion 0.8 -- confident fluent "
        "answers grounded in superseded v3/2025-exception; INSUFFICIENT "
        "declared on only 1 of 5 probes (Q5)",
        "W4 Q4 scored correct for the wrong reason: expected 'exception "
        "does not change the answer' via v4 supersession, decoder said "
        "'No' because v3 already permits 30 days -- token-level grading "
        "cannot see this; visible only in the raw answer text",
        "the pack's thesis (current authority vs plausible historical "
        "evidence) is what the two extremes measure: the stale window "
        "produced confabulation, not insufficiency declarations",
    ],
    "artifacts": {
        "raw_answers": ["answers_W2_inst1.json", "answers_W4_inst1.json"],
        "graded": ["graded_W2_inst1.json", "graded_W4_inst1.json"],
        "prompts": ["prompt_W2.txt", "prompt_W4.txt"],
        "grader": "grade_task04.py (repo root)",
        "binding": "CET_REAL_TASKS_v1/task_04_policy_validity/"
                   "probe_questions.json",
    },
    "no_promise_inside_indifference_region": True,
}
record["record_hash"] = _sha(_canon(record))
with open(f"{OUT}/record.json", "w") as f:
    json.dump(record, f, indent=2, sort_keys=True)
print(f"record {record['record_hash'][:16]} -> {OUT}/record.json")
for r in rungs:
    print(f"  {r['window_id']}: D={r['task_distortion']}, "
          f"failures={r['run_failures']}, verdict={r['verdict']}")
