# Task 04: Access-Control Under Conflicting Policy Versions — Research Synthesis

**Substrate:** CET-0 Experimental Substrate v1.1, `c871cc8e2994639c` (unchanged throughout).
**Pack:** CET_REAL_TASKS_v1, `fd266ee246d839e6`.
**Branch:** every protocol below was committed *before* its measurements ran; every raw answer is preserved in a committed journal.

## The question

A decoder (an LLM instance) is given a sealed evidence window and asked five
questions about a contractor access request. The world contains a current
policy (v4), explicit version lineage, and a coherent *superseded* reality
(policy v3 plus a 2025 exception memo). The window ladder varies what the
decoder sees:

| rung | contents | bytes |
|---|---|---|
| W4 | task + obsolete world only | 541 |
| W3 | task + current substantive rules | 871 |
| W2 | W3 + explicit version manifest | 1009 |
| W1 | W2 + superseded conflicting evidence | 1299 |
| W0 | W1 + historical decision under old rules | 1373 |

Three empirical questions: **sufficiency** (W3 vs W2 — is version metadata
load-bearing?), **contamination** (W1/W0 vs W2 — does coherent stale evidence
degrade reconstruction?), and **invalid-world reconstruction** (W4 — does
stale-only context trigger abstention or confident confabulation?).

## Findings

### 1. Locally grounded ⇏ currently correct (Smoke v1, n=1; replicated at scale)

The first real-decoder run of the frozen exp004 machinery (fable, W4 vs W2)
showed the decoder does not hallucinate arbitrary policy: it reconstructs a
*coherent world from evidence genuinely present in its window* — and that
world is obsolete. W2 → distortion 0.0; W4 → 0.8, grounded fluently in v3.

### 2. Correct answer ≠ correct epistemic basis (Smoke v1 → 92% at scale)

W4's Q4 ("does the 2025 exception change the answer?") returned the correct
"No" *for the wrong reason* ("v3 already permits 30 days" rather than "v4
supersedes the exception"). Outcome-only grading cannot see this. In the
aborted powered run (fable, 77 W4 instances), the signature appeared in
**71/77 (92%)** of instances. This motivated outcome-plus-basis grading:
score = (y = y*) ∧ (B = B*).

### 3. Two instrument defects were caught by small preregistered runs before any powered spend

- **Smoke v1 (n=1, ~2 instances)** caught the basis defect above.
- **The pilot (n=104, haiku)** caught a second: 17 of its 20 run failures
  were the decoder naming the correct authority ("Policy v4") without the
  literal filename `policy_v4.md` demanded by the v2 substring rule — a
  naming-convention artifact, not a reconstruction error. It also exposed a
  semantics gap: binary grading coerced honest INSUFFICIENT answers into
  "wrong", erasing the very distinction the ladder measures.

Both fixes were folded into **probes_v3**: three-valued probe classes
(PASS / CONFIDENT_FAIL / ABSTAINED), strict decision failure (any non-PASS —
an abstaining window cannot be certified sufficient), with the
confabulation/abstention decomposition preserved descriptively.

This is the Distinction Preservation Principle operating on the measurement
instrument itself: each defect was a declared distinction (correct basis vs
correct surface; abstention vs error) that the implementation collapsed, and
each was found by *executing* a cheap run, not by reading the spec.

### 4. The failure mode flips sign across the ladder — within one decoder

Haiku ladder, probes_v3, exact 95% CIs:

| rung | n | confident-failure runs | abstention-only runs |
|---|---|---|---|
| W4 | 40 | **40 (1.00; CI ≥ 0.912)** | 0 (CI ≤ 0.088) |
| W3 | 26 | 0 | 3 (0.115) |
| W2 | 26 | 0 | 0 |
| W1 | 26 | 1 | 0 |
| W0 | 26 | 0 | 0 |

Stale-only windows produce **confident wrong-world reconstruction**;
metadata-poor current windows produce **honest abstention**; and with current
authority present, coherent stale evidence caused no detectable contamination
(1/26 vs 0/26). Which side of the boundary the decoder errs on depends on
*what kind* of evidence is missing, not how much.

The failure *texture* is model-dependent even where the mode is shared:
fable's W4 instances abstained partially (universally on Q5) and produced the
correct-outcome/wrong-basis Q4 signature (92%); haiku's abstained almost
never and got Q4's outcome outright wrong (37/40).

### 5. The manifest is referential, not authoritative

W3's failures are all Q4 abstentions: without the version manifest (or the
memo itself), "the 2025 exception" has no referent in the window — the
decoder cannot know whether v4's generic supersession clause covers it. The
manifest's contribution is not authority (v4's own text carries that) but
*reference*: it tells the decoder what exists to be superseded. This is a
sufficiency result invisible at n=1 and invisible to binary grading — and
the certification run showed it is *decoder-relative*: fable needs no such
referent (finding 6), haiku does.

### 6. Certification (fable, POWERED-V2): **W3 at 871 bytes**

Ordered W4→W0, n=150/rung, probes_v3 strict grading, Bonferroni L=5
(RELIABLE iff k≤18, UNRELIABLE iff k≥25), with exact verdict-preserving
curtailment. Certificate `f69b038561c7ba70`:

| rung | n effective | failures | verdict |
|---|---|---|---|
| W4 (541 B) | 30 of 150 | 30 | UNRELIABLE (curtailed: k≥25 already) |
| W3 (871 B) | 135 of 150 | **0** | **RELIABLE** (curtailed: k_final ≤ 15 ≤ 18) — selected |

W2/W1/W0 were not measured (declared truncation). Exact per-rung bounds at
the certified rung: false-certification ≤ 0.0069, false-rejection ≤ 0.169.
The in-flight grading was reproduced exactly by the reference grader over
the journal (W4 30/30, W3 0/135) — the preregistered cross-check passed.
Fable's W4 Q4 wrong-basis signature reached 30/30 at low reasoning effort.
Curtailment spent 165 instances where naive execution would have spent 750,
with identical verdicts.

The certified claim, precisely: for *this* decoder identity
(claude-fable-5, low effort), the 871-byte current-rules window suffices —
run-failure probability ≤ 0.10 at the protocol's operating
characteristics — and the 541-byte stale-only window is rejected. The
contract travels with the certificate: no promise inside the indifference
region (0.10, 0.20), and "certified" is meaningless without it.

**Sufficiency is decoder-relative.** Fable certified W3 with zero failures
— including zero Q4 abstentions — while haiku abstained on Q4 at W3
(3/26): fable resolves "the 2025 exception" from v4's generic supersession
clause alone; haiku needs the manifest's referent. Whether version
metadata is load-bearing is a property of the (window, decoder) pair, not
of the window.

## Method notes

- **Preregistration discipline.** Every family (smoke, powered, pilot, W4
  arm, powered-v2) committed its protocol, prompts, grading rules, and the
  executable measurement program (workflow script, by hash) before running.
  Superseded families are preserved, not rewritten; grading-rule changes
  spawn new families and re-grade old *raw answers* rather than old scores.
- **Rung blindness / oracle barrier.** Prompts are assembled mechanically
  from pack files only (oracle/ and probes excluded by predicate, not
  convention), byte-identical across rungs except window contents, delivered
  to fresh sessions that never learn a ladder exists.
- **Decoder identity.** Every measurement names provider, model, reasoning
  effort, and interface. Curves never merge across identities: fable and
  haiku results sit side by side and are never pooled.
- **A_DECODER_SEALED: ASSUMED_UNVERIFIED.** Decoder instances are
  *instructed*, not mechanically deprived, of external channels; recorded
  zero tool use is control evidence, not effect evidence. Discharging this
  requires an adapter exposing only prompt→generation.
- **Exact statistics end to end.** Clopper–Pearson intervals; integer
  cutoff-table classification with INDETERMINATE checked first; verdicts
  reachable only through preregistered tables; within-rung curtailment only
  where the verdict is identical under every completion of the rung.

## Formal statement of the sufficiency result

The substrate declared distortion decoder-relative — `D_Q(W; R_O, M_v)` —
as an architectural requirement. Task 04 produced the empirical case for the
model index: two decoder identities yield different adequacy boundaries over
the same window ladder. Sufficiency is therefore never a property of a
window alone:

    Sufficient(W | M, Q, T, P)

where `M` is the decoder identity (model, version, reasoning effort), `Q`
the probe set and grading instrument, `T` the task/world relation, and `P`
the measurement protocol. Dropping any index makes the claim unstatable —
the certificate does not even transfer across effort settings of the same
model.

Relatedly, W4 separates three questions the architecture must keep distinct,
because passing the first implies nothing about the other two:

1. Was the claim **grounded** in W? (W4 answers: yes, fluently.)
2. Was W **sufficient** for this decoder and task? (Decoder-relative.)
3. Was W **causally valid** with respect to the world version governing the
   decision? (W4's window was coherent and obsolete: grounded ≠ true.)

## Repository semantics: historical vs current state

`MILESTONE.json` is the *frozen CET-0 v1.1 substrate milestone*. Its
evidential-state text ("no real decoder has been run") was true at its
freeze date and is preserved byte-identical for provenance — `freeze.py`
and every committed protocol record verify against it. It must not be read
as a description of the current repository. The current evidential state
lives in `RESEARCH_STATE.json`, a separate content-addressed object that
supersedes the milestone's claims *as description* while leaving them
intact *as history*. Collapsing those two is the error class this
repository measures; the repository should not commit it about itself.

## What is and is not established

**Established (for the named decoder identities, this task, this probe set):**
the existence and within-decoder sign structure of the two failure modes;
the referential (not authoritative) role of version metadata; the
instrument-defect findings and their fixes.

**Not established:** transfer to any other decoder identity, task, or probe
set; contamination effects at effect sizes below what n≈26/rung can see;
that the basis token test captures reasoning (it captures cited grounding
only); anything inside the indifference region of the certification
protocol.
