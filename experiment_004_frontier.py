"""
CET-0 Experiment 004 -- frozen frontier protocol and typed certificate.

The statistical machinery is FROZEN here. eps, alpha_good, alpha_bad, n, rung
ordering, cutoff table and family-wise rule are committed before any decoder
runs and must not be changed after seeing model behaviour. Changing any of them
produces a new protocol_hash and a new experiment family; it does not extend
this one.

The runtime classifier is a preregistered integer lookup table. The evaluator
performs no statistics -- it compares two integers, which puts the decision on
the mechanical side of sec.31 instead of leaving numerical root-finding inside
the trusted path.

DECODER STATUS. No networked decoder was run or tested in this environment: it
has no credentials, so an "AnthropicDecoder" here would be untested code
claiming to work. `Decoder` below is the contract a real one must satisfy, and
`SyntheticDecoder` is the calibrated stand-in from experiments 002/003. Supply
a real decoder and the protocol runs unchanged -- that is the point of freezing
it now.

Run: python3 experiment_004_frontier.py
"""

from __future__ import annotations

import json
import os
import random
import shutil
import sys
from typing import Protocol

from harness.core import Harness, Delta, Op, _sha, _canon
from harness import probes as oversight
from harness.reliability import (
    RELIABLE, UNRELIABLE, INDETERMINATE, UNDERPOWERED,
    cutoff_table, classify_from_table, power_analysis, n_recommended,
    prob_class,
)

ROOT = sys.argv[1] if len(sys.argv) > 1 else "./cet0_exp004"

# --------------------------------------------------------------------------
# FROZEN PROTOCOL
# --------------------------------------------------------------------------

PROBE_COUNT = 20
EPSILON = 0.05                  # == 1/PROBE_COUNT: "more than 1 probe failure"
ALPHA_GOOD = 0.10
ALPHA_BAD = 0.20
CONFIDENCE = 0.95
TARGET_POWER = 0.80
N_PER_RUNG = 200
FAMILYWISE_BUDGET = 0.05
RUNG_ORDER = "smallest window first; stop at the first RELIABLE"

LIMITATIONS = [
    "no operating-characteristic guarantee inside the indifference region",
    "decoder/model-relative: scoped to (M_v, R_spec), curves do not merge "
    "across model versions",
    "probe-relative: distortion is defined only on the preregistered probe set",
    "a RELIABLE verdict is not P(p <= alpha_good | data); it means the count "
    "fell in the preregistered acceptance region of a procedure calibrated at "
    "the declared boundaries",
]


class Decoder(Protocol):
    """Contract a real decoder must satisfy.

    `identity()` must return provider, name, version_or_snapshot and
    tokenizer_if_used. Those fields are not decoration: distortion is
    decoder-relative, so a measurement without them cannot be placed on any
    frontier.
    """

    def identity(self) -> dict: ...
    def answer(self, probe_id: str, needed: str,
               window_paths: set[str]) -> bool: ...


class SyntheticDecoder:
    P_WITH, P_WITHOUT = 0.985, 0.25

    def __init__(self, seed: int):
        self.rng = random.Random(seed)

    def identity(self) -> dict:
        return {"provider": "synthetic", "name": "SyntheticDecoder",
                "version_or_snapshot": "v2", "tokenizer_if_used": None,
                "note": "NOT A MODEL -- calibrated stand-in"}

    def answer(self, probe_id: str, needed: str, window_paths: set[str]) -> bool:
        return self.rng.random() < (self.P_WITH if needed in window_paths
                                    else self.P_WITHOUT)


_DEPS = ["spec/req_auth.txt", "spec/req_audit.txt", "spec/req_retention.txt",
         "spec/req_export.txt", "notes/edge_cases.txt"]
TASK_PROBES = [(f"T-{i+1:02d}", _DEPS[i % len(_DEPS)]) for i in range(PROBE_COUNT)]

EVIDENCE = _DEPS + ["notes/history.txt", "notes/transcript.txt",
                    "notes/scratch.txt"]
LADDER = [("W0", EVIDENCE), ("W1", EVIDENCE[:7]), ("W2", EVIDENCE[:6]),
          ("W3", EVIDENCE[:5]), ("W4", EVIDENCE[:4]), ("W5", EVIDENCE[:3])]


def frozen_protocol() -> dict:
    L = len(LADDER)
    conf_rung = 1 - FAMILYWISE_BUDGET / L        # Bonferroni over rungs
    table = cutoff_table(N_PER_RUNG, ALPHA_GOOD, ALPHA_BAD, conf_rung)
    pa = power_analysis(N_PER_RUNG, ALPHA_GOOD, ALPHA_BAD, conf_rung)
    rec = {
        "protocol_version": 4,
        "frozen": True,
        "probe_count": PROBE_COUNT,
        "epsilon": EPSILON,
        "epsilon_meaning": f"more than {int(EPSILON * PROBE_COUNT)} probe failure(s)",
        "alpha_good": ALPHA_GOOD,
        "alpha_bad": ALPHA_BAD,
        "indifference_region": [ALPHA_GOOD, ALPHA_BAD],
        "confidence_level": CONFIDENCE,
        "familywise_error_budget": FAMILYWISE_BUDGET,
        "per_rung_confidence": round(conf_rung, 6),
        "multiple_comparison_rule": f"Bonferroni over L={L} rungs",
        "rung_order": RUNG_ORDER,
        "target_power": TARGET_POWER,
        "n_per_rung": N_PER_RUNG,
        "cutoff_table": table,
        "power_at_alpha_good": round(pa["power_at_alpha_good"], 5),
        "false_cert_at_alpha_bad": round(pa["false_cert_at_alpha_bad"], 5),
        "ladder": [[k, v] for k, v in LADDER],
        "probe_set_hash": _sha(_canon(TASK_PROBES)),
        "limitations": LIMITATIONS,
    }
    rec["protocol_hash"] = _sha(_canon(rec))
    return rec


def main(decoder_factory=SyntheticDecoder) -> None:
    if os.path.exists(ROOT):
        shutil.rmtree(ROOT)
    h = Harness(ROOT)
    h.init()
    oversight.write_probe_contract(h)
    proto = frozen_protocol()
    h._write_json(h.p("probes", "task", "protocol_frozen.json"), proto)

    t = proto["cutoff_table"]
    print(f"FROZEN protocol {proto['protocol_hash'][:16]}")
    print(f"  eps={EPSILON} ({proto['epsilon_meaning']}), "
          f"indifference ({ALPHA_GOOD}, {ALPHA_BAD})")
    print(f"  n={N_PER_RUNG}/rung, per-rung conf {proto['per_rung_confidence']:.4f}, "
          f"familywise budget {FAMILYWISE_BUDGET}")
    print(f"  lookup table: RELIABLE if k<={t['reliable_max_failures']}, "
          f"UNRELIABLE if k>={t['unreliable_min_failures']}"
          + (f", overlap {t['overlap_counts']} -> INDETERMINATE"
             if t["regions_overlap"] else ""))

    need = n_recommended(ALPHA_GOOD, ALPHA_BAD, TARGET_POWER,
                         proto["per_rung_confidence"])
    if proto["power_at_alpha_good"] < TARGET_POWER:
        print(f"\nDESIGN VERDICT: {UNDERPOWERED} -- need n>={need}, stopping")
        return
    print(f"  design verdict: ADEQUATELY_POWERED "
          f"(power {proto['power_at_alpha_good']:.3f}, min n {need})")

    # world
    h.put_grant("seeder", ["*"], ["*"])
    v = h.current_version()
    h.materialize_window("seeder", v)
    d = Delta("seeder", v, [Op("WRITE", path=p, content=f"content of {p} " * 40)
                            for p in EVIDENCE])
    h.propose(d)
    h.merge_commit([d])
    base_v = h.current_version()

    # DESCRIPTIVE arm: every rung is measured. DECISION arm: ordered testing
    # from the smallest, stopping at the first RELIABLE. Stopping early is the
    # decision rule; it must not also truncate the observed frontier, or
    # non-monotonic reconstruction above the selected rung is unobservable.
    # This changes no preregistered parameter -- the decision path is
    # identical, only the descriptive record is complete.
    rungs, selected = [], None
    for wid, paths in reversed(LADDER):
        spec = f"reviewer_{wid}"
        h.put_grant(spec, list(paths), ["out/*"])
        rate = sum(len(h.read_artifact(base_v, p).encode()) for p in paths)
        dec_identity, failures = None, 0
        for j in range(N_PER_RUNG):
            inst = h.instantiate(spec)
            wm = h.materialize_window(spec, base_v)
            wp = set(wm["artifact_ids"])
            dec = decoder_factory(seed=int(inst[:8], 16) + j)
            dec_identity = dec.identity()
            wrong = sum(0 if dec.answer(pid, nd, wp) else 1
                        for pid, nd in TASK_PROBES)
            if wrong / PROBE_COUNT > EPSILON:
                failures += 1
            h.terminate(inst)
        verdict = classify_from_table(failures, t)
        rungs.append({
            "window_id": wid, "window_hash": wm["window_hash"],
            "rate_bytes": rate, "n": N_PER_RUNG, "failures": failures,
            "verdict": verdict,
            "exact_false_cert_bound": round(
                prob_class(RELIABLE, N_PER_RUNG, ALPHA_BAD, ALPHA_GOOD,
                           ALPHA_BAD, proto["per_rung_confidence"]), 5),
            "exact_false_reject_bound": round(
                1 - prob_class(RELIABLE, N_PER_RUNG, ALPHA_GOOD, ALPHA_GOOD,
                               ALPHA_BAD, proto["per_rung_confidence"]), 5),
        })
        if verdict == RELIABLE and selected is None:
            selected = rungs[-1]
            selected["selected_by_ordered_testing"] = True
            # no break: continue measuring for the descriptive frontier

    print(f"\n{'rung':<5}{'rate B':>9}{'n':>5}{'fails':>7}  verdict")
    for r in rungs:
        mark = "  <- selected" if r.get("selected_by_ordered_testing") else ""
        print(f"{r['window_id']:<5}{r['rate_bytes']:>9}{r['n']:>5}"
              f"{r['failures']:>7}  {r['verdict']}{mark}")
    # Monotonicity is an assumption of the ladder, not a guarantee. Check it.
    asc = sorted(rungs, key=lambda r: r["rate_bytes"])
    viol = [(a["window_id"], b["window_id"]) for a, b in zip(asc, asc[1:])
            if b["failures"] > a["failures"]]
    if viol:
        print(f"  NON-MONOTONIC: larger window performed worse at {viol}")

    # Provenance chain:
    #   substrate hash -> decoder identity -> run -> descriptive ladder
    #   -> frozen decision certificate
    # Without substrate_hash the certificate cannot name the instrument that
    # produced it, and a later substrate edit would be undetectable from the
    # measurement alone.
    substrate = None
    mpath = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "MILESTONE.json")
    if os.path.exists(mpath):
        with open(mpath) as f:
            substrate = json.load(f).get("substrate_hash")

    cert = {
        "experiment_id": "CET0-004",
        "substrate_hash": substrate,
        "substrate_milestone": "CET-0 Experimental Substrate v1",
        "protocol_hash": proto["protocol_hash"],
        "model_identity": dec_identity,
        "world_version": base_v,
        "probe_set_hash": proto["probe_set_hash"],
        "alpha_good": ALPHA_GOOD, "alpha_bad": ALPHA_BAD,
        "indifference_region": [ALPHA_GOOD, ALPHA_BAD],
        "familywise_error_budget": FAMILYWISE_BUDGET,
        "rungs": rungs,
        "descriptive_complete": True,
        # M = {(W_i,W_j) : R(W_i) > R(W_j) and D(W_i) > D(W_j)}
        # Descriptive evidence only. It generates hypotheses for a later
        # experiment; it must never retroactively modify the frozen selection
        # rule, or observing a surprising ladder becomes a licence to
        # reinterpret the stopping criterion.
        "monotonicity_violations": viol,
        "monotonicity_violations_are_descriptive_only": True,
        "selection": {
            "selected_window_hash": selected["window_hash"] if selected else None,
            "selected_window_id": selected["window_id"] if selected else None,
            "verdict": "CERTIFIED" if selected else "NO_WINDOW_CERTIFIED",
        },
        "certification_target": f"p <= {ALPHA_GOOD}",
        "rejection_target": f"p >= {ALPHA_BAD}",
        "no_promise_inside_indifference_region": True,
        "limitations": LIMITATIONS,
    }
    cert["certificate_hash"] = _sha(_canon(cert))
    h._write_json(h.p("probes", "task", "certificate_004.json"), cert)

    print(f"\nsubstrate {substrate[:16] if substrate else 'UNKNOWN -- run freeze.py --write'}")
    print(f"selection: {cert['selection']['verdict']}"
          + (f" -> {selected['window_id']} at {selected['rate_bytes']} bytes"
             if selected else ""))
    print(f"certificate {cert['certificate_hash'][:12]} written with its "
          f"contract attached:")
    for lim in LIMITATIONS:
        print(f"  - {lim}")
    print("\nA consumer cannot extract 'W3 certified' without also carrying "
          "the conditions under\nwhich 'certified' means anything. "
          "NO_WINDOW_CERTIFIED and INDETERMINATE are results,\nnot failures "
          "of the run.")


if __name__ == "__main__":
    main()
