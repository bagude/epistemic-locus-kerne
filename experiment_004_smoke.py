"""
CET-0 Experiment 004 -- SMOKE RUN: n=1, extreme rungs W4 and W2 only.

This is NOT the frozen protocol. Changing n (200 -> 1) and the ladder
(6 rungs -> 2) produces a new protocol_hash and therefore a new experiment
family, exactly as experiment_004_frontier.py declares. The frozen v4
protocol and its hash are untouched; both hashes are recorded side by side
so the family split is checkable rather than asserted.

The two rungs bracket the adequacy boundary of the preregistered ladder:

    W4 = EVIDENCE[:4]  -- 4 files, missing notes/edge_cases.txt, so 4 of
                          20 probes have no in-window dependency
                          (expected-bad extreme)
    W2 = EVIDENCE[:6]  -- 6 files, all five probe dependencies present
                          (expected-good extreme)

At n=1 the design is UNDERPOWERED by the protocol's own power analysis
(power 0.0 at alpha_good; min adequate n is 90), and the n=1 cutoff table
has reliable_max_failures = -1 and unreliable_min_failures = 2, so NO
observation can certify or reject: every rung verdict is necessarily
INDETERMINATE. The run is kept anyway because it exercises the full causal
chain (grant -> instance -> sealed window -> probe evaluation -> terminate)
end to end; its decision arm is recorded as VOID, descriptive only.

The decoder is the calibrated SyntheticDecoder -- this environment has no
model credentials, and the smoke record says so in model_identity.

Run: python3 experiment_004_smoke.py [root]
"""

from __future__ import annotations

import json
import os
import shutil
import sys

SMOKE_ROOT = sys.argv[1] if len(sys.argv) > 1 else "./cet0_exp004_smoke"
sys.argv = [sys.argv[0]]          # keep our argv out of e4.ROOT at import

import experiment_004_frontier as e4
from harness.core import Harness, Delta, Op, _sha, _canon
from harness.reliability import (
    RELIABLE, classify_from_table, n_recommended, prob_class,
)

# Frozen-family hash BEFORE any override, so the record can show the split.
FROZEN_V4_HASH = e4.frozen_protocol()["protocol_hash"]

# --- smoke overrides: new protocol family, frozen files untouched ---------
N_SMOKE = 1
e4.N_PER_RUNG = N_SMOKE
e4.LADDER = [("W2", e4.EVIDENCE[:6]), ("W4", e4.EVIDENCE[:4])]
e4.ROOT = SMOKE_ROOT

proto = e4.frozen_protocol()
table = proto["cutoff_table"]

print(f"SMOKE protocol {proto['protocol_hash'][:16]} "
      f"(frozen v4 family {FROZEN_V4_HASH[:16]} -- distinct, as required)")
print(f"  n={N_SMOKE}/rung, ladder {[w for w, _ in e4.LADDER]}, "
      f"eps={e4.EPSILON} ({proto['epsilon_meaning']})")
print(f"  n=1 table: RELIABLE if k<={table['reliable_max_failures']}, "
      f"UNRELIABLE if k>={table['unreliable_min_failures']} "
      f"-> no k in {{0,1}} can decide")

need = n_recommended(e4.ALPHA_GOOD, e4.ALPHA_BAD, e4.TARGET_POWER,
                     proto["per_rung_confidence"])
design_verdict = ("ADEQUATELY_POWERED"
                  if proto["power_at_alpha_good"] >= e4.TARGET_POWER
                  else "UNDERPOWERED")
print(f"  design verdict: {design_verdict} "
      f"(power {proto['power_at_alpha_good']:.3f} at alpha_good, "
      f"min adequate n {need})")
if design_verdict == "UNDERPOWERED":
    print("  frozen entrypoint would STOP here; smoke run proceeds "
          "DESCRIPTIVELY ONLY -- decision arm is VOID")

# --- world seeding: identical to experiment_004_frontier.main() -----------
if os.path.exists(SMOKE_ROOT):
    shutil.rmtree(SMOKE_ROOT)
h = Harness(SMOKE_ROOT)
h.init()
h._write_json(h.p("probes", "task", "protocol_smoke.json"), proto)

h.put_grant("seeder", ["*"], ["*"])
v = h.current_version()
h.materialize_window("seeder", v)
d = Delta("seeder", v, [Op("WRITE", path=p, content=f"content of {p} " * 40)
                        for p in e4.EVIDENCE])
h.propose(d)
h.merge_commit([d])
base_v = h.current_version()

# --- measurement: ordered smallest-first, every rung measured -------------
rungs, selected, dec_identity = [], None, None
for wid, paths in reversed(e4.LADDER):
    spec = f"reviewer_{wid}"
    h.put_grant(spec, list(paths), ["out/*"])
    rate = sum(len(h.read_artifact(base_v, p).encode()) for p in paths)
    failures = 0
    probe_record = []
    for j in range(N_SMOKE):
        inst = h.instantiate(spec)
        wm = h.materialize_window(spec, base_v)
        wp = set(wm["artifact_ids"])
        dec = e4.SyntheticDecoder(seed=int(inst[:8], 16) + j)
        dec_identity = dec.identity()
        answers = [(pid, nd, dec.answer(pid, nd, wp))
                   for pid, nd in e4.TASK_PROBES]
        wrong = sum(0 if ok else 1 for _, _, ok in answers)
        probe_record.append({"instance_id": inst, "wrong": wrong,
                             "failed_probes": [pid for pid, _, ok in answers
                                               if not ok]})
        if wrong / e4.PROBE_COUNT > e4.EPSILON:
            failures += 1
        h.terminate(inst)
    verdict = classify_from_table(failures, table)
    deps_in = {nd for _, nd in e4.TASK_PROBES if nd in set(paths)}
    rungs.append({
        "window_id": wid, "window_hash": wm["window_hash"],
        "rate_bytes": rate, "n": N_SMOKE, "failures": failures,
        "verdict": verdict,
        "probe_deps_in_window": f"{len(deps_in)}/5",
        "instances": probe_record,
        "exact_false_cert_bound": round(
            prob_class(RELIABLE, N_SMOKE, e4.ALPHA_BAD, e4.ALPHA_GOOD,
                       e4.ALPHA_BAD, proto["per_rung_confidence"]), 5),
    })
    if verdict == RELIABLE and selected is None:
        selected = rungs[-1]

print(f"\n{'rung':<5}{'rate B':>8}{'deps':>6}{'n':>4}{'fails':>7}  verdict")
for r in rungs:
    print(f"{r['window_id']:<5}{r['rate_bytes']:>8}"
          f"{r['probe_deps_in_window']:>6}{r['n']:>4}{r['failures']:>7}"
          f"  {r['verdict']}")

substrate = None
mpath = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "MILESTONE.json")
if os.path.exists(mpath):
    with open(mpath) as f:
        substrate = json.load(f).get("substrate_hash")

record = {
    "experiment_id": "CET0-004-SMOKE-n1-W4W2",
    "purpose": "end-to-end smoke of the exp004 machinery at n=1 on the two "
               "rungs bracketing the adequacy boundary; no statistical claim",
    "substrate_hash": substrate,
    "smoke_protocol_hash": proto["protocol_hash"],
    "frozen_v4_protocol_hash": FROZEN_V4_HASH,
    "deviations_from_frozen_v4": [
        "n_per_rung 200 -> 1",
        "ladder [W0..W5] -> [W2, W4]",
    ],
    "design_verdict": design_verdict,
    "min_adequate_n": need,
    "decision_arm": "VOID -- underpowered by preregistered power analysis; "
                    "no verdict at n=1 can be anything but INDETERMINATE",
    "model_identity": dec_identity,
    "world_version": base_v,
    "probe_set_hash": proto["probe_set_hash"],
    "rungs": rungs,
    "selection": {
        "selected_window_id": selected["window_id"] if selected else None,
        "verdict": "CERTIFIED" if selected else "NO_WINDOW_CERTIFIED",
    },
    "no_promise_inside_indifference_region": True,
    "limitations": e4.LIMITATIONS + [
        "smoke run: descriptive evidence about the machinery only, not about "
        "any window's adequacy",
    ],
}
record["record_hash"] = _sha(_canon(record))
h._write_json(h.p("probes", "task", "smoke_004.json"), record)

print(f"\nsubstrate {substrate[:16] if substrate else 'UNKNOWN'}")
print(f"selection: {record['selection']['verdict']} (expected: n=1 cannot "
      f"certify)")
print(f"smoke record {record['record_hash'][:12]} -> "
      f"{h.p('probes', 'task', 'smoke_004.json')}")
