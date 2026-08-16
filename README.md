# CET-0

Minimal executable slice of CET v5. Pure stdlib Python, no dependencies.

```
python3 adversarial.py      # falsification suite -- 21 checks
python3 run_experiment.py   # experiment 001: parallel loci, engineered conflict
```

## What is implemented

The causal chain, executable:

```
S^v -> W_i^v -> O_i -> Delta_i(STAGING) -> A_local -> A_merge -> COMMIT -> S^(v+1)
```

Hard predicates (sec.31 base cases), each with a distinct rejection code:

| predicate | code | section |
|---|---|---|
| artifact.state == COMMITTED | `E_NOT_COMMITTED` | 37 |
| base_version == expected_version | `E_BASE_VERSION_STALE` | 48 |
| write_path ⊆ granted_write_region | `E_WRITE_OUTSIDE_GRANT` | 34 |
| read_path ⊆ granted_window | `E_READ_OUTSIDE_WINDOW` | 9 |
| delegation_depth <= 1 | `E_DELEGATION_DEPTH` | 58 |
| review_deadline >= promote_into | `E_LEASE_EXPIRED` | 50 |
| effect_class != EFFECT_OPEN in protected | `E_EFFECT_OPEN` | 52 |
| write sets disjoint | `E_WRITE_SET_CONFLICT` | 48 |
| sealed window exists before action | `E_NO_SEALED_WINDOW` | 41 |

Traces are emitted by the harness, never by the acting locus. `harness/` sits
outside `world/` because per sec.57 its correctness is an assurance claim
(`A_TCB`), seeded into `risk/delegated.jsonl` as `ASSUMED_UNVERIFIED`.

## Sealed windows and effect evidence

Every window is a first-class sealed artifact at `windows/<locus>/manifest.json`
plus `manifest.sha256`, recording base and target world version, artifact ids,
hashes, versions, review deadlines, exclusions with reasons, and a window hash.
Deliveries are traced separately at `audit/deliveries.jsonl`.

This exists so probes can read **effect evidence** (what the materialized world
shows happened) rather than **control evidence** (what the harness says it
did). The two differ exactly when something bypasses the intended gate, which
is the only case that can falsify the implementation.

| probe | evidence source |
|---|---|
| Q_H-001 | committed manifest diffs across versions |
| Q_H-002 | committed effects vs the grant snapshot in force at that event |
| Q_H-003 | admission trace (invocation class *is* the property) |
| Q_H-004 | sealed window manifests + delivery traces |
| Q_H-005 | merge decision records |
| Q_H-006 | `merge_set_hash` lineage |
| Q_H-007 | risk register lifecycle state |
| Q_H-008 | effect traces where enumerable, else UNDECIDABLE |

## Read-side chain and delivery fidelity

    S^v -> W_i^v -> r_i -> d_i -> R_i

Each of `W_i^v` (sealed window), `r_i` (request) and `d_i` (delivery) is a
separate addressable object with its own trace. The delivery predicate is

    D_exact(r,d,W) = [path_r == path_d] and [path_d in W]
                     and [hash(d) == hash_W(path_r)]

whose three conjuncts fail differently. Q_H-004 reports five classes:

| class | meaning | falsifies |
|---|---|---|
| `E_LEASE_GATE` | gate correctly refused stale input | no (control evidence) |
| `E_WINDOW_STALE` | expired artifact sealed into a window | yes |
| `E_DELIVERY_SUBSTITUTION` | `path_r != path_d` | yes |
| `E_WINDOW_MANIFEST_MISMATCH` | not in manifest, or content mutated after sealing | yes |
| `E_REQUEST_UNRESOLVED` | `countOutcomes(r_i) != 1` | yes |

Request outcomes are their own objects: `forall r_i, exists! o_i` with
`o_i in {DELIVERED, REJECTED}`. Totality is decided by `request_id`, not by
matching rejections to requests on `(locus, path)` -- that would be inference
by name rather than evidence.

## Evaluation and fold identity

`Q_H` has identity via `probe_set_hash`, but an *execution* of it did not, and
`EVAL_Q(S^v) != EVAL_Q(S^(v+1))` for the same probe set. Each evaluation is now
recorded in `probes/oversight/evaluations.jsonl` with `evaluation_id`,
`world_version`, `audit_trace_root_hash` (binding the exact traces read),
`evaluator_version` and `result_hash`, so repeated evaluations are comparable
rather than overwrite-like.

Folds are recorded in `lineage/folds.jsonl` with `fold_id` binding locus,
model identity, base version, window hash, input artifact hashes, grant
snapshot, consumed `request_ids`, output delta hashes and `parent_fold_id`.
Witnesses attach to a fold by identity, so the maximal/compressed/minimal
variants of one originating fold group cleanly -- which is what the
distillation experiments require.

## Effect-local authorization provenance

Every committed effect carries `effect_id`, `delta_hash`, `merge_set_hash`,
`locus_id`, `grant_snapshot_hash`, `grant_version`, `admission_record_hash`,
`base_world_version`, `commit_world_version`. Grants are versioned and
content-addressed in an append-only registry, so Q_H-002 resolves

    effect -> admission_record -> grant_snapshot

by immutable hash. The invariant is that exactly one grant snapshot authorized
each committed effect. "Most recent grant for this locus" is causally
ambiguous once a grant can mutate within a world version, and when the
snapshot cannot be resolved the probe answers UNDECIDABLE rather than
substituting a replacement grant.

## Declared semantics (choices that were ambiguous in the spec)

**Lease horizon.** `review_deadline` is checked against `base_version + 1` --
the version the artifact would be promoted *into*, not the one it is read
from. The looser reading admits an artifact into the very version at which it
expires, which makes the lease test pass for the wrong reason.

**Merge identity.** The unit of merge admissibility is the merge *set*, not the
individual delta. A delta belonging to a rejected set may legitimately be
committed alone afterwards. `merge_set_hash` is recorded at rejection time;
without it Q_H-006 is unanswerable after the fact, and comparing delta hashes
instead produces a false BREACH. (This was found by running the suite, not by
reading the spec.)

**Window membership vs delivery correctness.** Sealing the manifest bounds
*what could be delivered*; it does not determine *what was delivered for a
given request*. A substitution between two members of the same sealed window
passes a set-membership check. Deliveries therefore record `requested_path` and
`delivered_path` separately and the probe compares both. (Found by ADV-10
failing, not by reading the spec.)

**Three-valued probes.** `UNDECIDABLE` is a first-class answer. Q_H-008 can
only compare executed against admitted effects where effects are enumerable;
returning NO for an `EFFECT_BOUNDED` operation would report clean on exactly
the operations most likely to escape.

## Suite design

Negative tests assert the *specific* rejection code, and the suite carries
positive controls (`CTRL-1..3`): a benign write must be admitted, genuinely
disjoint concurrent deltas must both commit, an unexpired artifact must be
readable. Without these, a gate that rejects every transition passes every
adversarial test.

Two defect injections exist so the probes can be shown to fire:

- `executor_faulty=True` -- effect trace diverges from the admitted typed
  effect (simulated `A_TCB` failure). Q_H-008 must answer YES.
- `merge_gate_disabled=True` -- a detected conflict is logged as rejected and
  promoted anyway (simulated override). Q_H-006 must answer YES.

A probe that cannot answer YES under any condition is not evidence.

## Deliberately not implemented

Decomposition, recursive self-modification, KL lineage fidelity, MDL
optimization, NCD, audit compression, backpressure. Per the sequencing: these
land only after the state machine survives adversarial runs.

`gzip` is excluded from the declared compressor set now rather than later --
its 32KB match window makes `C(xy) ≈ C(x) + C(y)` on larger artifacts, so NCD
collapses to ≈1 regardless of similarity and reads as "independent branches".

## Experiment records

`experiment_record()` fixes the provenance schema before any model is in the
loop: model provider/name/version, tokenizer, harness version, world version,
window hash, probe set hash, lambda hash, compressor and version. Distortion is
decoder-relative -- `D_Q(W; R_O, M_v)` -- so a bare `distortion=0.08` is never
storable.

## Findings produced by execution

1. **Merge identity.** Q_H-006 reported a false BREACH: the rejected object is
   the merge set, not the delta. Fixed with `merge_set_hash`.
2. **Unenforced chain edge.** The first implementation let a locus propose with
   no materialized window at all -- sec.41 requires `W_i^v` before `O_i`, and
   nothing enforced it. Now `E_NO_SEALED_WINDOW`.
3. **Set membership is not delivery correctness.** ADV-10 failed because the
   probe only checked whether the delivered artifact was in the manifest. A
   substitution within the window is invisible to that check.
4. **The request was never materialized.** Applying the Materialized-Edge
   Principle to the read-side chain: `requested_path` existed only as a field
   inside the delivery record, so a request producing no delivery left no
   trace. The invariant "every request has exactly one outcome" was unstatable.
   Now `audit/requests.jsonl` with `request_id`, reconciled against deliveries
   and rejections.

## L_spec vs O_instance

A `locus_id` is a locus *specification*, not a Self identity. Under CET's own
premise -- hidden state is invocation-local and dies with the invocation --
two invocations of one specification are different Selves. `instantiate()`
issues an `instance_id`; effects, admissions and lineage name the instance, so
`O_reviewer^(1)` and `O_reviewer^(2)` are separable and repeated fresh-locus
trials stop looking like repeated observations of one persisting entity.

## Trust root: identity vs authenticity

`policy/trust_root.vN.json` is versioned and chained by `previous_root_hash`.
Authenticity terminates at `anchor/trust_anchor.txt`, which sits outside
`world/` and `policy/`. This matters because a root hash stored beside the root
proves only that two mutable objects agree: ADV-22 rewrites the genesis root
*and* recomputes its self-hash consistently, and only the external anchor
catches it. Identity is checkable inside CET; authenticity is not, which is
sec.46's terminal condition rather than a defect.

## Topology-to-object audit

`python3 audit_topology.py [path]` mechanizes the Materialized-Edge Principle
as a standing check over seven questions: object, identity, distinguishability
of two occurrences, versioning, exact referenceability, absence detection, and
where authenticity is anchored. Question 3 is separate from question 2 because
the request bug had records of stable shape but no per-occurrence id, so
`r_1(path=x)` and `r_2(path=x)` collapsed observationally. Question 7 catches
the trust root, which the first six do not.

Currently **19/19 relative to a declared 10-claim set**, which is "no missing
identity found for the currently declared claims", not identity closure. The
score is meaningless without `claim_set_hash`: adding a downstream claim
invalidates it, so `delta C => re-run the identity audit`. The audit result is
itself content-addressed
(`topology_audit_id`, `cet_graph_hash`, `result_hash`) so successive runs are
comparable rather than terminal output.

## Experiment 002 -- window rate-distortion

`python3 experiment_002_window_rd.py`

    min R(W)  s.t.  P(D_Q(W) > eps) <= alpha

eps, alpha, n, the probe set, the window ladder and the *selection rule* are
committed and hashed before any instance runs. Every observation carries
`experiment_run_id`, `model_identity`, `locus_spec_id`, `instance_id`,
`world_version`, `window_id`, `window_hash`, `window_rate_bytes`,
`probe_set_hash` and `task_distortion`, so a point on the curve names the
decoder instance, world state, window and evaluation that produced it. The
frontier is scoped to `(M_v, R_spec)`; curves are not merged across model
versions.

**The decoder is synthetic.** No model is wired in. `SyntheticDecoder` is a
seeded stand-in with a declared evidence dependency per probe. The numbers
exercise the machinery and validate its statistics; they say nothing about any
model. Swap the decoder and the identity fields are what make the resulting
points interpretable.

### Three protocol defects found by running it

1. **eps incommensurate with probe granularity.** With `k` probes `D_Q` takes
   values in multiples of `1/k`, so v1's `eps=0.05` with `k=5` meant `D > 0` --
   a declared 5% tolerance that tolerated nothing. Fixed with `k=20`.
2. **Selection over noisy point estimates.** In v1, W0..W3 all contained every
   probe dependency and so shared one true failure rate, yet observed failures
   were 7,4,1,6, and the rule selected W2 (7400 B) over the smaller, equally
   adequate W3 (6240 B). The rule now selects on the confidence bound and
   reports statistically tied candidates instead of silently picking one.
3. **n sized from the zero-failure bound.** `n>=14` certifies `alpha=0.20` only
   if the true rate is 0. At a true rate near 0.10 the requirement is `n>=45`,
   and near 0.17 it is `n>=410`. v2 at n=30 is underpowered for its own alpha,
   which the run now diagnoses explicitly rather than reporting a clean-looking
   selection.

Defects 1 and 2 changed the protocol hash, so v1 results are not grandfathered.
Defect 3 is the one worth carrying into the later experiments: fold-witness and
audit rate-distortion reuse this machinery and will need power analysis at
preregistration, not after.

## Experiment 003 -- calibrating the protocol itself

`python3 experiment_003_protocol_calibration.py`

Experiment 002 showed that trustworthy causal measurement can still support an
invalid statistical conclusion. So the protocol becomes the object of
falsification before a real decoder is attached. The decision is about the
latent run-level rate `p_i = P(D_ij > eps)`, with an indifference region
`alpha_good=0.10 < alpha_bad=0.20` and four outcomes -- `RELIABLE`,
`UNRELIABLE`, `INDETERMINATE`, `UNDERPOWERED` -- so no run is forced to pick a
winner and n stays bounded near the boundary.

Because the decoder is synthetic, `p_true` is known and the operating
characteristics are computed **exactly**; Monte Carlo is kept only as a
cross-check that the implementation matches the theory (max deviation 0.0075
over 8000 reps). Power analysis is inside the protocol hash. At `n=200` power
at `alpha_good` is 0.990 against a target of 0.80; the smallest adequate n is
90; exp002's n=30 gives power 0.411.

### Two findings

1. **Classifier precedence silently certified the indifference region.** At
   large n both conditions can hold at once -- the interval is narrow and lies
   strictly inside `(alpha_good, alpha_bad)`. That is not a contradiction, it
   is positive evidence that `p` sits exactly where the protocol declared it
   would not decide. Checking `RELIABLE` first converted that into a
   certification: at `p=0.15`, 54.9% of runs certified RELIABLE. Returning
   `INDETERMINATE` when both hold drops it to 0.317 and cuts false
   certification at `p=alpha_bad` from 0.043 to 0.011.
2. **Multiple comparison needs a worst-case ladder to be visible.** With bad
   rungs far above `alpha_bad` neither the naive nor the Bonferroni rule ever
   false-certifies, so the ladder proves nothing. Placing three bad rungs
   exactly *at* `alpha_bad` gives naive 0.0328 vs Bonferroni 0.0203
   family-wise. Naive stays under the 0.05 budget here only because the
   corrected classifier is conservative; Bonferroni is retained because the
   guarantee should not depend on the true rates being favourable.

The protocol makes **no** promise inside the indifference region -- at `p=0.15`
it certifies RELIABLE about a third of the time. That is the declared price of
keeping n bounded, and it should be stated to anyone reading a certification.

## Experiment 004 -- frozen protocol, typed certificate

`python3 experiment_004_frontier.py`

The statistical machinery is frozen: eps, alpha_good, alpha_bad, n, rung
ordering, cutoff table and family-wise rule are committed before any decoder
runs. Changing any of them yields a new `protocol_hash` and a new experiment
family rather than extending this one.

**The runtime classifier is an integer lookup table.** Because
`cp_upper(k,n) <= alpha_bad` is equivalent to `P(X<=k | p=alpha_bad) <= 1-conf`
and is monotone in `k`, the whole protocol reduces to two critical counts. The
evaluator does no statistics -- it compares two integers, which moves the
decision onto the mechanical side of sec.31 instead of leaving numerical root
finding in the trusted path. `INDETERMINATE` is checked first so evaluation
precedence cannot collapse the unclassified region into a certification.

At per-rung confidence 0.9917 the table reads `RELIABLE if k<=26,
UNRELIABLE if k>=32` -- the Bonferroni correction removes the overlap seen at
0.95 and opens a genuine indeterminate band at 27..31. Ordered testing from the
smallest window certified W3 and stopped without testing W2, W1 or W0.

The output is a typed certificate carrying `certification_target`,
`rejection_target`, `indifference_region`, per-rung exact false-certification
and false-rejection bounds, and an explicit
`no_promise_inside_indifference_region: true`, so a consumer cannot extract
"W3 certified" without the contract under which "certified" means anything.
`NO_WINDOW_CERTIFIED` and `INDETERMINATE` are results, not failed runs.

**No real decoder was run.** This environment has no model credentials, so an
`AnthropicDecoder` here would be untested code claiming to work. `Decoder` is
the contract a real one must satisfy -- `identity()` must return provider,
name, version_or_snapshot and tokenizer, because a distortion measurement
without them cannot be placed on any frontier. Supplying a real decoder runs
the protocol unchanged, which is the reason for freezing it now.

### Descriptive and decision arms are separate

The decision rule stops at the first `RELIABLE` rung. That must not truncate
the measured frontier, or non-monotonic reconstruction above the selected rung
is unobservable. Every rung is therefore measured; only the *selection* stops
early. Under the synthetic decoder the full ladder already shows monotonicity
violations that the ordered rule alone would never have surfaced. Known ground
truth says these are sampling variation -- W0..W3 share one true rate. With a
real decoder that oracle is gone, so a similar inversion is an empirical
anomaly requiring investigation, not something the protocol may explain away.
`monotonicity_violations` is therefore descriptive evidence only and must never
retroactively modify the frozen selection rule; otherwise observing a
surprising ladder becomes a licence to reinterpret the stopping criterion.

## Milestone freeze

`python3 freeze.py --write` then `python3 freeze.py`

`CET-0 Experimental Substrate v1.1` is content-hashed per file into
`MILESTONE.json`, so "frozen" is checkable rather than asserted. v1.1
supersedes v1 (`e260cffb4a83fb13`) with one change: the certificate now
carries `substrate_hash`, completing the chain `substrate -> decoder identity
-> run -> descriptive ladder -> decision certificate`. Without it a
measurement could not name the instrument that produced it. No preregistered
parameter changed, and the edit was made before any real measurement existed,
so nothing is invalidated. Until
experiment 004 runs against a real decoder the only permitted variable is the
decoder adapter.

The evidential state, stated sharply:

- **Established:** the causal architecture preserves the identities and
  distinctions required to interpret an experiment; the statistical protocol
  behaves per its declared operating characteristics under a known synthetic
  process.
- **Not established:** that real LLM reconstruction exhibits a useful
  rate-distortion frontier; that the identity conjecture holds outside the
  declared claim set; that precedence errors are generally impossible -- the
  final classifier has no overlap only under this parameterization, and an
  earlier one at conf=0.95 did overlap and concealed a bug.

## Distinction Preservation Principle

The same structural error has now appeared at three layers:

| layer | declared distinction | how it was lost |
|---|---|---|
| ontology | merge set vs delta | implementation tracked deltas |
| causal topology | `W_i^v` vs raw world | gate checked the world manifest |
| statistical protocol | INDETERMINATE vs RELIABLE | evaluation precedence |

Missing identity was one mechanism; control-flow precedence is another. The
general form:

> If the theory assigns different causal or epistemic meanings to states A and
> B, no implementation map may collapse `A, B -> C` unless that equivalence has
> been explicitly declared safe for all currently represented downstream
> claims.

The Persistent Causal Identity Conjecture is one case of this. Both inherit the
claim-set relativity of sec.56.

A second rule earned by experiment 003: **calibrate mechanisms at their
decision boundary, not only far from it.** Testing the ladder at p=0.35 and
0.60 showed only that easy cases work; placing bad rungs exactly at
`alpha_bad` was what exposed the multiple-comparison behaviour (naive 0.0328
vs Bonferroni 0.0203). That naive stayed under budget in that configuration is
an emergent consequence of a conservative single-rung classifier and is
explicitly **not** promoted to an invariant.

## Next falsification steps

1. Put a model in the loop as `O_1`/`O_2` and measure `P(merge conflict)` on
   real generative folds against a fixed workload declared in advance.
2. Add `EFFECT_BOUNDED` with a real sandbox and attempt escape; a successful
   escape falsifies the `A_TCB-001` register entry.
3. Attach a real decoder to the frozen experiment 004 protocol without
   changing any preregistered parameter, then fold-witness and audit
   rate-distortion on the same machinery.
4. Attempt to falsify the Persistent Causal Identity Conjecture: find a
   downstream-relevant intermediate whose identity is absent yet whose
   provenance and verification properties remain mechanically decidable
   without reconstructive inference. See "Falsification attempt" below.

## Falsification attempt on the identity conjecture

Two candidates were checked and neither falsifies it, but both clarify scope:

- **Artifacts copied forward at commit.** Each carried-forward artifact at
  `v+1` has no separate identity, yet nothing downstream is ambiguous --
  because it is deterministically reconstructible from `v`'s manifest plus the
  delta. Excluded by clause 1, so not a counterexample.
- **Merge order within a merge set.** Not deterministically reconstructible
  (it depends on call order) and not identified, yet no downstream claim needs
  it -- write-set disjointness makes order provably irrelevant. Fails clause 2.

The useful observation is that clause 1 is doing heavy lifting and is not
mechanically decidable in general: reconstructibility is indexed by a claim
set, `Reconstructible(x | S, C)`, so the property is `NeedIdentity(x, C)` and
not `NeedIdentity(x)`. Since `C_declared != C_all_future`, the conjecture
inherits the objective-enumerability boundary from sec.56 rather than escaping
it, and the seven-question audit is a heuristic proxy, not a decision
procedure. A genuine counterexample would need a distinction that is
non-reconstructible, downstream-relevant, and still unambiguous -- none found
so far, but the search space has only been probed where the conjecture was
already expected to hold.
