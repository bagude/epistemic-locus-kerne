"""
CET-0 adversarial suite.

Each test asserts the SPECIFIC rejection code, not merely that rejection
occurred. Positive controls are included because a gate that rejects every
transition would otherwise pass every negative test -- the suite must be able
to distinguish a correct gate from a closed one.

Falsification: any FAIL below falsifies the corresponding CET section as
implemented.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile

from harness.core import (
    Harness, Delta, Op, E_NO_SEALED_WINDOW,
    E_WRITE_SET_CONFLICT, E_LEASE_EXPIRED, E_DELEGATION_DEPTH,
    E_EFFECT_OPEN, E_NOT_COMMITTED, E_WRITE_OUTSIDE_GRANT,
    EFFECT_ENUMERABLE, EFFECT_BOUNDED, EFFECT_OPEN,
)
from harness import probes

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


def fresh(faulty: bool = False, materializer_ignores_lease: bool = False) -> Harness:
    root = tempfile.mkdtemp(prefix="cet0_")
    h = Harness(root, executor_faulty=faulty,
                materializer_ignores_lease=materializer_ignores_lease)
    h.init()
    probes.write_probe_contract(h)
    return h


def act(h: Harness, locus: str, ops: list) -> tuple[Delta, "object"]:
    """Follow the chain order: W_i^v is materialized and sealed BEFORE the
    locus proposes. sec.41 requires this; the first implementation let a locus
    act with no window at all."""
    v = h.current_version()
    h.materialize_window(locus, v)
    d = Delta(locus, v, ops)
    return d, h.propose(d)


def seed(h: Harness, path: str, content: str, deadline: int | None = None) -> None:
    """Seed via the ordinary admissibility path -- no privileged back door."""
    h.put_grant("seeder", ["*"], ["*"], delegation_depth=0)
    d, dec = act(h, "seeder", [Op("WRITE", path=path, content=content,
                                 review_deadline=deadline)])
    assert dec.admitted, f"seed must be admissible: {dec.code}"
    assert h.merge_commit([d]).admitted, "seed must commit"


# ---------------------------------------------------------------------------
# Positive controls
# ---------------------------------------------------------------------------

def control_benign_write() -> None:
    h = fresh()
    h.put_grant("o1", ["work/*"], ["work/*"])
    v = h.current_version()
    d, dec = act(h, "o1", [Op("WRITE", path="work/a.txt", content="hello")])
    check("CTRL-1 benign write admitted", dec.admitted, dec.code or "")
    m = h.merge_commit([d])
    check("CTRL-1 benign write commits", m.admitted, m.code or "")
    check("CTRL-1 world advanced", h.current_version() == v + 1,
          f"v{h.current_version()}")


def control_disjoint_concurrency() -> None:
    """Genuinely disjoint concurrent deltas must BOTH commit. Without this, a
    merge gate that rejects all concurrency passes the conflict test."""
    h = fresh()
    h.put_grant("o1", ["work/*"], ["work/a.txt"])
    h.put_grant("o2", ["work/*"], ["work/b.txt"])
    d1, r1 = act(h, "o1", [Op("WRITE", path="work/a.txt", content="A")])
    d2, r2 = act(h, "o2", [Op("WRITE", path="work/b.txt", content="B")])
    ok1, ok2 = r1.admitted, r2.admitted
    dec = h.merge_commit([d1, d2])
    man = h.manifest(h.current_version())["artifacts"] if dec.admitted else {}
    check("CTRL-2 disjoint concurrent deltas both commit",
          ok1 and ok2 and dec.admitted and "work/a.txt" in man and "work/b.txt" in man,
          dec.code or "")


def control_fresh_artifact_readable() -> None:
    """An unexpired artifact must be readable -- otherwise the lease test
    passes because reads never work at all."""
    h = fresh()
    seed(h, "protected/spec.txt", "spec", deadline=99)
    h.put_grant("child", ["protected/*"], ["work/*"])
    d, dec = act(h, "child", [Op("READ", path="protected/spec.txt")])
    check("CTRL-3 unexpired artifact readable", dec.admitted, dec.code or "")


# ---------------------------------------------------------------------------
# Adversarial tests
# ---------------------------------------------------------------------------

def adv_merge_conflict() -> None:
    """sec.48. Two locally valid deltas, same write path. Both local gates must
    pass; the merge gate must reject; the world must contain exactly one."""
    h = fresh()
    h.put_grant("o1", ["work/*"], ["work/*"])
    h.put_grant("o2", ["work/*"], ["work/*"])
    v = h.current_version()
    d1, l1 = act(h, "o1", [Op("WRITE", path="work/shared.txt", content="from-1")])
    d2, l2 = act(h, "o2", [Op("WRITE", path="work/shared.txt", content="from-2")])
    check("ADV-1 both deltas locally admissible", l1.admitted and l2.admitted)
    dec = h.merge_commit([d1, d2])
    check("ADV-1 merge gate rejects with E_WRITE_SET_CONFLICT",
          (not dec.admitted) and dec.code == E_WRITE_SET_CONFLICT, str(dec.code))
    check("ADV-1 world did not advance", h.current_version() == v,
          f"v{h.current_version()}")
    # Serialised, one at a time, must still work.
    solo = h.merge_commit([d1])
    check("ADV-1 serialised commit still admitted", solo.admitted, solo.code or "")


def adv_staging_isolation() -> None:
    """sec.37. Staged work must not be projectable into another locus."""
    h = fresh()
    h.put_grant("o1", ["work/*"], ["work/*"])
    h.put_grant("o2", ["work/*"], ["work/*"])
    v = h.current_version()
    d1, _ = act(h, "o1", [Op("WRITE", path="work/secret.txt", content="staged")])
    dec = h.peek_staging("o2", "o1")
    check("ADV-2 staging not observable (E_NOT_COMMITTED)",
          (not dec.admitted) and dec.code == E_NOT_COMMITTED, str(dec.code))
    w = h.materialize_window("o2", v)
    check("ADV-2 staged artifact absent from o2 sealed window",
          "work/secret.txt" not in w["artifact_ids"])


def adv_expired_lease() -> None:
    """sec.50. Expire an artifact, then attempt to project it."""
    h = fresh()
    # deadline=2 means: valid to be promoted into v2, not v3.
    seed(h, "protected/stale.txt", "old", deadline=2)
    h.put_grant("child", ["protected/*"], ["work/*"])
    seed(h, "work/filler.txt", "x")   # advance the world past the deadline
    v = h.current_version()
    wm = h.materialize_window("child", v)
    check("ADV-3 expired artifact excluded from sealed window",
          "protected/stale.txt" in wm["excluded"]
          and wm["excluded"]["protected/stale.txt"] == E_LEASE_EXPIRED,
          str(wm["excluded"]))
    d = Delta("child", v, [Op("READ", path="protected/stale.txt")])
    dec = h.propose(d)
    check("ADV-3 expired artifact rejected with E_LEASE_EXPIRED",
          (not dec.admitted) and dec.code == E_LEASE_EXPIRED, str(dec.code))


def adv_transitive_delegation() -> None:
    """sec.58. d_max=1: a delegated capability may be used, not re-delegated."""
    h = fresh()
    h.put_grant("o1", ["work/*"], ["work/*"], delegation_depth=0)
    v = h.current_version()
    d, dec1 = act(h, "o1", [Op("DELEGATE", to_locus="o2",
                               grant={"write_region": ["work/*"]})])
    check("ADV-4 first-hop delegation admitted (depth 0->1)",
          dec1.admitted, dec1.code or "")
    h.put_grant("o2", ["work/*"], ["work/*"], delegation_depth=1, parent="o1")
    d2, dec2 = act(h, "o2", [Op("DELEGATE", to_locus="o3",
                                grant={"write_region": ["work/*"]})])
    check("ADV-4 transitive delegation rejected with E_DELEGATION_DEPTH",
          (not dec2.admitted) and dec2.code == E_DELEGATION_DEPTH, str(dec2.code))
    # sec.34: delegation must not amplify beyond the parent's own region.
    d3, dec3 = act(h, "o1", [Op("DELEGATE", to_locus="o4",
                                grant={"write_region": ["protected/*"]})])
    check("ADV-4 amplifying delegation rejected with E_WRITE_OUTSIDE_GRANT",
          (not dec3.admitted) and dec3.code == E_WRITE_OUTSIDE_GRANT, str(dec3.code))


def adv_effect_open() -> None:
    """sec.52. EFFECT_OPEN must not cross into a protected region."""
    h = fresh()
    h.put_grant("o1", ["*"], ["*"])
    d, dec = act(h, "o1", [Op("EXEC", path="protected/out.txt",
                              command="sh -c 'echo hi'", effect_class="EFFECT_OPEN")])
    check("ADV-5 EFFECT_OPEN in protected region rejected with E_EFFECT_OPEN",
          (not dec.admitted) and dec.code == E_EFFECT_OPEN, str(dec.code))
    # Same op outside the protected region is allowed -- the gate discriminates
    # on region, not on refusing everything.
    d2, dec2 = act(h, "o1", [Op("EXEC", path="work/out.txt",
                                command="sh -c 'echo hi'", effect_class="EFFECT_OPEN")])
    check("ADV-5 EFFECT_OPEN outside protected region admitted",
          dec2.admitted, dec2.code or "")


def adv_probe_can_fire() -> None:
    """Q_H-008 must be able to answer YES. A probe that cannot fire is not
    evidence. Inject an executor that writes somewhere other than the admitted
    typed effect -- this is a simulated A_TCB failure."""
    h = fresh(faulty=True)
    h.put_grant("o1", ["work/*"], ["work/*"])
    d, _ = act(h, "o1", [Op("WRITE", path="work/a.txt", content="A")])
    h.merge_commit([d])
    res = probes.evaluate(h)
    check("ADV-6 Q_H-008 detects injected effect divergence",
          res["Q_H-008"]["answer"] == probes.YES, res["Q_H-008"]["answer"])

    # And must report UNDECIDABLE, not NO, on non-enumerable effects.
    h2 = fresh()
    h2.put_grant("o1", ["work/*"], ["work/*"])
    d2, _ = act(h2, "o1", [Op("WRITE", path="work/b.txt", content="B",
                              effect_class=EFFECT_BOUNDED)])
    h2.merge_commit([d2])
    res2 = probes.evaluate(h2)
    check("ADV-6 Q_H-008 reports UNDECIDABLE on non-enumerable effects",
          res2["Q_H-008"]["answer"] == probes.UNDECIDABLE,
          res2["Q_H-008"]["answer"])


def adv_rejected_merge_not_promoted() -> None:
    """Q_H-006. A delta from a rejected merge set may legitimately be committed
    alone -- that must answer NO. Only re-promotion of the same SET is a
    breach, and the probe must be able to detect it."""
    h = fresh()
    h.put_grant("o1", ["work/*"], ["work/*"])
    h.put_grant("o2", ["work/*"], ["work/*"])
    d1, _ = act(h, "o1", [Op("WRITE", path="work/s.txt", content="1")])
    d2, _ = act(h, "o2", [Op("WRITE", path="work/s.txt", content="2")])
    h.merge_commit([d1, d2])          # rejected as a set
    h.merge_commit([d1])              # d1 alone is legitimate
    res = probes.evaluate(h)
    check("ADV-7 Q_H-006 NO when a rejected set's member commits alone",
          res["Q_H-006"]["answer"] == probes.NO, res["Q_H-006"]["evidence"])

    # Injected override: the same conflicting set is promoted anyway.
    h2 = fresh()
    h2.merge_gate_disabled = True
    h2.put_grant("o1", ["work/*"], ["work/*"])
    h2.put_grant("o2", ["work/*"], ["work/*"])
    e1, _ = act(h2, "o1", [Op("WRITE", path="work/s.txt", content="1")])
    e2, _ = act(h2, "o2", [Op("WRITE", path="work/s.txt", content="2")])
    h2.merge_commit([e1, e2])
    res2 = probes.evaluate(h2)
    check("ADV-7 Q_H-006 detects injected merge override",
          res2["Q_H-006"]["answer"] == probes.YES, res2["Q_H-006"]["evidence"])



def adv_no_sealed_window() -> None:
    """sec.41 chain order. A locus with no materialized window has no
    epistemic state to act from, and nothing a probe could inspect."""
    h = fresh()
    h.put_grant("o1", ["work/*"], ["work/*"])
    d = Delta("o1", h.current_version(),
              [Op("WRITE", path="work/a.txt", content="x")])
    dec = h.propose(d)          # deliberately skips materialize_window
    check("ADV-8 action without sealed window rejected (E_NO_SEALED_WINDOW)",
          (not dec.admitted) and dec.code == E_NO_SEALED_WINDOW, str(dec.code))


def adv_window_stale_detectable() -> None:
    """Q_H-004/E_WINDOW_STALE. If the materializer ignores the lease, a stale
    artifact is sealed into the window. The probe must catch it from the
    manifest -- the gate never fires, so control evidence shows nothing."""
    h = fresh(materializer_ignores_lease=True)
    seed(h, "protected/stale.txt", "old", deadline=2)
    seed(h, "work/filler.txt", "x")
    h.put_grant("child", ["protected/*"], ["work/*"])
    h.materialize_window("child", h.current_version())
    res = probes.evaluate(h)
    check("ADV-9 Q_H-004 detects stale artifact in sealed window",
          res["Q_H-004"]["answer"] == probes.YES
          and "E_WINDOW_STALE" in res["Q_H-004"]["evidence"],
          res["Q_H-004"]["evidence"][:70])


def adv_window_manifest_mismatch() -> None:
    """Q_H-004/E_WINDOW_MANIFEST_MISMATCH. Delivery bypasses the manifest."""
    h = fresh()
    seed(h, "protected/spec.txt", "spec", deadline=99)
    seed(h, "protected/other.txt", "other", deadline=99)
    h.put_grant("child", ["protected/*"], ["work/*"])
    h.materialize_window("child", h.current_version())
    h.delivery_diverges = "protected/other.txt"
    # request one artifact, harness hands over a different one
    h.deliver("child", "protected/spec.txt")
    res = probes.evaluate(h)
    check("ADV-10 Q_H-004 classifies as E_DELIVERY_SUBSTITUTION",
          res["Q_H-004"]["answer"] == probes.YES
          and "E_DELIVERY_SUBSTITUTION" in res["Q_H-004"]["evidence"],
          res["Q_H-004"]["evidence"][:70])


def adv_effect_evidence_dominates() -> None:
    """Q_H-001 must read committed state, not admission records. A protected
    write that was authorised but never committed must answer NO."""
    h = fresh()
    h.put_grant("o1", ["*"], ["*"])
    d, dec = act(h, "o1", [Op("WRITE", path="protected/p.txt", content="p")])
    check("ADV-11 protected write admitted but not committed", dec.admitted)
    res = probes.evaluate(h)
    check("ADV-11 Q_H-001 answers NO on uncommitted protected write",
          res["Q_H-001"]["answer"] == probes.NO, res["Q_H-001"]["evidence"][:60])
    h.merge_commit([d])
    res2 = probes.evaluate(h)
    check("ADV-11 Q_H-001 answers YES once committed",
          res2["Q_H-001"]["answer"] == probes.YES, res2["Q_H-001"]["evidence"][:60])




def adv_grant_resolved_by_hash() -> None:
    """(1) Admit under Gamma_1, mutate the grant to Gamma_2, then commit the
    earlier delta. Q_H-002 must resolve Gamma_1, not 'latest grant'."""
    h = fresh()
    g1 = h.put_grant("o1", ["work/*"], ["work/*"])
    d, dec = act(h, "o1", [Op("WRITE", path="work/a.txt", content="A")])
    check("ADV-12 admitted under Gamma_1", dec.admitted, dec.code or "")
    # Grant narrows AFTER admission but BEFORE commit. Under the old
    # chronological resolution this write would look like a breach.
    g2 = h.put_grant("o1", ["work/*"], ["other/*"])
    check("ADV-12 grant mutated to a disjoint region",
          g2["grant_version"] == 2 and g1["grant_snapshot_hash"] != g2["grant_snapshot_hash"])
    h.merge_commit([d])
    res = probes.evaluate(h)
    check("ADV-12 Q_H-002 resolves the authorizing grant, not the latest",
          res["Q_H-002"]["answer"] == probes.NO, res["Q_H-002"]["evidence"][:70])


def adv_two_grants_same_version() -> None:
    """(2) Two grant snapshots within one world version; effect identity must
    stay unambiguous."""
    h = fresh()
    h.put_grant("o1", ["work/*"], ["work/a.txt"])
    d1, r1 = act(h, "o1", [Op("WRITE", path="work/a.txt", content="A")])
    h.put_grant("o1", ["work/*"], ["work/b.txt"])
    d2, r2 = act(h, "o1", [Op("WRITE", path="work/b.txt", content="B")])
    check("ADV-13 both deltas admitted under different snapshots",
          r1.admitted and r2.admitted
          and d1.grant_snapshot_hash != d2.grant_snapshot_hash,
          f"gv{d1.grant_version} vs gv{d2.grant_version}")
    h.merge_commit([d1, d2])
    res = probes.evaluate(h)
    check("ADV-13 Q_H-002 clean with two snapshots in one version",
          res["Q_H-002"]["answer"] == probes.NO, res["Q_H-002"]["evidence"][:70])


def adv_tampered_grant_hash() -> None:
    """(3) Tamper with grant_snapshot_hash in an effect record. The probe must
    report a provenance-integrity error, not infer a replacement grant."""
    h = fresh()
    h.put_grant("o1", ["work/*"], ["work/*"])
    d, _ = act(h, "o1", [Op("WRITE", path="work/a.txt", content="A")])
    h.merge_commit([d])
    fp = h.p("audit", "effects.jsonl")
    rows = [json.loads(l) for l in open(fp) if l.strip()]
    for r in rows:
        r["grant_snapshot_hash"] = "deadbeef" * 8
    with open(fp, "w") as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True) + "\n")
    res = probes.evaluate(h)
    check("ADV-14 Q_H-002 returns UNDECIDABLE on broken grant provenance",
          res["Q_H-002"]["answer"] == probes.UNDECIDABLE
          and "E_GRANT_PROVENANCE_BROKEN" in res["Q_H-002"]["evidence"],
          res["Q_H-002"]["evidence"][:60])


def adv_content_mutated_after_sealing() -> None:
    """(4) Correct path, altered bytes after window sealing. Path membership
    passes; the content conjunct of D_exact must fail."""
    h = fresh()
    seed(h, "protected/spec.txt", "original", deadline=99)
    h.put_grant("child", ["protected/*"], ["work/*"])
    v = h.current_version()
    h.materialize_window("child", v)
    # Mutate the committed bytes underneath the sealed manifest.
    fp = h.p("world", "committed", f"v{v:06d}", "artifacts", "protected/spec.txt")
    with open(fp, "w") as f:
        f.write("tampered")
    h.deliver("child", "protected/spec.txt")
    res = probes.evaluate(h)
    check("ADV-15 Q_H-004 detects content mutation at correct path",
          res["Q_H-004"]["answer"] == probes.YES
          and "mutated" in res["Q_H-004"]["evidence"],
          res["Q_H-004"]["evidence"][:70])


def adv_substitution_within_window() -> None:
    """(5) Request A, deliver B, both in the same sealed window."""
    h = fresh()
    seed(h, "protected/a.txt", "A", deadline=99)
    seed(h, "protected/b.txt", "B", deadline=99)
    h.put_grant("child", ["protected/*"], ["work/*"])
    h.materialize_window("child", h.current_version())
    wm = h.sealed_window("child")
    check("ADV-16 both artifacts in the same sealed window",
          "protected/a.txt" in wm["artifact_ids"] and "protected/b.txt" in wm["artifact_ids"])
    h.delivery_diverges = "protected/b.txt"
    h.deliver("child", "protected/a.txt")
    res = probes.evaluate(h)
    check("ADV-16 D_exact rejects substitution inside the window",
          res["Q_H-004"]["answer"] == probes.YES
          and "E_DELIVERY_SUBSTITUTION" in res["Q_H-004"]["evidence"],
          res["Q_H-004"]["evidence"][:70])




def adv_dropped_request() -> None:
    """Materialized-Edge Principle applied to r_i. A request that receives
    neither a delivery nor a rejection is invisible unless the request is its
    own addressable object -- 'requested_path' as a field inside the delivery
    record cannot represent a request that produced no delivery."""
    h = fresh()
    seed(h, "protected/spec.txt", "spec", deadline=99)
    h.put_grant("child", ["protected/*"], ["work/*"])
    h.materialize_window("child", h.current_version())
    h.drop_requests = True
    h.deliver("child", "protected/spec.txt")   # silently produces nothing
    res = probes.evaluate(h)
    check("ADV-17 Q_H-004 detects a request with no outcome",
          res["Q_H-004"]["answer"] == probes.YES
          and "E_REQUEST_UNRESOLVED" in res["Q_H-004"]["evidence"],
          res["Q_H-004"]["evidence"][:70])




def adv_evaluation_instance_identity() -> None:
    """EVAL_Q(S^v) != EVAL_Q(S^(v+1)) for the same probe set. Two evaluations
    must be distinguishable and comparable, not overwrite-like."""
    h = fresh()
    h.put_grant("o1", ["work/*"], ["work/*"])
    probes.evaluate(h)
    d, _ = act(h, "o1", [Op("WRITE", path="work/a.txt", content="A")])
    h.merge_commit([d])
    probes.evaluate(h)
    rows = [json.loads(l) for l in
            open(h.p("probes", "oversight", "evaluations.jsonl")) if l.strip()]
    check("ADV-18 two evaluation instances recorded", len(rows) == 2, str(len(rows)))
    check("ADV-18 same probe set, different evaluation identity",
          rows[0]["probe_set_hash"] == rows[1]["probe_set_hash"]
          and rows[0]["evaluation_id"] != rows[1]["evaluation_id"])
    check("ADV-18 evaluation records the world version actually evaluated",
          rows[0]["world_version"] == 1 and rows[1]["world_version"] == 2,
          f"{rows[0]['world_version']},{rows[1]['world_version']}")
    check("ADV-18 evaluation binds the exact traces read",
          rows[0]["audit_trace_root_hash"] != rows[1]["audit_trace_root_hash"])


def adv_fold_witness_identity() -> None:
    """Multiple witnesses of ONE originating fold must be comparable. Without
    fold identity the distillation experiments cannot group them."""
    h = fresh()
    seed(h, "work/in.txt", "input")
    h.put_grant("o1", ["work/*"], ["work/*"])
    v = h.current_version()
    h.materialize_window("o1", v)
    d = Delta("o1", v, [Op("READ", path="work/in.txt"),
                        Op("WRITE", path="work/out.txt", content="output")])
    dec = h.propose(d)
    check("ADV-19 fold delta admitted", dec.admitted, dec.code or "")
    fid = h.record_fold("o1", v, request_ids_consumed=d.request_ids,
                        output_delta_hashes=[d.hash()],
                        model_identity={"provider": None, "name": None})
    w_max = h.record_witness(fid, "maximal", "full reasoning trace " * 20)
    w_mid = h.record_witness(fid, "compressed", "key decisions only")
    w_min = h.record_witness(fid, "minimal", "output")
    rows = [json.loads(l) for l in
            open(h.p("lineage", "witnesses.jsonl")) if l.strip()]
    check("ADV-19 three witnesses share one fold_id",
          len({r["fold_id"] for r in rows}) == 1 and len(rows) == 3)
    check("ADV-19 witnesses distinguishable by hash and rate",
          len({r["witness_hash"] for r in rows}) == 3
          and rows[0]["rate_bytes"] > rows[2]["rate_bytes"],
          f"{[r['rate_bytes'] for r in rows]}")
    folds = [json.loads(l) for l in
             open(h.p("lineage", "folds.jsonl")) if l.strip()]
    check("ADV-19 fold binds window, grant and consumed requests",
          folds[0]["window_hash"] is not None
          and folds[0]["grant_snapshot_hash"] is not None
          and folds[0]["request_ids_consumed"] == sorted(d.request_ids))




def adv_risk_revision_history() -> None:
    """property_id names the enduring property, not a state of it. History must
    be recoverable and tampering detectable."""
    h = fresh()
    h.put_risk_revision("A_TCB-001", status="UNDER_TEST", review_deadline=100)
    h.put_risk_revision("A_TCB-001", status="FAILED", review_deadline=100)
    revs = h.risk_revisions("A_TCB-001")
    check("ADV-20 full status history recoverable",
          [r["status"] for r in revs] == ["ASSUMED", "UNDER_TEST", "FAILED"],
          str([r["status"] for r in revs]))
    check("ADV-20 revisions chained by previous_revision_hash",
          revs[1]["previous_revision_hash"] == revs[0]["revision_hash"]
          and revs[2]["previous_revision_hash"] == revs[1]["revision_hash"])
    check("ADV-20 D^v(p) returns the latest revision",
          h.risk_current("A_TCB-001")["status"] == "FAILED")
    # Excise a middle revision: the chain must break rather than read as clean.
    fp = h.p("risk", "revisions.jsonl")
    rows = [json.loads(l) for l in open(fp) if l.strip()]
    with open(fp, "w") as f:
        for r in rows[:1] + rows[2:]:
            f.write(json.dumps(r, sort_keys=True) + "\n")
    res = probes.evaluate(h)
    check("ADV-20 Q_H-007 detects excised revision (E_RISK_REVISION_BROKEN)",
          res["Q_H-007"]["answer"] == probes.UNDECIDABLE
          and "E_RISK_REVISION_BROKEN" in res["Q_H-007"]["evidence"],
          res["Q_H-007"]["evidence"][:50])


def adv_locus_instance_identity() -> None:
    """L_spec != O_instance. Two invocations of one specification are different
    Selves, because hidden state is invocation-local and dies with it."""
    h = fresh()
    h.put_grant("reviewer", ["work/*"], ["work/*"])
    i1 = h.instantiate("reviewer", model_identity={"name": None})
    i2 = h.instantiate("reviewer", model_identity={"name": None})
    check("ADV-21 same spec yields distinct instance identities", i1 != i2,
          f"{i1[:8]} vs {i2[:8]}")
    child = h.instantiate("reviewer", parent_instance_id=i1)
    rows = [json.loads(l) for l in
            open(h.p("lineage", "instances.jsonl")) if l.strip()]
    check("ADV-21 instance lineage points to an instance, not a name",
          any(r.get("instance_id") == child and r.get("parent_instance_id") == i1
              for r in rows))
    # Effects must carry the instance, so two runs of one spec are separable.
    v = h.current_version()
    h.materialize_window("reviewer", v)
    d = Delta("reviewer", v, [Op("WRITE", path="work/a.txt", content="A")])
    d.instance_id = i1
    h.propose(d); h.merge_commit([d])
    eff = [json.loads(l) for l in open(h.p("audit", "effects.jsonl")) if l.strip()]
    check("ADV-21 committed effect names the ephemeral Self that produced it",
          eff[0]["instance_id"] == i1, str(eff[0].get("instance_id"))[:8])


def adv_trust_root_anchor() -> None:
    """Identity inside CET; authenticity anchored outside it. Rewriting both
    the root and its hash must still be detected."""
    h = fresh()
    ok, detail = h.verify_trust_root()
    check("ADV-22 genesis root verifies against external anchor", ok, detail)

    # Legitimate evolution: v2 chained to v1.
    v1 = h.trust_root_chain()[0]
    v2 = {"root_id": "cet0-root", "root_version": 2,
          "previous_root_hash": v1["root_hash"], "form": "immutable",
          "effective_world_version": 1, "authorization_evidence": "quorum-sim",
          "harness_version": h.HARNESS_VERSION, "a_tcb": "ASSUMED_UNVERIFIED"}
    v2["root_hash"] = h._write_json(h.p("policy", "trust_root.v2.json"), v2) or None
    import harness.core as core
    v2["root_hash"] = core._sha(core._canon({k: x for k, x in v2.items()
                                             if k != "root_hash"}))
    h._write_json(h.p("policy", "trust_root.v2.json"), v2)
    ok2, d2 = h.verify_trust_root()
    check("ADV-22 chained root evolution still verifies", ok2, d2)

    # Attack: rewrite the genesis root AND its self-hash consistently. Internal
    # consistency holds; only the external anchor exposes it.
    forged = dict(v1); forged["form"] = "mutable-by-locus"
    forged["root_hash"] = core._sha(core._canon(
        {k: x for k, x in forged.items() if k != "root_hash"}))
    h._write_json(h.p("policy", "trust_root.v1.json"), forged)
    ok3, d3 = h.verify_trust_root()
    check("ADV-22 self-consistent forgery caught by external anchor",
          (not ok3) and "ANCHOR_MISMATCH" in d3, d3[:60])



def main() -> int:
    print("CET-0 adversarial suite\n")
    for fn in (control_benign_write, control_disjoint_concurrency,
               control_fresh_artifact_readable, adv_merge_conflict,
               adv_staging_isolation, adv_expired_lease,
               adv_transitive_delegation, adv_effect_open,
               adv_probe_can_fire, adv_rejected_merge_not_promoted,
               adv_no_sealed_window, adv_window_stale_detectable,
               adv_window_manifest_mismatch, adv_effect_evidence_dominates,
               adv_grant_resolved_by_hash, adv_two_grants_same_version,
               adv_tampered_grant_hash, adv_content_mutated_after_sealing,
               adv_substitution_within_window, adv_dropped_request,
               adv_evaluation_instance_identity, adv_fold_witness_identity,
               adv_risk_revision_history, adv_locus_instance_identity,
               adv_trust_root_anchor):
        print(f"\n{fn.__name__}")
        fn()

    print("\n" + "=" * 66)
    failed = [n for n, ok, _ in RESULTS if not ok]
    print(f"{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    if failed:
        print("FALSIFIED:")
        for n in failed:
            print(f"  - {n}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
