"""
CET-0 harness core.

This module is the Trusted Computing Base. Per CET v5 sec.57, its correctness
is an ASSURANCE CLAIM (A_TCB), not a fact derivable from modeled state. It
therefore lives outside world/ and is never itself an artifact of the world it
governs. Nothing in world/ can modify this file through the admissibility path.

Implements the executable slice:
    S^v -> W_i^v -> O_i -> Delta_i(STAGING) -> A_local -> A_merge -> COMMIT -> S^(v+1)

Traces are emitted by the harness, never by the acting locus.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Any

# ---------------------------------------------------------------------------
# Rejection codes. Every gate failure names exactly one. Tests assert on these,
# not merely on the fact of rejection -- a gate that rejects everything must
# not be able to pass the adversarial suite.
# ---------------------------------------------------------------------------

E_NOT_COMMITTED       = "E_NOT_COMMITTED"        # sec.37 projection requires COMMITTED
E_BASE_VERSION_STALE  = "E_BASE_VERSION_STALE"   # sec.48 optimistic concurrency
E_WRITE_OUTSIDE_GRANT = "E_WRITE_OUTSIDE_GRANT"  # sec.34 capability ceiling
E_READ_OUTSIDE_WINDOW = "E_READ_OUTSIDE_WINDOW"  # sec.9 window bound
E_DELEGATION_DEPTH    = "E_DELEGATION_DEPTH"     # sec.58 d_max
E_LEASE_EXPIRED       = "E_LEASE_EXPIRED"        # sec.50 bounded liveness
E_EFFECT_OPEN         = "E_EFFECT_OPEN"          # sec.52 interface precision
E_WRITE_SET_CONFLICT  = "E_WRITE_SET_CONFLICT"   # sec.48 merge admissibility
E_UNKNOWN_LOCUS       = "E_UNKNOWN_LOCUS"
E_NO_SEALED_WINDOW    = "E_NO_SEALED_WINDOW"   # sec.41 chain order: W_i^v precedes O_i
E_DELIVERY_SUBSTITUTION   = "E_DELIVERY_SUBSTITUTION"    # path(d) != path(r)
E_DELIVERY_CONTENT        = "E_DELIVERY_CONTENT"         # hash(d) != hash_W(path(r))
E_GRANT_PROVENANCE_BROKEN = "E_GRANT_PROVENANCE_BROKEN"  # no unique authorizing grant
E_REQUEST_UNRESOLVED      = "E_REQUEST_UNRESOLVED"       # r_i with no d_i and no rejection
E_TRUST_ANCHOR_MISMATCH   = "E_TRUST_ANCHOR_MISMATCH"    # root chain disagrees with anchor
E_RISK_REVISION_BROKEN    = "E_RISK_REVISION_BROKEN"     # risk history not chained
E_MALFORMED_OP        = "E_MALFORMED_OP"

EFFECT_ENUMERABLE = "EFFECT_ENUMERABLE"
EFFECT_BOUNDED    = "EFFECT_BOUNDED"
EFFECT_OPEN       = "EFFECT_OPEN"


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _match_any(path: str, globs: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, g) for g in globs)


def vdir(n: int) -> str:
    return f"v{n:06d}"


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@dataclass
class Op:
    """A candidate typed boundary event (e^out*)."""
    op: str                       # READ | WRITE | DELEGATE | EXEC
    path: str | None = None
    content: str | None = None
    effect_class: str = EFFECT_ENUMERABLE
    to_locus: str | None = None   # DELEGATE
    grant: dict | None = None     # DELEGATE
    command: str | None = None    # EXEC
    review_deadline: int | None = None   # WRITE: lease expiry, in world versions

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class Decision:
    admitted: bool
    code: str | None = None
    detail: str = ""
    delta_hash: str | None = None


@dataclass
class Delta:
    """Private staged output of one locus. Not visible to any other locus
    until COMMITTED (sec.37)."""
    locus_id: str
    base_version: int
    ops: list[Op] = field(default_factory=list)
    admitted: bool = False
    reads: list[str] = field(default_factory=list)
    # Effect-local authorization provenance, bound at admission time. Resolving
    # "the grant for this locus" by chronology is causally ambiguous once a
    # grant can mutate within a world version.
    grant_snapshot_hash: str | None = None
    grant_version: int | None = None
    admission_record_hash: str | None = None
    request_ids: list[str] = field(default_factory=list)
    instance_id: str | None = None

    def write_set(self) -> set[str]:
        return {o.path for o in self.ops if o.op == "WRITE" and o.path}

    def hash(self) -> str:
        return _sha(_canon({
            "locus": self.locus_id,
            "base": self.base_version,
            "ops": [o.to_dict() for o in self.ops],
        }))


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

class Harness:
    HARNESS_VERSION = "cet0-0.1.0"

    def __init__(self, root: str, executor_faulty: bool = False,
                 merge_gate_disabled: bool = False,
                 materializer_ignores_lease: bool = False,
                 delivery_diverges: str | None = None,
                 drop_requests: bool = False):
        """Both flags are deliberate defect injections, used to demonstrate that
        the oversight probes can actually fire. A probe that cannot answer YES
        under any condition is not evidence of anything.

        executor_faulty     -- effect trace diverges from admitted typed effect
                               (simulated A_TCB failure); targets Q_H-008.
        merge_gate_disabled -- a detected merge conflict is logged as rejected
                               and then promoted anyway (simulated override);
                               targets Q_H-006.
        materializer_ignores_lease -- an expired artifact is sealed into the
                               window anyway; targets Q_H-004/E_WINDOW_STALE.
        delivery_diverges   -- path actually handed to the locus, regardless of
                               what the sealed manifest lists; targets
                               Q_H-004/E_WINDOW_MANIFEST_MISMATCH.
        """
        self.root = os.path.abspath(root)
        self.executor_faulty = executor_faulty
        self.merge_gate_disabled = merge_gate_disabled
        self.materializer_ignores_lease = materializer_ignores_lease
        self.delivery_diverges = delivery_diverges
        self.drop_requests = drop_requests

    # -- layout ------------------------------------------------------------

    def p(self, *parts: str) -> str:
        return os.path.join(self.root, *parts)

    def init(self, policy: dict | None = None) -> None:
        for d in ("world/committed", "staging", "grants", "policy", "windows",
                  "leases", "probes/oversight", "risk", "audit", "lineage", "anchor"):
            os.makedirs(self.p(*d.split("/")), exist_ok=True)

        pol = policy or {
            "d_max": 1,
            "protected_paths": ["protected/*"],
            "effect_open_forbidden_in_protected": True,
            # Lease semantics, declared explicitly. An artifact is promoted INTO
            # version base+1, so its deadline is checked against base+1, not
            # base. The looser reading would admit an artifact into the very
            # version at which it expires.
            "lease_checked_against": "base_version_plus_one",
        }
        self._write_json(self.p("policy", "lambda.json"), pol)
        # sec.46 terminal condition. The root's IDENTITY is inside CET; its
        # AUTHENTICITY is anchored outside the authority it governs. If the
        # same authority could rewrite both trust_root and its hash, the hash
        # would only prove that two mutable objects agree with each other.
        root = {
            "root_id": "cet0-root",
            "root_version": 1,
            "previous_root_hash": None,
            "form": "immutable",
            "effective_world_version": 1,
            "authorization_evidence": "genesis",
            "harness_version": self.HARNESS_VERSION,
            "a_tcb": "ASSUMED_UNVERIFIED",
        }
        root["root_hash"] = _sha(_canon({k: v for k, v in root.items()
                                         if k != "root_hash"}))
        self._write_json(self.p("policy", "trust_root.v1.json"), root)
        os.makedirs(self.p("anchor"), exist_ok=True)
        with open(self.p("anchor", "trust_anchor.txt"), "w") as f:
            f.write(root["root_hash"] + "\n")


        v1 = self.p("world", "committed", vdir(1))
        os.makedirs(os.path.join(v1, "artifacts"), exist_ok=True)
        self._write_json(os.path.join(v1, "manifest.json"),
                         {"version": 1, "artifacts": {}, "lambda_hash": _sha(_canon(pol))})
        self.put_risk_revision(
            "A_TCB-001", status="ASSUMED", review_deadline=100,
            desired_property="harness enforces declared effect containment",
            reason_not_compiled="not decidable from modeled state")

    # -- io helpers --------------------------------------------------------

    @staticmethod
    def _write_json(path: str, obj: Any) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(json.dumps(obj, indent=2, sort_keys=True))

    @staticmethod
    def _read_json(path: str) -> Any:
        with open(path) as f:
            return json.load(f)

    @staticmethod
    def _append_jsonl(path: str, obj: Any) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a") as f:
            f.write(json.dumps(obj, sort_keys=True) + "\n")

    def policy(self) -> dict:
        return self._read_json(self.p("policy", "lambda.json"))

    def current_version(self) -> int:
        vs = [int(d[1:]) for d in os.listdir(self.p("world", "committed"))
              if d.startswith("v")]
        return max(vs) if vs else 0

    def manifest(self, v: int) -> dict:
        return self._read_json(self.p("world", "committed", vdir(v), "manifest.json"))

    # -- grants ------------------------------------------------------------

    def put_grant(self, locus_id: str, read_window: list[str], write_region: list[str],
                  delegation_depth: int = 0, max_effect_class: str = EFFECT_ENUMERABLE,
                  parent: str | None = None) -> dict:
        """Grants are versioned and content-addressed. Every snapshot is
        appended to an immutable registry so a committed effect can name the
        exact grant that authorized it, rather than the latest one."""
        prev = self.grant(locus_id)
        gv = (prev["grant_version"] + 1) if prev else 1
        body = {
            "locus_id": locus_id,
            "read_window": read_window,
            "write_region": write_region,
            "delegation_depth": delegation_depth,
            "max_effect_class": max_effect_class,
            "parent": parent,
            "grant_version": gv,
        }
        body["grant_snapshot_hash"] = _sha(_canon(
            {k: v for k, v in body.items() if k != "grant_snapshot_hash"}))
        self._write_json(self.p("grants", f"{locus_id}.json"), body)
        self._append_jsonl(self.p("grants", "snapshots.jsonl"),
                           {"ts": time.time(), "world_version": self.current_version(),
                            **body})
        return body

    # -- delegated risk register, event-sourced (sec.54) -------------------

    def risk_revisions(self, property_id: str | None = None) -> list[dict]:
        path = self.p("risk", "revisions.jsonl")
        if not os.path.exists(path):
            return []
        out = []
        with open(path) as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    if property_id is None or r["property_id"] == property_id:
                        out.append(r)
        return out

    def put_risk_revision(self, property_id: str, status: str,
                          review_deadline: int | None = None,
                          evidence_hashes: list[str] | None = None,
                          evaluator_id: str | None = None,
                          evaluation_id: str | None = None, **fields) -> dict:
        """A property_id names the enduring property; it cannot name a
        particular STATE of that property. Revisions are chained so status
        history is recoverable and last_evaluated_version is derivable from
        immutable lineage rather than a mutable field."""
        prior = self.risk_revisions(property_id)
        rec = {
            "property_id": property_id,
            "revision_index": len(prior) + 1,
            "previous_revision_hash": prior[-1]["revision_hash"] if prior else None,
            "status": status,
            "evidence_hashes": sorted(evidence_hashes or []),
            "evaluator_id": evaluator_id,
            "evaluation_id": evaluation_id,
            "world_version": self.current_version(),
            "review_deadline": review_deadline,
            "created_at": time.time(),
            **fields,
        }
        rec["risk_revision_id"] = _sha(_canon(
            {k: v for k, v in rec.items() if k != "created_at"}))
        rec["revision_hash"] = _sha(_canon(rec))
        self._append_jsonl(self.p("risk", "revisions.jsonl"), rec)
        return rec

    def risk_current(self, property_id: str) -> dict | None:
        """D^v(p): latest admissible revision as of the current version."""
        revs = self.risk_revisions(property_id)
        return revs[-1] if revs else None

    # -- trust root --------------------------------------------------------

    def trust_root_chain(self) -> list[dict]:
        out = []
        i = 1
        while os.path.exists(self.p("policy", f"trust_root.v{i}.json")):
            out.append(self._read_json(self.p("policy", f"trust_root.v{i}.json")))
            i += 1
        return out

    def verify_trust_root(self) -> tuple[bool, str]:
        """Identity is checkable inside CET; authenticity terminates at the
        anchor, which lives outside world/ and policy/."""
        ap = self.p("anchor", "trust_anchor.txt")
        if not os.path.exists(ap):
            return False, "anchor absent"
        anchor = open(ap).read().strip()
        chain = self.trust_root_chain()
        if not chain:
            return False, "no trust root"
        genesis = chain[0]
        recomputed = _sha(_canon({k: v for k, v in genesis.items()
                                  if k != "root_hash"}))
        if recomputed != genesis.get("root_hash"):
            return False, f"{E_TRUST_ANCHOR_MISMATCH}: genesis self-hash invalid"
        if genesis["root_hash"] != anchor:
            return False, f"{E_TRUST_ANCHOR_MISMATCH}: genesis != anchor"
        for prev, cur in zip(chain, chain[1:]):
            if cur.get("previous_root_hash") != prev.get("root_hash"):
                return False, f"{E_TRUST_ANCHOR_MISMATCH}: chain break at v{cur.get('root_version')}"
        return True, f"anchored, {len(chain)} root version(s)"

    # -- locus instances (sec.12) ------------------------------------------

    def instantiate(self, locus_spec_id: str, model_identity: dict | None = None,
                    parent_instance_id: str | None = None) -> str:
        """L_spec != O_instance. Under CET's own premise hidden state is
        invocation-local and dies with the invocation, so two invocations of
        one specification are DIFFERENT Selves. A locus_id string cannot carry
        that distinction."""
        rec = {
            "locus_spec_id": locus_spec_id,
            "model_identity": model_identity,
            "parent_instance_id": parent_instance_id,
            "harness_version": self.HARNESS_VERSION,
            "grant_snapshot_hash": (self.grant(locus_spec_id) or {}).get("grant_snapshot_hash"),
            "world_version": self.current_version(),
            "started_at": time.time(),
            "nonce": os.urandom(8).hex(),
        }
        rec["instance_id"] = _sha(_canon(rec))
        self._append_jsonl(self.p("lineage", "instances.jsonl"), rec)
        return rec["instance_id"]

    def terminate(self, instance_id: str) -> None:
        self._append_jsonl(self.p("lineage", "instances.jsonl"),
                           {"instance_id": instance_id, "event": "TERMINATED",
                            "terminated_at": time.time()})

    def grant_by_hash(self, gh: str) -> dict | None:
        """Exactly one snapshot must match. Zero matches is a provenance
        failure; it must not fall back to the current grant."""
        path = self.p("grants", "snapshots.jsonl")
        if not os.path.exists(path):
            return None
        hits = []
        with open(path) as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    if r.get("grant_snapshot_hash") == gh:
                        hits.append(r)
        return hits[0] if len(hits) >= 1 else None

    def grant(self, locus_id: str) -> dict | None:
        path = self.p("grants", f"{locus_id}.json")
        return self._read_json(path) if os.path.exists(path) else None

    # -- windows (sec.37: versioned snapshot projection) -------------------

    # -- window materialization (sec.9, sec.37) ----------------------------
    #
    # A window is a first-class SEALED artifact, not a transient computation.
    # The sealed manifest records what the locus ACTUALLY received, so probes
    # can read effect evidence rather than the gate's claim about its own
    # behaviour.
    #
    # Lease contract, declared once and read by both materializer and probe:
    #     a is window-eligible iff  v_review(a) >= v_target,  v_target = v_base + 1
    # review_deadline means "valid through this version".

    MATERIALIZER_VERSION = "mat-0.1.0"

    def materialize_window(self, locus_id: str, base_version: int) -> dict:
        g = self.grant(locus_id)
        man = self.manifest(base_version)
        target = base_version + 1

        included: dict[str, dict] = {}
        excluded: dict[str, str] = {}
        for path, meta in man["artifacts"].items():
            if meta["state"] != "COMMITTED":
                excluded[path] = E_NOT_COMMITTED
                continue
            if g and not _match_any(path, g["read_window"]):
                continue  # outside the window by grant; not an exclusion event
            dl = meta.get("review_deadline")
            stale = dl is not None and dl < target
            if stale and not self.materializer_ignores_lease:
                excluded[path] = E_LEASE_EXPIRED
                continue
            included[path] = meta

        wm = {
            "locus_id": locus_id,
            "base_world_version": base_version,
            "target_world_version": target,
            "artifact_ids": sorted(included),
            "artifact_hashes": {p: m.get("hash") for p, m in included.items()},
            "artifact_versions": {p: m.get("created_version") for p, m in included.items()},
            "artifact_review_deadlines": {p: m.get("review_deadline") for p, m in included.items()},
            "excluded": excluded,
            "materialized_at": time.time(),
            "materializer_version": self.MATERIALIZER_VERSION,
            "harness_version": self.HARNESS_VERSION,
        }
        wm["window_hash"] = _sha(_canon({k: wm[k] for k in
                                         ("locus_id", "base_world_version",
                                          "target_world_version", "artifact_ids",
                                          "artifact_hashes")}))
        d = self.p("windows", locus_id)
        os.makedirs(d, exist_ok=True)
        self._write_json(os.path.join(d, "manifest.json"), wm)
        with open(os.path.join(d, "manifest.sha256"), "w") as f:
            f.write(_sha(_canon(wm)) + "\n")
        self._append_jsonl(self.p("audit", "windows.jsonl"),
                           {"ts": time.time(), "event": "SEALED", **wm})
        return wm

    def sealed_window(self, locus_id: str) -> dict | None:
        path = self.p("windows", locus_id, "manifest.json")
        return self._read_json(path) if os.path.exists(path) else None

    def record_request(self, locus_id: str, path: str) -> str:
        """r_i as its own addressable object, recorded BEFORE any outcome."""
        wm = self.sealed_window(locus_id)
        request_id = _sha(_canon([locus_id, path, time.time(), os.urandom(4).hex()]))
        self._append_jsonl(self.p("audit", "requests.jsonl"), {
            "ts": time.time(), "request_id": request_id,
            "locus_id": locus_id, "requested_path": path,
            "window_hash": (wm or {}).get("window_hash"),
            "harness_version": self.HARNESS_VERSION,
        })
        return request_id

    def record_outcome(self, request_id: str, outcome: str, detail: str = "") -> None:
        """o_i as its own object. The totality condition countOutcomes(r_i)==1
        is only decidable if outcomes reference requests by identity; matching
        rejections to requests by (locus, path) is inference, not evidence."""
        self._append_jsonl(self.p("audit", "request_outcomes.jsonl"), {
            "ts": time.time(), "request_id": request_id,
            "outcome": outcome, "detail": detail,
            "harness_version": self.HARNESS_VERSION,
        })

    def deliver(self, locus_id: str, path: str,
                request_id: str | None = None) -> tuple[str | None, str]:
        """d_i, emitted only when the outcome is DELIVERED."""
        wm = self.sealed_window(locus_id)
        if request_id is None:
            request_id = self.record_request(locus_id, path)
        if wm is None:
            self.record_outcome(request_id, "REJECTED", E_NO_SEALED_WINDOW)
            return None, E_NO_SEALED_WINDOW
        if self.drop_requests:
            return None, "DROPPED"   # injected: request with no outcome at all
        actual = path
        if self.delivery_diverges:
            actual = self.delivery_diverges
        v = wm["base_world_version"]
        fp = self.p("world", "committed", vdir(v), "artifacts", actual)
        body = open(fp).read() if os.path.exists(fp) else None
        self._append_jsonl(self.p("audit", "deliveries.jsonl"), {
            "ts": time.time(), "request_id": request_id, "locus_id": locus_id,
            "requested_path": path, "delivered_path": actual,
            "delivered_hash": _sha(body) if body is not None else None,
            "sealed_hash_for_requested": wm["artifact_hashes"].get(path),
            "base_world_version": v, "window_hash": wm["window_hash"],
            "harness_version": self.HARNESS_VERSION,
        })
        self.record_outcome(request_id, "DELIVERED", actual)
        return body, "OK"

    # -- fold identity (sec.22, sec.24, sec.62) ----------------------------

    def record_fold(self, locus_id: str, base_version: int,
                    request_ids_consumed: list[str], output_delta_hashes: list[str],
                    model_identity: dict | None = None,
                    parent_fold_id: str | None = None) -> str:
        """f_j. A witness is a witness TO something; without fold identity,
        multiple witnesses of the same originating fold cannot be compared,
        which is precisely what the distillation experiments require."""
        wm = self.sealed_window(locus_id) or {}
        g = self.grant(locus_id) or {}
        rec = {
            "locus_id": locus_id,
            "model_identity": model_identity,
            "base_world_version": base_version,
            "window_hash": wm.get("window_hash"),
            "input_artifact_hashes": wm.get("artifact_hashes", {}),
            "grant_snapshot_hash": g.get("grant_snapshot_hash"),
            "request_ids_consumed": sorted(request_ids_consumed),
            "output_delta_hashes": sorted(output_delta_hashes),
            "parent_fold_id": parent_fold_id,
            "started_at": time.time(),
        }
        rec["fold_id"] = _sha(_canon({k: v for k, v in rec.items()
                                      if k != "started_at"}))
        rec["completed_at"] = time.time()
        self._append_jsonl(self.p("lineage", "folds.jsonl"), rec)
        return rec["fold_id"]

    def record_witness(self, fold_id: str, variant: str, content: str) -> str:
        """Omega attached to f_j by identity, not by filename or timestamp."""
        wh = _sha(content)
        self._append_jsonl(self.p("lineage", "witnesses.jsonl"), {
            "ts": time.time(), "fold_id": fold_id, "variant": variant,
            "witness_hash": wh, "rate_bytes": len(content.encode()),
            "harness_version": self.HARNESS_VERSION,
        })
        return wh

    def window_hash(self, window: dict) -> str:
        return window["window_hash"]

    def read_artifact(self, version: int, path: str) -> str:
        with open(self.p("world", "committed", vdir(version), "artifacts", path)) as f:
            return f.read()

    # -- local admissibility (A_local) -------------------------------------

    def propose(self, delta: Delta) -> Decision:
        pol = self.policy()
        g = self.grant(delta.locus_id)
        if g is None:
            return self._reject(delta, E_UNKNOWN_LOCUS, delta.locus_id)

        # Bind the authorizing grant snapshot NOW, so the effect can name it
        # by hash later regardless of subsequent grant mutation.
        delta.grant_snapshot_hash = g.get("grant_snapshot_hash")
        delta.grant_version = g.get("grant_version")

        cur = self.current_version()
        if delta.base_version != cur:
            return self._reject(delta, E_BASE_VERSION_STALE,
                                f"base={delta.base_version} current={cur}")

        man = self.manifest(delta.base_version)
        # sec.41: W_i^v precedes O_i. A locus that never had a materialized
        # window has no epistemic state to act from, and nothing exists that a
        # probe could inspect as effect evidence.
        wm = self.sealed_window(delta.locus_id)
        if wm is None or wm["base_world_version"] != delta.base_version:
            return self._reject(delta, E_NO_SEALED_WINDOW,
                                f"no sealed window at v{delta.base_version}")
        promote_into = wm["target_world_version"]

        for o in delta.ops:
            if o.op in ("READ", "WRITE") and not o.path:
                return self._reject(delta, E_MALFORMED_OP, o.op)

            if o.op == "READ":
                rid = self.record_request(delta.locus_id, o.path)
                delta.request_ids.append(rid)
                if not _match_any(o.path, g["read_window"]):
                    self.record_outcome(rid, "REJECTED", E_READ_OUTSIDE_WINDOW)
                    return self._reject(delta, E_READ_OUTSIDE_WINDOW, o.path)
                # Read the sealed window, not the raw world manifest: the
                # window is what the locus actually has.
                if o.path in wm["excluded"]:
                    self.record_outcome(rid, "REJECTED", wm["excluded"][o.path])
                    return self._reject(delta, wm["excluded"][o.path],
                                        f"{o.path} excluded at materialization")
                if o.path not in wm["artifact_ids"]:
                    meta = man["artifacts"].get(o.path)
                    code = (E_NOT_COMMITTED if meta is None
                            or meta["state"] != "COMMITTED" else E_READ_OUTSIDE_WINDOW)
                    self.record_outcome(rid, "REJECTED", code)
                    return self._reject(delta, code, o.path)
                self.deliver(delta.locus_id, o.path, request_id=rid)

            elif o.op == "WRITE":
                if not _match_any(o.path, g["write_region"]):
                    return self._reject(delta, E_WRITE_OUTSIDE_GRANT, o.path)
                if self._effect_open_blocked(o, pol, o.path):
                    return self._reject(delta, E_EFFECT_OPEN, o.path)

            elif o.op == "EXEC":
                target = o.path or ""
                if self._effect_open_blocked(o, pol, target):
                    return self._reject(delta, E_EFFECT_OPEN, target)
                if target and not _match_any(target, g["write_region"]):
                    return self._reject(delta, E_WRITE_OUTSIDE_GRANT, target)

            elif o.op == "DELEGATE":
                # sec.58: bounded depth is the compilable construction.
                child_depth = g["delegation_depth"] + 1
                if child_depth > pol["d_max"]:
                    return self._reject(delta, E_DELEGATION_DEPTH,
                                        f"parent_depth={g['delegation_depth']} d_max={pol['d_max']}")
                # sec.34: no self-amplification -- child region must be a subset.
                child_writes = (o.grant or {}).get("write_region", [])
                if not set(child_writes).issubset(set(g["write_region"])):
                    return self._reject(delta, E_WRITE_OUTSIDE_GRANT,
                                        f"delegate {child_writes} exceeds {g['write_region']}")
            else:
                return self._reject(delta, E_MALFORMED_OP, o.op)

        delta.admitted = True
        self._trace_admission(delta, True, None, "")
        self._stage(delta)
        return Decision(True, delta_hash=delta.hash())

    def _effect_open_blocked(self, o: Op, pol: dict, path: str) -> bool:
        if o.effect_class != EFFECT_OPEN:
            return False
        if not pol.get("effect_open_forbidden_in_protected", True):
            return False
        return _match_any(path, pol["protected_paths"])

    def _reject(self, delta: Delta, code: str, detail: str) -> Decision:
        self._trace_admission(delta, False, code, detail)
        return Decision(False, code, detail, delta.hash())

    def _trace_admission(self, delta: Delta, admitted: bool,
                         code: str | None, detail: str) -> None:
        # Emitted by the harness, not the locus. delta_hash is recorded on
        # rejection so Q_H-006 can identify a rejected delta if it later
        # appears in a commit.
        rec = {
            "ts": time.time(),
            "locus_id": delta.locus_id,
            "base_version": delta.base_version,
            "delta_hash": delta.hash(),
            "ops": [o.to_dict() for o in delta.ops],
            "write_set": sorted(delta.write_set()),
            "admitted": admitted,
            "code": code,
            "detail": detail,
            "instance_id": delta.instance_id,
            "grant_snapshot_hash": delta.grant_snapshot_hash,
            "grant_version": delta.grant_version,
            "window_hash": (self.sealed_window(delta.locus_id) or {}).get("window_hash"),
            "harness_version": self.HARNESS_VERSION,
        }
        rec["admission_record_hash"] = _sha(_canon(
            {k: v for k, v in rec.items() if k != "ts"}))
        delta.admission_record_hash = rec["admission_record_hash"]
        self._append_jsonl(self.p("audit", "admission.jsonl"), rec)

    def _stage(self, delta: Delta) -> None:
        d = self.p("staging", delta.locus_id)
        os.makedirs(d, exist_ok=True)
        self._write_json(os.path.join(d, "delta.json"), {
            "locus_id": delta.locus_id,
            "base_version": delta.base_version,
            "delta_hash": delta.hash(),
            "ops": [o.to_dict() for o in delta.ops],
        })

    # -- merge admissibility (A_merge) + atomic commit ---------------------

    def merge_commit(self, deltas: list[Delta]) -> Decision:
        """sec.48. Locally valid deltas may still be jointly inadmissible."""
        cur = self.current_version()
        for d in deltas:
            if not d.admitted:
                return Decision(False, E_NOT_COMMITTED, f"{d.locus_id} not admitted")
            if d.base_version != cur:
                return Decision(False, E_BASE_VERSION_STALE, d.locus_id)

        # The unit of merge admissibility is the merge SET, not the individual
        # delta. A delta that was part of a rejected set may legitimately be
        # committed alone later; only re-promotion of the same set is a breach.
        merge_set_hash = _sha(_canon(sorted(d.hash() for d in deltas)))

        seen: dict[str, str] = {}
        conflict: str | None = None
        for d in deltas:
            for w in d.write_set():
                if w in seen:
                    conflict = f"{w} written by {seen[w]} and {d.locus_id}"
                    break
                seen[w] = d.locus_id
            if conflict:
                break

        if conflict:
            self._append_jsonl(self.p("audit", "admission.jsonl"), {
                "ts": time.time(), "stage": "MERGE",
                "locus_id": [x.locus_id for x in deltas],
                "delta_hash": [x.hash() for x in deltas],
                "merge_set_hash": merge_set_hash,
                "admitted": False, "code": E_WRITE_SET_CONFLICT,
                "detail": conflict, "base_version": cur,
                "harness_version": self.HARNESS_VERSION,
            })
            if not self.merge_gate_disabled:
                return Decision(False, E_WRITE_SET_CONFLICT, conflict)
            # Injected override: proceed to commit a set already logged as
            # rejected. Q_H-006 must catch this.

        new_v = cur + 1
        src = self.p("world", "committed", vdir(cur))
        dst = self.p("world", "committed", vdir(new_v))
        os.makedirs(os.path.join(dst, "artifacts"), exist_ok=True)
        man = json.loads(json.dumps(self.manifest(cur)))
        man["version"] = new_v

        # copy forward
        for path in man["artifacts"]:
            s = os.path.join(src, "artifacts", path)
            t = os.path.join(dst, "artifacts", path)
            os.makedirs(os.path.dirname(t), exist_ok=True)
            if os.path.exists(s):
                with open(s) as f:
                    body = f.read()
                with open(t, "w") as f:
                    f.write(body)

        executed: list[dict] = []
        for d in deltas:
            for o in d.ops:
                if o.op != "WRITE":
                    continue
                actual_path = o.path
                if self.executor_faulty:
                    # Deliberate TCB-divergence injection: the executor writes
                    # somewhere other than the admitted typed effect.
                    actual_path = o.path + ".shadow"
                t = os.path.join(dst, "artifacts", actual_path)
                os.makedirs(os.path.dirname(t), exist_ok=True)
                with open(t, "w") as f:
                    f.write(o.content or "")
                man["artifacts"][actual_path] = {
                    "state": "COMMITTED",
                    "hash": _sha(o.content or ""),
                    "review_deadline": o.review_deadline,
                    "author": d.locus_id,
                    "created_version": new_v,
                }
                executed.append({
                    # Complete causal authorization reference. Q_H-002 resolves
                    # effect -> admission_record -> grant_snapshot by immutable
                    # hash, never by "the most recent grant for this locus".
                    "effect_id": _sha(_canon([d.hash(), o.path, len(executed)])),
                    "delta_hash": d.hash(),
                    "merge_set_hash": merge_set_hash,
                    "locus_id": d.locus_id,
                    "instance_id": d.instance_id,
                    "grant_snapshot_hash": d.grant_snapshot_hash,
                    "grant_version": d.grant_version,
                    "admission_record_hash": d.admission_record_hash,
                    "base_world_version": d.base_version,
                    "commit_world_version": new_v,
                    "op": "WRITE",
                    "admitted_path": o.path, "actual_path": actual_path,
                    "effect_class": o.effect_class, "version": new_v,
                })

        self._write_json(os.path.join(dst, "manifest.json"), man)

        for e in executed:
            self._append_jsonl(self.p("audit", "effects.jsonl"),
                               {"ts": time.time(), **e,
                                "harness_version": self.HARNESS_VERSION})

        self._append_jsonl(self.p("audit", "admission.jsonl"), {
            "ts": time.time(), "stage": "MERGE",
            "locus_id": [d.locus_id for d in deltas],
            "delta_hash": [d.hash() for d in deltas],
            "merge_set_hash": merge_set_hash,
            "admitted": True, "code": None, "detail": "",
            "base_version": cur, "committed_version": new_v,
            "write_set": sorted(seen.keys()),
            "harness_version": self.HARNESS_VERSION,
        })
        self._append_jsonl(self.p("lineage", "commits.jsonl"), {
            "version": new_v, "parents": [cur],
            "deltas": [d.hash() for d in deltas],
        })
        for d in deltas:
            sd = self.p("staging", d.locus_id, "delta.json")
            if os.path.exists(sd):
                os.remove(sd)
        return Decision(True, detail=f"committed {vdir(new_v)}")

    # -- observation of another locus's staging (must fail) ----------------

    def peek_staging(self, observer: str, target: str) -> Decision:
        """sec.37: ordinary projection requires COMMITTED. Staging is private."""
        self._append_jsonl(self.p("audit", "admission.jsonl"), {
            "ts": time.time(), "locus_id": observer, "stage": "PEEK",
            "target": target, "admitted": False, "code": E_NOT_COMMITTED,
            "detail": f"{observer} attempted to observe staging of {target}",
            "base_version": self.current_version(), "delta_hash": None,
            "harness_version": self.HARNESS_VERSION,
        })
        return Decision(False, E_NOT_COMMITTED, "staging is not projectable")
