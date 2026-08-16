"""
CET-0 adapter for CET_REAL_TASKS_v1.

Loads a real-task pack into the frozen substrate: verifies the pack manifest,
materializes each ladder rung as a sealed CET-0 window, and refuses to run a
measurement that would be void.

WHY THIS FILE ENFORCES ORACLE EXCLUSION MECHANICALLY

EXECUTION_GUIDE step 3 says "keep oracle/ inaccessible to the decoder". As
written that is a convention, not a predicate. Nothing in the pack prevents an
oracle path entering a window, and nothing records whether the decoder saw one.
By the Distinction Preservation Principle a declared distinction that the
implementation does not preserve is not real -- and oracle contamination is the
worst case of it, because a contaminated decoder produces confident, fluent,
correct-looking answers and leaves no trace in the output.

So E_ORACLE_LEAK is a hard predicate here, and every run carries an explicit
decoder contamination attestation that must be supplied, not defaulted.

Run: python3 taskpack.py /path/to/CET_REAL_TASKS_v1
"""

from __future__ import annotations

import hashlib
import json
import os
import sys

E_ORACLE_LEAK = "E_ORACLE_LEAK"
E_PROBE_COUNT_MISMATCH = "E_PROBE_COUNT_MISMATCH"
E_PROBE_NOT_GRADABLE = "E_PROBE_NOT_GRADABLE"
E_DECODER_CONTAMINATED = "E_DECODER_CONTAMINATED"
E_PACK_HASH_MISMATCH = "E_PACK_HASH_MISMATCH"

# Any path segment matching these is evaluator-only and must never reach a
# window. Substring matching, not exact paths: a pack may add new oracle files.
ORACLE_MARKERS = ("oracle/", "ground_truth", "hidden_cases", "/oracle")

# From the frozen substrate (experiment_004_frontier.py). Not editable here:
# changing either produces a new protocol_hash and a new experiment family.
FROZEN_PROBE_COUNT = 20
FROZEN_EPSILON = 0.05


def sha(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def is_oracle(path: str) -> bool:
    p = path.replace("\\", "/")
    return any(m in p for m in ORACLE_MARKERS)


def verify_pack(root: str) -> tuple[bool, list, str]:
    man = json.load(open(os.path.join(root, "manifest.json")))
    bad = []
    entries = {}
    for t in man["tasks"]:
        for f in t["files"]:
            rel = os.path.join(t["task_id"], f["path"])
            full = os.path.join(root, rel)
            if not os.path.exists(full):
                bad.append((rel, "MISSING"))
                continue
            h = sha(full)
            entries[rel] = h
            if h != f["sha256"]:
                bad.append((rel, E_PACK_HASH_MISMATCH))
    pack_hash = hashlib.sha256(
        json.dumps(entries, sort_keys=True).encode()).hexdigest()
    return (not bad), bad, pack_hash


def check_ladder(root: str, task_id: str) -> dict:
    tdir = os.path.join(root, task_id)
    wdir = os.path.join(tdir, "windows")
    ladders = {}
    for fn in sorted(os.listdir(wdir)):
        ladders[fn] = json.load(open(os.path.join(wdir, fn)))

    leaks, rungs = [], {}
    for fn, lad in ladders.items():
        for rung, paths in lad.items():
            if not isinstance(paths, list):
                rungs[f"{fn}:{rung}"] = None        # task 5 witness ladder
                continue
            bad = [p for p in paths if is_oracle(p)]
            if bad:
                leaks.append((fn, rung, bad))
            missing = [p for p in paths
                       if not os.path.exists(os.path.join(tdir, p))]
            rate = sum(os.path.getsize(os.path.join(tdir, p))
                       for p in paths if os.path.exists(os.path.join(tdir, p)))
            rungs[f"{fn}:{rung}"] = {"n_files": len(paths), "rate_bytes": rate,
                                     "missing": missing}
    return {"ladders": ladders, "leaks": leaks, "rungs": rungs}


def check_probes(root: str, task_id: str) -> dict:
    p = json.load(open(os.path.join(root, task_id, "probes", "probes.json")))
    probes = p["probes"]
    executable = [q for q in probes if q.get("type") == "executable"]
    structured, free_text = [], []
    for q in probes:
        if q.get("type") == "executable":
            continue
        exp = q.get("expected")
        # Mechanically gradable: bool, number, or list of short tokens.
        if isinstance(exp, (bool, int, float)) or (
                isinstance(exp, list) and all(isinstance(x, str) for x in exp)):
            structured.append(q["id"])
        elif isinstance(exp, str) and len(exp.split()) <= 2:
            structured.append(q["id"])
        else:
            free_text.append(q["id"])
    return {
        "probe_set_id": p.get("probe_set_id"),
        "count": len(probes),
        "executable": [q["id"] for q in executable],
        "mechanically_gradable": structured,
        "requires_judge": free_text,
        "probe_set_hash": hashlib.sha256(
            json.dumps(probes, sort_keys=True).encode()).hexdigest(),
    }


def readiness(root: str) -> dict:
    ok, bad, pack_hash = verify_pack(root)
    man = json.load(open(os.path.join(root, "manifest.json")))
    report = {"pack": man["pack"], "pack_hash": pack_hash,
              "manifest_verified": ok, "manifest_problems": bad,
              "tasks": {}, "blockers": []}
    if not ok:
        report["blockers"].append(E_PACK_HASH_MISMATCH)

    for t in man["tasks"]:
        tid = t["task_id"]
        lad = check_ladder(root, tid)
        pr = check_probes(root, tid)
        entry = {"ladder": lad["rungs"], "oracle_leaks": lad["leaks"],
                 "probes": pr, "blockers": []}

        if lad["leaks"]:
            entry["blockers"].append(E_ORACLE_LEAK)
        if pr["count"] != FROZEN_PROBE_COUNT:
            entry["blockers"].append(
                f"{E_PROBE_COUNT_MISMATCH}: k={pr['count']}, frozen protocol "
                f"assumes k={FROZEN_PROBE_COUNT}; eps={FROZEN_EPSILON} on "
                f"support 1/{pr['count']} means "
                f"'{'zero' if FROZEN_EPSILON * pr['count'] < 1 else int(FROZEN_EPSILON * pr['count'])} "
                f"probe failures allowed'")
        if pr["requires_judge"]:
            entry["blockers"].append(
                f"{E_PROBE_NOT_GRADABLE}: {len(pr['requires_judge'])} of "
                f"{pr['count']} probes need a judge")
        report["tasks"][tid] = entry
        report["blockers"].extend(f"{tid}: {b}" for b in entry["blockers"])
    return report


def gate_decoder(contamination_attestation: dict | None) -> tuple[bool, str]:
    """A decoder must attest that it has not observed evaluator-only material.
    This cannot default to clean: contamination is invisible in the output, so
    absence of an attestation is treated as contamination."""
    if not contamination_attestation:
        return False, (f"{E_DECODER_CONTAMINATED}: no attestation supplied. "
                       "Contamination leaves no trace in decoder output, so "
                       "an unattested decoder is treated as contaminated.")
    if contamination_attestation.get("observed_oracle_paths"):
        return False, (f"{E_DECODER_CONTAMINATED}: attested exposure to "
                       f"{contamination_attestation['observed_oracle_paths']}")
    required = ("provider", "name", "version_or_snapshot", "tokenizer_if_used")
    missing = [k for k in required
               if k not in contamination_attestation.get("identity", {})]
    if missing:
        return False, f"decoder identity incomplete: missing {missing}"
    return True, "decoder attested clean"


def main() -> int:
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    r = readiness(root)
    print(f"pack {r['pack']}  hash {r['pack_hash'][:16]}")
    print(f"manifest verified: {r['manifest_verified']}"
          + (f"  problems {r['manifest_problems']}"
             if r["manifest_problems"] else ""))

    for tid, e in r["tasks"].items():
        pr = e["probes"]
        print(f"\n{tid}")
        print(f"  probes k={pr['count']}  gradable={len(pr['mechanically_gradable'])}"
              f"  executable={len(pr['executable'])}"
              f"  needs-judge={len(pr['requires_judge'])}")
        rungs = {k: v for k, v in e["ladder"].items() if v}
        if rungs:
            rates = ", ".join(f"{k.split(':')[1]}={v['rate_bytes']}B"
                              for k, v in sorted(rungs.items()))
            print(f"  ladder  {rates}")
        print(f"  oracle leaks in declared windows: "
              f"{e['oracle_leaks'] if e['oracle_leaks'] else 'none'}")
        for b in e["blockers"]:
            print(f"  BLOCKER {b}")

    ok, msg = gate_decoder(None)
    print(f"\ndecoder gate: {msg}")

    print(f"\n{len(r['blockers'])} blocker(s) before a valid measurement:")
    for b in r["blockers"]:
        print(f"  - {b}")
    return 1 if r["blockers"] else 0


if __name__ == "__main__":
    sys.exit(main())
