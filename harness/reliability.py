"""
Reliability classification for CET rate-distortion experiments.

Separates three things Experiment 002 conflated:

    D_Q          probe-level distortion, support {0, 1/k, ..., 1}
    p_i          run-level violation probability P(D_ij > eps)
    evidence     finite-sample knowledge about p_i

The decision is about p_i, not about the observed rate. An indifference region
between alpha_good and alpha_bad is declared so sample size does not explode as
the true rate approaches the boundary -- a protocol that must decide exactly at
alpha is unbounded in n by construction.

Return values:
    RELIABLE       evidence rules out p >= alpha_bad
    UNRELIABLE     evidence rules out p <= alpha_good
    INDETERMINATE  neither; the run does not decide
    UNDERPOWERED   design-time verdict, knowable before execution
"""

from __future__ import annotations

import math

RELIABLE = "RELIABLE"
UNRELIABLE = "UNRELIABLE"
INDETERMINATE = "INDETERMINATE"
UNDERPOWERED = "UNDERPOWERED"


def cp_upper(k: int, n: int, conf: float = 0.95) -> float:
    """One-sided upper Clopper-Pearson bound on a binomial rate."""
    if k >= n:
        return 1.0
    lo, hi, target = 0.0, 1.0, 1.0 - conf
    for _ in range(160):
        mid = (lo + hi) / 2
        cdf = sum(math.comb(n, i) * mid**i * (1 - mid)**(n - i)
                  for i in range(k + 1))
        if cdf > target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def cp_lower(k: int, n: int, conf: float = 0.95) -> float:
    if k <= 0:
        return 0.0
    lo, hi, target = 0.0, 1.0, 1.0 - conf
    for _ in range(160):
        mid = (lo + hi) / 2
        sf = sum(math.comb(n, i) * mid**i * (1 - mid)**(n - i)
                 for i in range(k, n + 1))
        if sf > target:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def _binom_pmf(k: int, n: int, p: float) -> float:
    if p <= 0:
        return 1.0 if k == 0 else 0.0
    if p >= 1:
        return 1.0 if k == n else 0.0
    return math.comb(n, k) * p**k * (1 - p)**(n - k)


def _binom_cdf(k: int, n: int, p: float) -> float:
    return sum(_binom_pmf(i, n, p) for i in range(0, k + 1))


def _binom_sf(k: int, n: int, p: float) -> float:
    """P(X >= k)."""
    return sum(_binom_pmf(i, n, p) for i in range(k, n + 1))


def classify(k: int, n: int, alpha_good: float, alpha_bad: float,
             conf: float = 0.95) -> str:
    """Classify one window from k violations in n fresh-instance runs.

    No bisection is needed: cp_upper(k,n) <= alpha_bad holds exactly when
    P(X <= k | p=alpha_bad) <= 1-conf, and cp_lower(k,n) >= alpha_good holds
    exactly when P(X >= k | p=alpha_good) <= 1-conf. Each verdict is one
    binomial tail, which is what makes exact operating characteristics
    tractable at realistic n."""
    return classify_from_table(
        k, _table_cached(n, alpha_good, alpha_bad, conf))


_TABLES: dict = {}


def _table_cached(n, alpha_good, alpha_bad, conf) -> dict:
    key = (n, alpha_good, alpha_bad, conf)
    if key not in _TABLES:
        _TABLES[key] = cutoff_table(n, alpha_good, alpha_bad, conf)
    return _TABLES[key]


def cutoff_table(n: int, alpha_good: float, alpha_bad: float,
                 conf: float = 0.95) -> dict:
    """Reduce the whole protocol to two integer critical counts.

    The certification condition is P(X<=k | p=alpha_bad) <= 1-conf, monotone in
    k, so it is equivalent to k <= reliable_max_failures. Likewise the
    rejection condition is k >= unreliable_min_failures. Once these are
    computed the evaluator needs no statistics at all -- it applies a
    preregistered deterministic table whose operating characteristics were
    calculated before execution. That puts the decision on the mechanical side
    of sec.31 rather than leaving a numerical procedure in the trusted path.

    The two regions may OVERLAP at large n. Overlap is not a contradiction: it
    locates p strictly inside the indifference region, and INDETERMINATE
    dominates there.
    """
    tail = 1.0 - conf
    rel_max = -1
    for k in range(n + 1):
        if _binom_cdf(k, n, alpha_bad) <= tail:
            rel_max = k
        else:
            break
    unrel_min = n + 1
    for k in range(n, -1, -1):
        if _binom_sf(k, n, alpha_good) <= tail:
            unrel_min = k
        else:
            break
    return {
        "n": n, "alpha_good": alpha_good, "alpha_bad": alpha_bad,
        "confidence": conf,
        "reliable_max_failures": rel_max,
        "unreliable_min_failures": unrel_min,
        "regions_overlap": unrel_min <= rel_max,
        "overlap_counts": list(range(unrel_min, rel_max + 1))
                          if unrel_min <= rel_max else [],
    }


def classify_from_table(k: int, table: dict) -> str:
    """The entire runtime classifier. No statistics, no floating comparison
    against a recomputed interval -- one integer test per boundary, with
    INDETERMINATE checked first so evaluation precedence cannot collapse a
    deliberately unclassified region into a certification."""
    rel = k <= table["reliable_max_failures"]
    unrel = k >= table["unreliable_min_failures"]
    if rel and unrel:
        return INDETERMINATE          # evidence locates p inside the region
    if rel:
        return RELIABLE
    if unrel:
        return UNRELIABLE
    return INDETERMINATE              # evidence excludes neither side


def reliable_region(n: int, alpha_good: float, alpha_bad: float,
                    conf: float = 0.95) -> set[int]:
    """The set of k values that would certify RELIABLE. Precomputing this makes
    the operating characteristics exactly computable."""
    return {k for k in range(n + 1)
            if classify(k, n, alpha_good, alpha_bad, conf) == RELIABLE}


def prob_class(cls: str, n: int, p_true: float, alpha_good: float,
               alpha_bad: float, conf: float = 0.95) -> float:
    """EXACT probability of a classification at a known true rate. Available
    only because the decoder is synthetic; with a real decoder p_true is
    unknown and this must be replaced by simulation under assumed rates."""
    return sum(_binom_pmf(k, n, p_true) for k in range(n + 1)
               if classify(k, n, alpha_good, alpha_bad, conf) == cls)


def power_analysis(n: int, alpha_good: float, alpha_bad: float,
                   conf: float = 0.95) -> dict:
    """Belongs in the protocol hash, not in the post-hoc discussion."""
    return {
        "n": n,
        "power_at_alpha_good": prob_class(RELIABLE, n, alpha_good,
                                          alpha_good, alpha_bad, conf),
        "false_cert_at_alpha_bad": prob_class(RELIABLE, n, alpha_bad,
                                              alpha_good, alpha_bad, conf),
        "indeterminate_at_midpoint": prob_class(
            INDETERMINATE, n, (alpha_good + alpha_bad) / 2,
            alpha_good, alpha_bad, conf),
    }


def n_recommended(alpha_good: float, alpha_bad: float, target_power: float,
                  conf: float = 0.95, n_max: int = 4000) -> int:
    """Smallest n achieving target power at p = alpha_good."""
    n = 10
    while n <= n_max:
        if prob_class(RELIABLE, n, alpha_good, alpha_good, alpha_bad,
                      conf) >= target_power:
            return n
        n += 10
    return -1
