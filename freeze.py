"""
CET-0 Experimental Substrate v1 -- milestone freeze.

A milestone that exists only as a claim has no identity. This writes a
content-hashed manifest of every source file, so "frozen at v1" is checkable
rather than asserted, and any subsequent edit is detectable by the same
mechanism the harness uses for everything else.

    python3 freeze.py            verify against MILESTONE.json
    python3 freeze.py --write    create or replace MILESTONE.json

CHANGE CONTROL. Until Experiment 004 has been run against a real decoder, the
only permitted variable is the decoder adapter. No changes to eps, alpha_good,
alpha_bad, n, probe set, ladder, rung ordering, cutoff table, selection rule or
family-wise rule. Any such change produces a new protocol_hash and starts a new
experiment family; it does not extend this one.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys

MILESTONE = "CET-0 Experimental Substrate v1.1"
SUPERSEDES = {
    "v1": "e260cffb4a83fb133c290591f09c6ad3725052c6eaf0585d8f8726df45cacea9",
}
CHANGE_FROM_V1 = (
    "certificate now carries substrate_hash, completing the provenance chain "
    "substrate -> decoder -> run -> descriptive ladder -> decision "
    "certificate. No preregistered parameter changed; the decision path is "
    "unchanged. Made before any real measurement existed, so no measurement "
    "is invalidated."
)

FILES = [
    "harness/__init__.py", "harness/core.py", "harness/probes.py",
    "harness/reliability.py", "adversarial.py", "audit_topology.py",
    "run_experiment.py", "experiment_002_window_rd.py",
    "experiment_003_protocol_calibration.py", "experiment_004_frontier.py",
    "README.md",
]

MUTABLE_BEFORE_004 = ["the decoder adapter passed to experiment_004.main()"]

EVIDENTIAL_STATE = {
    "established": [
        "the causal architecture preserves the identities and distinctions "
        "required to interpret an experiment (adversarial suite, 46 checks)",
        "the statistical protocol behaves per its declared operating "
        "characteristics under a known synthetic process (experiment 003)",
    ],
    "NOT established": [
        "that real LLM reconstruction exhibits a useful rate-distortion "
        "frontier -- no real decoder has been run",
        "that the identity conjecture holds outside the declared claim set",
        "that precedence errors are generally impossible; the final "
        "classifier has no overlap only under this parameterization, and an "
        "earlier one at conf=0.95 did overlap and hid a bug",
    ],
}


def sha(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def build() -> dict:
    entries = {p: sha(p) for p in FILES if os.path.exists(p)}
    missing = [p for p in FILES if not os.path.exists(p)]
    rec = {
        "milestone": MILESTONE,
        "supersedes": SUPERSEDES,
        "change_from_v1": CHANGE_FROM_V1,
        "files": entries,
        "missing": missing,
        "mutable_before_experiment_004": MUTABLE_BEFORE_004,
        "evidential_state": EVIDENTIAL_STATE,
    }
    rec["substrate_hash"] = hashlib.sha256(
        json.dumps(entries, sort_keys=True).encode()).hexdigest()
    return rec


def main() -> int:
    rec = build()
    if "--write" in sys.argv:
        with open("MILESTONE.json", "w") as f:
            json.dump(rec, f, indent=2, sort_keys=True)
        print(f"{MILESTONE}\nsubstrate_hash {rec['substrate_hash']}")
        print(f"{len(rec['files'])} files frozen")
        return 0

    if not os.path.exists("MILESTONE.json"):
        print("no MILESTONE.json -- run with --write")
        return 1
    with open("MILESTONE.json") as f:
        old = json.load(f)
    drift = [p for p, h in rec["files"].items() if old["files"].get(p) != h]
    added = [p for p in rec["files"] if p not in old["files"]]
    removed = [p for p in old["files"] if p not in rec["files"]]
    print(f"{MILESTONE}")
    print(f"  frozen  {old['substrate_hash'][:16]}")
    print(f"  current {rec['substrate_hash'][:16]}")
    if not (drift or added or removed):
        print("  VERIFIED -- substrate unchanged")
        return 0
    print("  DRIFT DETECTED")
    for p in drift:
        print(f"    modified {p}")
    for p in added:
        print(f"    added    {p}")
    for p in removed:
        print(f"    removed  {p}")
    print("\n  If this touched any preregistered parameter, the result is a new")
    print("  experiment family, not a continuation of this one.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
