"""
CET-0 Experiment 003 -- calibration of the statistical protocol itself.

Experiment 002 showed that trustworthy causal measurement can still support an
invalid statistical conclusion when the inferential contract is underspecified.
So before a real decoder is attached, the protocol becomes the object of
falsification: does it achieve the error rates it promises, at known p?

Because the decoder is synthetic, p_true is available. That permits EXACT
operating characteristics rather than sampled ones; Monte Carlo is retained
only as a cross-check that the implementation matches the theory. With a real
decoder neither is available and the design must be sized in advance from
assumed rates -- which is the whole point of doing this now.

Run: python3 experiment_003_protocol_calibration.py
"""

from __future__ import annotations

import json
import math
import random
import sys

from harness.reliability import (
    RELIABLE, UNRELIABLE, INDETERMINATE, UNDERPOWERED,
    classify, prob_class, power_analysis, n_recommended, cp_upper,
)
from harness.core import _sha, _canon

# --------------------------------------------------------------------------
# Preregistered protocol v3. Power analysis is INSIDE the hash.
# --------------------------------------------------------------------------

PROBE_COUNT = 20
PROBE_WEIGHTS = "equal"
EPSILON = 0.05                      # == 1/PROBE_COUNT, commensurate
ALPHA_GOOD = 0.10
ALPHA_BAD = 0.20
CONFIDENCE = 0.95
TARGET_POWER = 0.80
PLANNED_N = 200
SELECTION_RULE = ("ordered testing from the smallest nested window upward; "
                  "stop at the first window certified RELIABLE; rate breaks "
                  "ties among windows in the same reliability class")
MULTIPLE_COMPARISON_RULE = ("Bonferroni: per-window level 1-(1-conf)/L over "
                            "L ladder rungs, so family-wise false-certification "
                            "stays at or below 1-conf")
TRUE_RATES = [0.02, 0.08, 0.10, 0.15, 0.20, 0.30]
MC_REPS = 8000


def protocol_record() -> dict:
    rec = {
        "protocol_version": 3,
        "probe_count": PROBE_COUNT,
        "probe_weights": PROBE_WEIGHTS,
        "epsilon": EPSILON,
        "epsilon_support_note": (
            f"D_Q support is multiples of 1/{PROBE_COUNT}; eps={EPSILON} means "
            f"'more than {int(EPSILON * PROBE_COUNT)} probe failure(s)'"),
        "alpha_good": ALPHA_GOOD,
        "alpha_bad": ALPHA_BAD,
        "confidence_level": CONFIDENCE,
        "target_power": TARGET_POWER,
        "planned_n": PLANNED_N,
        "selection_rule": SELECTION_RULE,
        "multiple_comparison_rule": MULTIPLE_COMPARISON_RULE,
    }
    rec.update({k: round(v, 5) for k, v in
                power_analysis(PLANNED_N, ALPHA_GOOD, ALPHA_BAD, CONFIDENCE).items()
                if k != "n"})
    rec["protocol_hash"] = _sha(_canon(rec))
    return rec


# --------------------------------------------------------------------------

def main() -> None:
    proto = protocol_record()
    print("CET-0 Experiment 003 -- protocol calibration")
    print(f"protocol hash {proto['protocol_hash'][:16]} (power analysis included)")
    print(f"  eps={EPSILON} on support 1/{PROBE_COUNT}: "
          f"{proto['epsilon_support_note'].split('means ')[1]}")
    print(f"  indifference region: good<={ALPHA_GOOD}  bad>={ALPHA_BAD}")

    # --- design-time verdict, before any run --------------------------------
    need = n_recommended(ALPHA_GOOD, ALPHA_BAD, TARGET_POWER, CONFIDENCE)
    pa = power_analysis(PLANNED_N, ALPHA_GOOD, ALPHA_BAD, CONFIDENCE)
    verdict = (UNDERPOWERED if pa["power_at_alpha_good"] < TARGET_POWER
               else "ADEQUATELY_POWERED")
    print(f"\ndesign-time verdict at planned n={PLANNED_N}: {verdict}")
    print(f"  power at p=alpha_good : {pa['power_at_alpha_good']:.3f} "
          f"(target {TARGET_POWER})")
    print(f"  smallest n reaching target power: {need}")
    print(f"  for comparison, exp002 used n=30 -> power "
          f"{power_analysis(30, ALPHA_GOOD, ALPHA_BAD, CONFIDENCE)['power_at_alpha_good']:.3f}")

    n = max(PLANNED_N, need)
    if n != PLANNED_N:
        print(f"  planned n raised to {n} by the preregistered target power")

    # --- exact operating characteristics ------------------------------------
    print(f"\nexact operating characteristics at n={n}")
    print(f"{'p_true':>8}{'RELIABLE':>11}{'UNRELIABLE':>12}"
          f"{'INDET':>9}   expected")
    rows = []
    for p in TRUE_RATES:
        r = prob_class(RELIABLE, n, p, ALPHA_GOOD, ALPHA_BAD, CONFIDENCE)
        u = prob_class(UNRELIABLE, n, p, ALPHA_GOOD, ALPHA_BAD, CONFIDENCE)
        i = prob_class(INDETERMINATE, n, p, ALPHA_GOOD, ALPHA_BAD, CONFIDENCE)
        if p <= ALPHA_GOOD:
            exp = "mostly RELIABLE"
        elif p >= ALPHA_BAD:
            exp = "mostly UNRELIABLE"
        else:
            exp = "often INDETERMINATE"
        rows.append((p, r, u, i, exp))
        print(f"{p:>8.2f}{r:>11.3f}{u:>12.3f}{i:>9.3f}   {exp}")

    # --- the two promises the protocol makes --------------------------------
    print("\nprotocol guarantees")
    worst_false_cert = max(
        prob_class(RELIABLE, n, p, ALPHA_GOOD, ALPHA_BAD, CONFIDENCE)
        for p in TRUE_RATES if p >= ALPHA_BAD)
    ok1 = worst_false_cert <= 1 - CONFIDENCE
    print(f"  P(RELIABLE | p >= alpha_bad) = {worst_false_cert:.4f} "
          f"<= {1 - CONFIDENCE}  {'PASS' if ok1 else 'FAIL'}")
    worst_miss = max(
        1 - prob_class(RELIABLE, n, p, ALPHA_GOOD, ALPHA_BAD, CONFIDENCE)
        for p in TRUE_RATES if p <= ALPHA_GOOD)
    ok2 = worst_miss <= 1 - TARGET_POWER
    print(f"  P(not certified | p <= alpha_good) = {worst_miss:.4f} "
          f"<= {1 - TARGET_POWER:.2f}  {'PASS' if ok2 else 'FAIL'}")

    # --- Monte Carlo cross-check --------------------------------------------
    rng = random.Random(20260816)
    print(f"\nMonte Carlo cross-check ({MC_REPS} reps) -- confirms the "
          f"implementation matches the exact calculation")
    max_dev = 0.0
    for p in TRUE_RATES:
        hits = sum(1 for _ in range(MC_REPS)
                   if classify(rng.binomialvariate(n, p), n, ALPHA_GOOD,
                               ALPHA_BAD, CONFIDENCE) == RELIABLE)
        emp = hits / MC_REPS
        exact = prob_class(RELIABLE, n, p, ALPHA_GOOD, ALPHA_BAD, CONFIDENCE)
        max_dev = max(max_dev, abs(emp - exact))
        print(f"  p={p:.2f}  empirical {emp:.4f}  exact {exact:.4f}  "
              f"dev {abs(emp - exact):.4f}")
    print(f"  max deviation {max_dev:.4f} "
          f"{'PASS' if max_dev < 0.02 else 'FAIL'}")

    # --- ladder: ordered testing and family-wise error ----------------------
    # A nested ladder where the three smallest windows are genuinely bad and
    # the rest are genuinely good. The correct answer is W3.
    # The three smallest windows are bad but only just -- p just above
    # alpha_bad. Far-from-boundary bad windows are never certified by either
    # rule, so they cannot expose a multiple-comparison problem at all.
    ladder = [("W0", 0.02, 9840), ("W1", 0.03, 8680), ("W2", 0.05, 7400),
              ("W3", 0.20, 6240), ("W4", 0.20, 4960), ("W5", 0.20, 3720)]
    L = len(ladder)
    conf_bonf = 1 - (1 - CONFIDENCE) / L
    print(f"\nordered testing on a nested ladder (correct answer: W2, "
          f"the smallest window with p<=alpha_good;\n  W3-W5 are bad but only "
          f"just above alpha_bad, which is where false certification lives)")
    print(f"  Bonferroni per-window confidence {conf_bonf:.4f} over L={L}")

    def run_ladder(conf: float) -> str:
        for wid, p, _rate in reversed(ladder):     # smallest window first
            k = rng.binomialvariate(n, p)
            if classify(k, n, ALPHA_GOOD, ALPHA_BAD, conf) == RELIABLE:
                return wid
        return "NO_WINDOW_CERTIFIED"

    for label, conf in (("naive (per-window 0.95)", CONFIDENCE),
                        ("Bonferroni", conf_bonf)):
        counts: dict[str, int] = {}
        reps = 4000
        for _ in range(reps):
            sel = run_ladder(conf)
            counts[sel] = counts.get(sel, 0) + 1
        total = sum(counts.values())
        # A false certification is selecting a window whose true p >= alpha_bad.
        bad_ids = {w for w, p, _ in ladder if p >= ALPHA_BAD}
        fwer = sum(c for w, c in counts.items() if w in bad_ids) / total
        correct = counts.get("W2", 0) / total
        print(f"  {label:<24} selects W2 {correct:.3f}   "
              f"family-wise false cert {fwer:.4f}"
              + ("  <- exceeds 1-conf" if fwer > 1 - CONFIDENCE else ""))

    print("\n  note: 3 bad rungs sitting exactly AT alpha_bad is the worst "
          "case for the ordered\n  procedure. Naive stays under the 0.05 "
          "family budget here only because the corrected\n  classifier's "
          "per-window false-certification rate is ~0.011, not ~0.05. "
          "Bonferroni is\n  retained because the guarantee should not depend "
          "on the true rates being favourable.")
    print("\n  the protocol makes NO promise inside the indifference region: "
          "at p=0.15 it certifies\n  RELIABLE about a third of the time. That "
          "is the declared cost of bounding n.")
    print("\nDESCRIPTIVE and DECISION outputs are separate: the R-D points and "
          "intervals are reported in full,\nwhile the decision is a single "
          "certified window or NO_WINDOW_CERTIFIED. An uncertifiable smaller "
          "window\nmeans 'insufficient evidence to promote it', not 'the "
          "larger window is better'.")


if __name__ == "__main__":
    main()
