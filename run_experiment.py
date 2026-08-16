"""
CET-0 Experiment 001 -- parallel loci, engineered conflict, oversight audit.

    two loci -> same S^v -> different W_i^v -> parallel work -> private staging
    -> conflicting outputs -> merge gate -> atomic S^(v+1) -> audit trace

The experiment record carries full decoder/model/harness provenance from day
one, because distortion measurements are relative to the reconstructing model
and harness, not properties of the window alone. No distortion is measured in
this slice -- no model is in the loop yet -- but the record shape is fixed now
so later measurements are never stored bare.
"""

from __future__ import annotations

import json
import os
import platform
import sys

from harness.core import Harness, Delta, Op, EFFECT_OPEN
from harness import probes

ROOT = sys.argv[1] if len(sys.argv) > 1 else "./cet0_store"


def experiment_record(h: Harness, **extra) -> dict:
    return {
        "experiment_id": "CET0-001",
        # Decoder/model provenance. Empty here -- no model in the loop yet --
        # but the keys exist so a bare distortion=0.08 can never be recorded.
        "model_provider": None,
        "model_name": None,
        "model_version_or_snapshot": None,
        "tokenizer_if_used": None,
        # Harness / world provenance.
        "harness_version": h.HARNESS_VERSION,
        "python": platform.python_version(),
        "world_version": h.current_version(),
        "probe_set_hash": probes.probe_set_hash(),
        "lambda_hash": h.manifest(h.current_version()).get("lambda_hash"),
        # Compression provenance, fixed before the information layer lands.
        # gzip is excluded: its 32KB match window makes NCD collapse to ~1 on
        # artifacts larger than the window regardless of similarity.
        "compressor": "xz/LZMA (declared, unused in this slice)",
        "compressor_version": None,
        **extra,
    }


def main() -> None:
    if os.path.exists(ROOT):
        import shutil
        shutil.rmtree(ROOT)
    h = Harness(ROOT)
    h.init()
    ph = probes.write_probe_contract(h)
    print(f"probe contract committed and hashed before any locus runs: {ph[:16]}")

    # Seed a shared world through the ordinary admissibility path.
    h.put_grant("seeder", ["*"], ["*"])
    v = h.current_version()
    h.materialize_window("seeder", v)
    d0 = Delta("seeder", v, [
        Op("WRITE", path="protected/spec.txt", content="the specification",
           review_deadline=6),
        Op("WRITE", path="work/notes.txt", content="shared notes"),
    ])
    h.propose(d0)
    h.merge_commit([d0])
    print(f"seeded world -> v{h.current_version():06d}")

    # Two loci, same committed world version, deliberately different windows.
    h.put_grant("o1", ["work/*", "protected/*"], ["work/*"])
    h.put_grant("o2", ["work/*"], ["work/*"])
    v = h.current_version()
    w1 = h.materialize_window("o1", v)
    w2 = h.materialize_window("o2", v)
    print(f"\nW_1^v sealed: {w1['artifact_ids']}  hash={w1['window_hash'][:12]}")
    print(f"W_2^v sealed: {w2['artifact_ids']}  hash={w2['window_hash'][:12]}")
    print("  (different sealed projections of the same S^v -- sec.9)")

    # Parallel work into private staging.
    d1 = Delta("o1", v, [Op("READ", path="protected/spec.txt"),
                         Op("WRITE", path="work/result.txt", content="from o1")])
    d2 = Delta("o2", v, [Op("WRITE", path="work/result.txt", content="from o2")])
    r1, r2 = h.propose(d1), h.propose(d2)
    print(f"\nlocal gate o1: {'ADMIT' if r1.admitted else r1.code}")
    print(f"local gate o2: {'ADMIT' if r2.admitted else r2.code}")

    # o2 attempts to observe o1's staging.
    peek = h.peek_staging("o2", "o1")
    print(f"o2 peek at o1 staging: {peek.code}")

    # Engineered conflict: both locally valid, jointly inadmissible.
    m = h.merge_commit([d1, d2])
    print(f"merge gate: {'ADMIT' if m.admitted else m.code} -- {m.detail}")
    print(f"world still at v{h.current_version():06d}")

    # Serialise.
    m1 = h.merge_commit([d1])
    print(f"o1 alone: {'ADMIT' if m1.admitted else m1.code} -> v{h.current_version():06d}")

    # An EFFECT_OPEN attempt into the protected region.
    v = h.current_version()
    h.materialize_window("o1", v)
    d3 = Delta("o1", v, [Op("EXEC", path="protected/x", command="sh -c 'rm -rf /'",
                            effect_class=EFFECT_OPEN)])
    r3 = h.propose(d3)
    print(f"EFFECT_OPEN into protected: {r3.code}")

    print("\n" + "=" * 66)
    print(probes.report(h))

    rec = experiment_record(h, final_world_version=h.current_version())
    h._write_json(h.p("lineage", "experiment_001.json"), rec)
    print("\nexperiment record ->", h.p("lineage", "experiment_001.json"))


if __name__ == "__main__":
    main()
