"""
Topology-to-object audit.

Mechanizes the Materialized-Edge Principle as a standing check rather than a
one-off review. For every named intermediate node in the CET-0 chain, ask:

    1. Does it exist as a first-class object?
    2. Does it have identity?
    3. Is it versioned or content-addressed?
    4. Can downstream records reference it exactly?
    5. Can ABSENCE of the object be detected?

Any "no" is a candidate shortcut around the topology. Question 5 is the one
that catches the hardest cases: an object can be addressable and still leave a
silent hole when it fails to appear (the dropped-request finding).

Run: python3 audit_topology.py
"""

from __future__ import annotations

NO = "no"
YES = "yes"
IMPLEMENTATION_VERSION = "cet0-0.5.0"
AUDIT_RULE_VERSION = 2   # 7-question rule

# NeedIdentity(x, C), not NeedIdentity(x). Reconstructibility is relative to
# the claims we intend to decide, so a score is meaningful only together with
# the claim set it was computed against. Adding a claim invalidates the score:
#     delta C  =>  re-run the identity audit
DECLARED_CLAIMS = [
    "C-01 which grant snapshot authorized this committed effect",
    "C-02 which merge set was rejected, and was it later promoted",
    "C-03 what exactly did this locus receive, for a given request",
    "C-04 did every request reach exactly one terminal outcome",
    "C-05 which ephemeral Self produced this effect",
    "C-06 what was the status history of this delegated-risk property",
    "C-07 which probe evaluation produced this answer, over which traces",
    "C-08 which witnesses derive from one originating fold",
    "C-09 was the trust root replaced",
    "C-10 which window and model produced this distortion measurement",
]

# node, store, identity field, versioned/content-addressed, referenced by,
# absence detectable how
NODES = [
    ("S^v committed world", "world/committed/vN/manifest.json", "version",
     YES, "base_world_version, commit_world_version",
     "version sequence gap"),
    ("Lambda^v policy", "policy/lambda.json", "lambda_hash",
     YES, "manifest.lambda_hash",
     "absent from world manifest"),
    ("Gamma grant snapshot", "grants/snapshots.jsonl", "grant_snapshot_hash",
     YES, "effect.grant_snapshot_hash, admission.grant_snapshot_hash",
     "Q_H-002 E_GRANT_PROVENANCE_BROKEN"),
    ("W_i^v sealed window", "windows/<locus>/manifest.json", "window_hash",
     YES, "admission.window_hash, delivery.window_hash, fold.window_hash",
     "E_NO_SEALED_WINDOW at propose"),
    ("r_i request", "audit/requests.jsonl", "request_id",
     YES, "outcome.request_id, delivery.request_id, fold.request_ids_consumed",
     "no outcome -> E_REQUEST_UNRESOLVED"),
    ("o_i request outcome", "audit/request_outcomes.jsonl", "request_id",
     YES, "reconciled against requests",
     "countOutcomes(r_i) != 1"),
    ("d_i delivery", "audit/deliveries.jsonl", "request_id",
     YES, "Q_H-004 D_exact",
     "outcome DELIVERED with no delivery record"),
    ("Delta_i staged delta", "staging/<locus>/delta.json", "delta_hash",
     YES, "effect.delta_hash, merge_set members",
     "admission trace without staging file"),
    ("M merge set", "audit/admission.jsonl stage=MERGE", "merge_set_hash",
     YES, "effect.merge_set_hash, Q_H-006",
     "commit with no merge record"),
    ("tau_A admission trace", "audit/admission.jsonl", "admission_record_hash",
     YES, "effect.admission_record_hash",
     "effect referencing an absent record"),
    ("tau_effect effect trace", "audit/effects.jsonl", "effect_id",
     YES, "Q_H-001, Q_H-002, Q_H-008",
     "manifest change with no effect record"),
    ("f_j fold", "lineage/folds.jsonl", "fold_id",
     YES, "witness.fold_id, fold.parent_fold_id",
     "witness with unknown fold_id"),
    ("Omega witness", "lineage/witnesses.jsonl", "witness_hash",
     YES, "grouped by fold_id",
     "fold with no witness"),
    ("Q_H probe set", "probes/oversight/Q_H.json", "probe_set_hash",
     YES, "evaluation.probe_set_hash",
     "evaluation citing an unknown probe set"),
    ("EVAL_Q^j evaluation", "probes/oversight/evaluations.jsonl", "evaluation_id",
     YES, "result_hash, audit_trace_root_hash",
     "probe answers with no evaluation record"),
    ("D^v risk revision", "risk/revisions.jsonl", "risk_revision_id",
     YES, "previous_revision_hash chain, evaluation_id",
     "chain break -> E_RISK_REVISION_BROKEN"),
    ("O_instance ephemeral Self", "lineage/instances.jsonl", "instance_id",
     YES, "effect.instance_id, admission.instance_id, parent_instance_id",
     "effect naming an unknown instance"),
    ("L_spec locus specification", "grants/<spec>.json", "locus_spec_id",
     YES, "instance.locus_spec_id",
     "instance citing an unknown spec"),
    ("trust root state", "policy/trust_root.vN.json", "root_hash",
     YES, "previous_root_hash chain",
     "E_TRUST_ANCHOR_MISMATCH"),
]

# Question 3 (can two occurrences be distinguished?) is separate from question
# 2: the request bug had records with a stable shape but no per-occurrence id,
# so r_1(path=x) and r_2(path=x) collapsed observationally.
# Question 7 catches the trust root, which the first six do not: a hash proves
# identity, but if the same authority can rewrite the object and its hash, it
# proves only that two mutable things agree.
DISTINGUISHABLE = {
    "r_i request": "request_id includes a nonce",
    "o_i request outcome": "keyed by request_id",
    "d_i delivery": "keyed by request_id",
    "O_instance ephemeral Self": "instance_id includes a nonce",
    "EVAL_Q^j evaluation": "audit_trace_root_hash + world_version",
    "f_j fold": "content-addressed over inputs",
    "Omega witness": "witness_hash per variant",
    "D^v risk revision": "revision_index + chain",
    "Gamma grant snapshot": "grant_version",
    "M merge set": "content-addressed over member deltas",
    "W_i^v sealed window": "window_hash per materialization",
    "Delta_i staged delta": "content-addressed",
    "tau_A admission trace": "admission_record_hash",
    "tau_effect effect trace": "effect_id",
    "S^v committed world": "version number",
    "Lambda^v policy": "lambda_hash per version",
    "Q_H probe set": "probe_set_hash",
    "L_spec locus specification": "grant_version",
    "trust root state": "root_version + chain",
}

ANCHOR = {
    "trust root state": "anchor/trust_anchor.txt, outside world/ and policy/",
}


def _s(o):
    import hashlib, json as _j
    return hashlib.sha256(
        _j.dumps(o, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def main() -> None:
    print("CET-0 topology-to-object audit\n")
    gaps = []
    for name, store, ident, versioned, refs, absence in NODES:
        obj = NO if store == "(none)" else YES
        distinct = DISTINGUISHABLE.get(name, NO)
        anchor = ANCHOR.get(name, "n/a -- authenticity not load-bearing")
        ok = (obj == YES and ident != NO and distinct != NO and versioned == YES
              and not absence.startswith("NOT DETECTABLE")
              and not anchor.startswith("UNANCHORED"))
        mark = "  " if ok else "!!"
        print(f"{mark} {name}")
        print(f"     1 object      : {store}")
        print(f"     2 identity    : {ident}")
        print(f"     3 distinct    : {distinct}")
        print(f"     4 versioned   : {versioned}")
        print(f"     5 referenced  : {refs}")
        print(f"     6 absence     : {absence}")
        print(f"     7 authenticity: {anchor}")
        if not ok:
            gaps.append(name)
    score = f"{len(NODES) - len(gaps)}/{len(NODES)}"
    print("\n" + "=" * 66)
    print(f"{score} nodes fully materialized")
    print(f"  relative to claim set {_s(DECLARED_CLAIMS)[:12]} "
          f"({len(DECLARED_CLAIMS)} declared claims)")
    print("  this is 'no missing identity found for the currently declared")
    print("  claims', not identity closure -- a new claim invalidates the score")

    # The audit result is itself a causal object with identity, so successive
    # runs are comparable rather than terminal output.
    import json as _j, sys, time
    rec = {
        "claim_set_hash": _s(DECLARED_CLAIMS),
        "audit_rule_version": AUDIT_RULE_VERSION,
        "cet_graph_hash": _s([n[0] for n in NODES]),
        "implementation_version": IMPLEMENTATION_VERSION,
        "expected_objects": len(NODES),
        "observed_objects": len(NODES) - len(gaps),
        "missing_objects": gaps,
        "score": score,
        "audited_at": time.time(),
    }
    rec["result_hash"] = _s({k: v for k, v in rec.items() if k != "audited_at"})
    rec["topology_audit_id"] = _s([rec["claim_set_hash"], rec["cet_graph_hash"],
                                   rec["result_hash"]])
    if len(sys.argv) > 1:
        path = sys.argv[1]
        with open(path, "a") as f:
            f.write(_j.dumps(rec, sort_keys=True) + "\n")
        print(f"audit record -> {path}  id={rec['topology_audit_id'][:12]}")
    else:
        print(f"audit id {rec['topology_audit_id'][:12]}  "
              f"(pass a path to commit the record)")
    if gaps:
        print("\nCandidate shortcuts around the topology:")
        for g in gaps:
            print(f"  - {g}")
        print("\nEach is a place where a downstream invariant would need an")
        print("identity that does not currently exist.")


if __name__ == "__main__":
    main()
