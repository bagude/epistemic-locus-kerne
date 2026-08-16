"""
CET-0 Experiment 002 -- window rate-distortion, epistemic reliability frontier.

    min R(W)  s.t.  P(D_Q(W) > eps) <= alpha

Not a single curve. A window that passes once is not evidence; the question is
the smallest window whose fresh-instance reconstruction stays below tolerated
distortion at a declared reliability level.

PREREGISTRATION. eps, alpha, n, the probe set, and the window ladder are all
committed and hashed BEFORE any instance runs. The selection rule is fixed in
advance too, so the frontier cannot be chosen after seeing the curve.

DECODER. No model is wired in here. The decoder is a seeded synthetic stand-in
with a declared evidence dependency per probe, present so the machinery can be
exercised and its statistics checked. THE NUMBERS BELOW SAY NOTHING ABOUT ANY
MODEL. Swap `SyntheticDecoder` for a real one and the recorded identity fields
are what make the resulting points causally interpretable.

Every observation is scoped to (M_v, R_spec). Do not merge curves across model
versions: a model upgrade is a different channel, not more samples.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import shutil
import sys

from harness.core import Harness, Delta, Op, _sha, _canon
from harness import probes as oversight

ROOT = sys.argv[1] if len(sys.argv) > 1 else "./cet0_exp002"

# --------------------------------------------------------------------------
# Preregistered protocol. Frozen before the run.
# --------------------------------------------------------------------------

PROTOCOL_VERSION = 2
# v1 was run and discarded. Two defects, both found by running it:
#
#  (a) EPSILON was incommensurate with probe granularity. With k probes,
#      D_Q takes values in multiples of 1/k, so eps=0.05 with k=5 meant
#      "D > 0" -- a declared 5% tolerance that actually tolerated nothing.
#      Fixed by k=20, making 1/k == eps exactly.
#
#  (b) The selection rule ranked windows by point estimate over statistically
#      indistinguishable candidates. In v1 W0..W3 all contained every probe
#      dependency and so shared one true failure rate, yet observed failures
#      were 7,4,1,6 -- pure sampling noise -- and the rule selected W2 (7400 B)
#      over the smaller and equally adequate W3 (6240 B). Fixed by selecting on
#      the confidence bound and reporting statistically tied candidates rather
#      than silently picking one.
#
# The protocol hash changes with these edits, so v1 results are not
# grandfathered under the v2 protocol.

EPSILON = 0.05          # tolerated task distortion
ALPHA = 0.20            # tolerated probability of exceeding it
N_INSTANCES = 30        # fresh Self instances per window
CONFIDENCE = 0.95       # one-sided bound on P(D > eps)
SELECTION_RULE = ("smallest R(W) whose one-sided upper confidence bound on "
                  "P(D_Q > eps) is <= alpha; report all candidates whose "
                  "bounds overlap the selected one as statistically tied")

# Task probes and the evidence each one depends on.
_DEPS = ["spec/req_auth.txt", "spec/req_audit.txt", "spec/req_retention.txt",
         "spec/req_export.txt", "notes/edge_cases.txt"]
TASK_PROBES = [(f"T-{i+1:02d}", _DEPS[i % len(_DEPS)]) for i in range(20)]

# Nested deterministic reductions W_0 ⊃ W_1 ⊃ ... ⊃ W_k.
EVIDENCE = [
    "spec/req_auth.txt", "spec/req_audit.txt", "spec/req_retention.txt",
    "spec/req_export.txt", "notes/edge_cases.txt", "notes/history.txt",
    "notes/transcript.txt", "notes/scratch.txt",
]
LADDER = [
    ("W0", EVIDENCE),
    ("W1", EVIDENCE[:7]),
    ("W2", EVIDENCE[:6]),
    ("W3", EVIDENCE[:5]),
    ("W4", EVIDENCE[:4]),
    ("W5", EVIDENCE[:3]),
]

MODEL_IDENTITY = {
    "provider": "synthetic",
    "name": "SyntheticDecoder",
    "version_or_snapshot": "v1",
    "tokenizer_if_used": None,
    "note": "NOT A MODEL -- machinery validation only",
}


def protocol_hash() -> str:
    return _sha(_canon({
        "protocol_version": PROTOCOL_VERSION,
        "epsilon": EPSILON, "alpha": ALPHA, "n": N_INSTANCES,
        "confidence": CONFIDENCE, "selection_rule": SELECTION_RULE,
        "probes": TASK_PROBES, "ladder": LADDER,
        "model_identity": MODEL_IDENTITY,
    }))


# --------------------------------------------------------------------------
# Statistics
# --------------------------------------------------------------------------

def clopper_pearson_upper(k: int, n: int, conf: float = CONFIDENCE) -> float:
    """One-sided upper bound on a binomial rate. With small n and zero
    observed failures the bound is ~3/n, so alpha cannot be certified below
    that however clean the run looks."""
    if k >= n:
        return 1.0
    lo, hi = 0.0, 1.0
    target = 1.0 - conf
    for _ in range(200):
        mid = (lo + hi) / 2
        # P(X <= k | p=mid)
        cdf = sum(math.comb(n, i) * mid**i * (1 - mid)**(n - i)
                  for i in range(k + 1))
        if cdf > target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def clopper_pearson_lower(k: int, n: int, conf: float = CONFIDENCE) -> float:
    if k <= 0:
        return 0.0
    lo, hi = 0.0, 1.0
    target = 1.0 - conf
    for _ in range(200):
        mid = (lo + hi) / 2
        sf = sum(math.comb(n, i) * mid**i * (1 - mid)**(n - i)
                 for i in range(k, n + 1))
        if sf > target:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def n_required_at_rate(p_true: float, alpha: float,
                       conf: float = CONFIDENCE) -> int:
    """Instances needed to certify P(fail) <= alpha when the TRUE rate is
    p_true. The zero-failure formula below is the p_true=0 special case, and
    using it to size a run silently assumes perfection: at any nonzero true
    rate the required n is far larger. Sizing v2 from the zero-failure bound is
    exactly why n=30 could not certify alpha=0.20 against a true rate near
    0.12."""
    if p_true >= alpha:
        return -1                      # not certifiable at any n
    n = 5
    while n <= 20000:
        k = int(round(p_true * n))
        if clopper_pearson_upper(k, n, conf) <= alpha:
            return n
        n += 5
    return -1


def n_required(alpha: float, conf: float = CONFIDENCE) -> int:
    """Instances needed for a zero-failure run to certify P(fail) <= alpha."""
    n = 1
    while clopper_pearson_upper(0, n, conf) > alpha:
        n += 1
        if n > 20000:
            break
    return n


# --------------------------------------------------------------------------
# Decoder
# --------------------------------------------------------------------------

class SyntheticDecoder:
    """Answers a probe correctly with high probability when its evidence is in
    the window, low probability otherwise. Seeded per instance so runs are
    reproducible and instance-to-instance variation is real, not an artifact."""

    P_WITH_EVIDENCE = 0.97
    P_WITHOUT = 0.25

    def __init__(self, seed: int):
        self.rng = random.Random(seed)

    def answer(self, probe_id: str, needed: str, window_paths: set[str]) -> bool:
        p = self.P_WITH_EVIDENCE if needed in window_paths else self.P_WITHOUT
        return self.rng.random() < p


# --------------------------------------------------------------------------
# Run
# --------------------------------------------------------------------------

def main() -> None:
    if os.path.exists(ROOT):
        shutil.rmtree(ROOT)
    h = Harness(ROOT)
    h.init()
    oversight.write_probe_contract(h)

    ph = protocol_hash()
    h._write_json(h.p("probes", "task", "protocol.json"), {
        "protocol_hash": ph, "protocol_version": PROTOCOL_VERSION,
        "epsilon": EPSILON, "alpha": ALPHA,
        "n_instances": N_INSTANCES, "confidence": CONFIDENCE,
        "selection_rule": SELECTION_RULE, "probes": TASK_PROBES,
        "ladder": [[k, v] for k, v in LADDER],
        "model_identity": MODEL_IDENTITY,
    })
    print(f"protocol frozen before any instance runs: {ph[:16]}")
    print(f"  protocol v{PROTOCOL_VERSION}  eps={EPSILON}  alpha={ALPHA}  "
          f"n={N_INSTANCES}  conf={CONFIDENCE}")
    print(f"  {len(TASK_PROBES)} probes -> D granularity "
          f"{1/len(TASK_PROBES):.3f}, commensurate with eps={EPSILON}")

    need = n_required(ALPHA)
    print(f"  zero-failure certification of alpha={ALPHA} needs n>={need}"
          f"  -> {'OK' if N_INSTANCES >= need else 'UNDERPOWERED'}")
    need01 = n_required(0.01)
    print(f"  (for alpha=0.01 it would need n>={need01})")
    print("  NOTE: that is the zero-failure bound. Sizing a run from it "
          "assumes the true rate is 0.")

    # Seed the over-complete evidence world.
    h.put_grant("seeder", ["*"], ["*"])
    v = h.current_version()
    h.materialize_window("seeder", v)
    d = Delta("seeder", v, [Op("WRITE", path=p, content=f"content of {p} " * 40)
                            for p in EVIDENCE])
    h.propose(d)
    h.merge_commit([d])
    base_v = h.current_version()

    rows = []
    for wid, paths in LADDER:
        spec = f"reviewer_{wid}"
        h.put_grant(spec, list(paths), ["out/*"])
        rate = sum(len(h.read_artifact(base_v, p).encode()) for p in paths)

        failures = 0
        for j in range(N_INSTANCES):
            inst = h.instantiate(spec, model_identity=MODEL_IDENTITY)
            wm = h.materialize_window(spec, base_v)
            wpaths = set(wm["artifact_ids"])
            dec = SyntheticDecoder(seed=int(inst[:8], 16) + j)
            wrong = sum(0 if dec.answer(pid, need_, wpaths) else 1
                        for pid, need_ in TASK_PROBES)
            dist = wrong / len(TASK_PROBES)
            if dist > EPSILON:
                failures += 1
            h._append_jsonl(h.p("lineage", "exp002_observations.jsonl"), {
                "experiment_run_id": ph,
                "protocol_hash": ph,
                "model_identity": MODEL_IDENTITY,
                "locus_spec_id": spec,
                "instance_id": inst,
                "world_version": base_v,
                "window_id": wid,
                "window_hash": wm["window_hash"],
                "window_rate_bytes": rate,
                "probe_set_hash": _sha(_canon(TASK_PROBES)),
                "task_distortion": dist,
            })
            h.terminate(inst)

        rate_fail = failures / N_INSTANCES
        ub = clopper_pearson_upper(failures, N_INSTANCES)
        rows.append((wid, len(paths), rate, failures, rate_fail, ub))

    print(f"\n{'win':<4}{'arts':>5}{'rate B':>9}{'fails':>7}"
          f"{'P̂(D>eps)':>11}{'UB95':>8}  meets alpha")
    for wid, k, rate, f, pf, ub in rows:
        ok = "yes" if ub <= ALPHA else "no"
        print(f"{wid:<4}{k:>5}{rate:>9}{f:>7}{pf:>11.3f}{ub:>8.3f}  {ok}")

    # Selection rule, fixed in advance: smallest rate meeting the bound.
    # Power diagnosis: was n large enough to decide the question asked?
    print()
    for wid, k, rate, f, pf, ub in rows:
        if ub > ALPHA and pf < ALPHA:
            need = n_required_at_rate(pf, ALPHA)
            msg = (f"n>={need}" if need > 0
                   else f"not certifiable -- point estimate {pf:.3f} >= alpha")
            print(f"  {wid}: point estimate {pf:.3f} < alpha but bound "
                  f"{ub:.3f} > alpha -- UNDERPOWERED, would need {msg}")

    ok_rows = [r for r in rows if r[5] <= ALPHA]
    print()
    if ok_rows:
        best = min(ok_rows, key=lambda r: r[2])
        print(f"selected: {best[0]} at {best[2]} bytes "
              f"(UB95 P(D>{EPSILON}) = {best[5]:.3f} <= {ALPHA})")
        # Candidates whose intervals overlap the selection are not
        # distinguishable at this n; reporting only the winner would overstate
        # what the run established.
        lo_best = clopper_pearson_lower(best[3], N_INSTANCES)
        tied = [r for r in rows if r is not best
                and clopper_pearson_upper(r[3], N_INSTANCES) >= lo_best
                and clopper_pearson_lower(r[3], N_INSTANCES) <= best[5]]
        if tied:
            print(f"  statistically tied at n={N_INSTANCES}: "
                  + ", ".join(f"{r[0]}({r[2]}B)" for r in tied))
            print("  the run does not distinguish these; more instances or a "
                  "larger effect are needed to separate them")
    else:
        print("no window met the reliability criterion")

    print("\nreliability frontier is scoped to (M_v, R_spec) = "
          f"({MODEL_IDENTITY['name']}/{MODEL_IDENTITY['version_or_snapshot']}, "
          "reviewer). A model change is a different channel, not more samples.")
    print("These numbers exercise the machinery. They are not a finding about "
          "any model.")


if __name__ == "__main__":
    main()
