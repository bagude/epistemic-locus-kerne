"""
Builds the Task-04 POWERED-V2 family: workflow_task04_powered_v2.js and its
preregistered protocol record. Run from repo root:

    python3 build_powered_v2.py

This is the confirmatory/certification run, superseding the never-executed
POWERED family (whose Q5 rule the pilot showed measures filename
convention). Changes, all justified by archived runs and frozen here:

  - grading is probes_v3: decision failure Y_j = 1[any probe not PASS]
    (strict -- an abstaining window cannot be certified sufficient), with
    the confabulation/abstention decomposition recorded descriptively
  - decision arm: ordered testing W4 -> W0 (rate-ascending), STOP at the
    first RELIABLE rung. The descriptive ladder above the selected rung is
    deliberately NOT measured, unlike exp004's synthetic run: the pilot
    estimated contamination (W1/W0 vs W2) as null for a real decoder, and
    the cost of completing the ladder in fable instances buys hypotheses
    the pilot already priced. Declared limitation: non-monotonicity above
    the selected rung is unobservable in this family.
  - within-rung curtailment: a rung stops as soon as its verdict is
    determined under every possible completion -- the classifier is a
    monotone step function of the final count k, and with c of n done and
    k failures observed, final k lies in [k, k+(n-c)]; if both endpoints
    classify identically the verdict is exact. This changes no operating
    characteristic (the decision is the same one the full-n table makes);
    it only skips instances that cannot change it. n_effective is
    recorded per rung.
  - decoder: session-configured claude-fable-5 (workflow inherit) at LOW
    reasoning effort, declared as this family's decoder identity.

Statistics are unchanged from the POWERED family: n=150/rung,
alpha_good=0.10, alpha_bad=0.20, Bonferroni over L=5 (conf/rung 0.99),
RELIABLE k<=18, UNRELIABLE k>=25, indeterminate 19..24, power 0.831.
"""

import hashlib
import json
import os

from harness.core import _sha, _canon
from harness.reliability import cutoff_table, power_analysis, n_recommended
from taskpack import verify_pack
from make_decoder_prompt_v2 import build_prompt

N = 150
BATCH = 15
RUNGS = ["W4", "W3", "W2", "W1", "W0"]
ALPHA_GOOD, ALPHA_BAD, FAMILYWISE, TARGET_POWER = 0.10, 0.20, 0.05, 0.80
CONF = 1 - FAMILYWISE / len(RUNGS)
PROMPT_DIR = "results/task04_powered_n150/prompts"
OUT = "results/task04_powered_v2"

WRAPPER = ("You will be given a self-contained task below. Do not use any "
           "tools, do not read any files, do not run any commands — answer "
           "using only the text below. Output exactly what the task requests "
           "and nothing else.\n\n")

table = cutoff_table(N, ALPHA_GOOD, ALPHA_BAD, CONF)
pa = power_analysis(N, ALPHA_GOOD, ALPHA_BAD, CONF)
n_min = n_recommended(ALPHA_GOOD, ALPHA_BAD, TARGET_POWER, CONF)
assert N >= n_min and pa["power_at_alpha_good"] >= TARGET_POWER
assert not table["regions_overlap"]

prompts = {r: WRAPPER + open(f"{PROMPT_DIR}/task_04_policy_validity__{r}.txt").read()
           for r in RUNGS}
probes_v3 = json.load(open(
    "CET_REAL_TASKS_v1/task_04_policy_validity/probes/probes_v3.json"))
TYPES = {"Q1": "bool", "Q2": "list", "Q3": "number", "Q4": "bool",
         "Q5": "q5"}
probes_js = [
    {"id": p["id"], "type": TYPES[p["id"]],
     "expected": ([t.lower() for t in p["expected_outcome"]]
                  if isinstance(p["expected_outcome"], list)
                  else p["expected_outcome"]),
     "basis": [t.lower() for t in p["required_basis_tokens"]]}
    for p in probes_v3["probes"]
]

script = f"""export const meta = {{
  name: 'task04-powered-v2',
  description: 'Task 04 certification run: ordered W4->W0, n=150/rung, fable low-effort, probes_v3 strict grading, exact curtailment',
  phases: [{{ title: 'W4' }}, {{ title: 'W3' }}, {{ title: 'W2' }}, {{ title: 'W1' }}, {{ title: 'W0' }}],
}}

const N = {N}, BATCH = {BATCH}
const REL_MAX = {table["reliable_max_failures"]}, UNREL_MIN = {table["unreliable_min_failures"]}
const RUNGS = {json.dumps(RUNGS)}
const PROMPTS = {json.dumps(prompts, sort_keys=True)}
const PROBES = {json.dumps(probes_js)}

const QCELL = {{ type: 'object', properties: {{ answer: {{ type: 'string' }}, basis: {{ type: 'string' }} }}, required: ['answer', 'basis'], additionalProperties: false }}
const SCHEMA = {{ type: 'object', properties: {{ Q1: QCELL, Q2: QCELL, Q3: QCELL, Q4: QCELL, Q5: QCELL }}, required: ['Q1', 'Q2', 'Q3', 'Q4', 'Q5'], additionalProperties: false }}

// Line-for-line port of grade_task04_v3.py; cross-checked against the
// reference grader over the journal after the run (mismatch voids the run).
function norm(s) {{ return String(s || '').trim().toLowerCase() }}
function outcomeOf(p, ans, basis) {{
  const a = norm(ans)
  if (a.startsWith('insufficient')) return 'ABSTAINED'
  if (p.type === 'q5') {{
    if (a.includes('v4') || (a.includes('current policy') && norm(basis).includes('v4'))) return 'CORRECT'
    return 'WRONG'
  }}
  if (p.type === 'bool') {{
    const head = a.split(/[.,;:\\s]/, 1)[0]
    if (head === 'no' || head === 'false' || head === 'not') return p.expected === false ? 'CORRECT' : 'WRONG'
    if (head === 'yes' || head === 'true') return p.expected === true ? 'CORRECT' : 'WRONG'
    return 'WRONG'
  }}
  if (p.type === 'number') {{
    const m = a.match(/-?\\d+(\\.\\d+)?/)
    return (m && parseFloat(m[0]) === p.expected) ? 'CORRECT' : 'WRONG'
  }}
  if (p.type === 'list') return p.expected.every(t => a.includes(t)) ? 'CORRECT' : 'WRONG'
  return a.includes(norm(p.expected)) ? 'CORRECT' : 'WRONG'
}}
function gradeInstance(ans) {{
  let conf = 0, abst = 0
  for (const p of PROBES) {{
    const cell = ans[p.id] || {{}}
    const out = outcomeOf(p, cell.answer, cell.basis)
    if (out === 'ABSTAINED') {{ abst++; continue }}
    const bc = p.basis.some(t => norm(cell.basis).includes(t))
    if (!(out === 'CORRECT' && bc)) conf++
  }}
  return {{ decisionFail: (conf + abst) > 0, confFail: conf > 0,
            abstOnly: abst > 0 && conf === 0 }}
}}
function regionOf(k) {{ return k <= REL_MAX ? 'RELIABLE' : (k >= UNREL_MIN ? 'UNRELIABLE' : 'INDETERMINATE') }}

const results = []
let selected = null
for (const rung of RUNGS) {{
  let k = 0, confRuns = 0, abstRuns = 0, c = 0, curtailed = false
  for (let b = 0; b < N && !curtailed; b += BATCH) {{
    const res = await parallel(Array.from({{ length: Math.min(BATCH, N - b) }}, (_, i) => () =>
      agent(PROMPTS[rung], {{ label: rung + '#' + (b + i), phase: rung,
                              schema: SCHEMA, effort: 'low' }})))
    for (const ans of res) {{
      if (!ans) continue
      c++
      const g = gradeInstance(ans)
      if (g.decisionFail) k++
      if (g.confFail) confRuns++
      if (g.abstOnly) abstRuns++
    }}
    // exact curtailment: final k is in [k, k + (N - c)]
    if (regionOf(k) === regionOf(k + (N - c))) curtailed = (c < N)
    log(rung + ': ' + k + ' fails in ' + c + (curtailed ? ' -- verdict determined, curtailing' : ''))
    if (curtailed) break
  }}
  const verdict = regionOf(k)   // exact: identical for every completion iff curtailed
  results.push({{ rung, n_planned: N, n_effective: c, failures: k,
                  confident_failure_runs: confRuns, abstention_only_runs: abstRuns,
                  verdict, curtailed }})
  log(rung + ' verdict: ' + verdict + ' (k=' + k + ', n_eff=' + c + ')')
  if (verdict === 'RELIABLE') {{ selected = rung; break }}
}}

return {{ results, selected }}
"""

with open("workflow_task04_powered_v2.js", "w") as f:
    f.write(script)


def fsha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


ok, bad, pack_hash = verify_pack("CET_REAL_TASKS_v1")
assert ok, bad
prompt_index = []
for r in RUNGS:
    rec = build_prompt("CET_REAL_TASKS_v1", "task_04_policy_validity", r)
    prompt_index.append({k: v for k, v in rec.items() if k != "prompt"})

proto = {
    "experiment_family": "CET0-REALTASK-004-POWERED-V2",
    "protocol_version": 1,
    "frozen": True,
    "supersedes": "CET0-REALTASK-004-POWERED (8a8598bd272982eb, never "
                  "executed beyond the archived W4 partial): its Q5 rule "
                  "measures filename convention (pilot finding, summary "
                  "d0d9fb23126ccfb0)",
    "substrate_hash": json.load(open("MILESTONE.json"))["substrate_hash"],
    "pack_hash": pack_hash,
    "task_id": "task_04_policy_validity",
    "grading": {
        "instrument": "probes_v3 three-valued",
        "probes_v3_hash": _sha(_canon(probes_v3)),
        "decision_failure": "Y_j = 1[any probe not PASS] -- strict: "
                            "abstention blocks certification",
        "descriptive_decomposition": "confident-failure runs vs "
                                     "abstention-only runs, per rung",
        "reference_grader_sha256": fsha("grade_task04_v3.py"),
    },
    "alpha_good": ALPHA_GOOD, "alpha_bad": ALPHA_BAD,
    "indifference_region": [ALPHA_GOOD, ALPHA_BAD],
    "familywise_error_budget": FAMILYWISE,
    "multiple_comparison_rule": f"Bonferroni over L={len(RUNGS)} rungs",
    "per_rung_confidence": round(CONF, 6),
    "n_per_rung": N, "n_min_adequate": n_min,
    "power_at_alpha_good": round(pa["power_at_alpha_good"], 5),
    "false_cert_at_alpha_bad": round(pa["false_cert_at_alpha_bad"], 5),
    "cutoff_table": table,
    "decision_arm": {
        "rung_order": "rate-ascending W4,W3,W2,W1,W0",
        "stop_rule": "stop at first RELIABLE; rungs above the selected one "
                     "are NOT measured (declared truncation; pilot priced "
                     "contamination as null for a real decoder)",
        "within_rung_curtailment": "stop when the verdict is identical for "
                                   "every possible completion of the rung "
                                   "(final k bounded in [k, k+(N-c)]); "
                                   "exact, changes no operating "
                                   "characteristic; n_effective recorded",
    },
    "decoder_identity_declared": {
        "provider": "anthropic",
        "name": "claude-fable-5",
        "version_or_snapshot": "session-configured claude-fable-5 "
                               "(workflow model inherit)",
        "tokenizer_if_used": None,
        "reasoning_effort": "low",
        "interface": "fresh rung-blind workflow subagent per instance, "
                     "byte-identical Smoke-v1 wrapper, schema-enforced "
                     "structured output",
        "sealing": "A_DECODER_SEALED: ASSUMED_UNVERIFIED",
    },
    "prompts": "byte-identical to pilot/powered families",
    "ladder_rungs": prompt_index,
    "batching": {"batch_size": BATCH, "order": "sequential within rung "
                 "(ordered testing requires completing a rung's verdict "
                 "before the next rung starts)"},
    "measurement_program": {
        "workflow_script": "workflow_task04_powered_v2.js",
        "workflow_script_sha256": fsha("workflow_task04_powered_v2.js"),
        "builder_sha256": fsha("build_powered_v2.py"),
        "cross_check": "grade_task04_v3.py re-applied to journal raw "
                       "answers must reproduce the in-flight counts "
                       "exactly; disagreement voids the run",
    },
    "limitations": [
        "no promise inside the indifference region",
        "decoder-relative: scoped to claude-fable-5 at low reasoning "
        "effort; merges with no other identity, including this model at "
        "other effort settings",
        "descriptive ladder truncated above the selected rung by design",
        "basis grading remains a token-level proxy for cited grounding",
        "a RELIABLE verdict means the count fell in the preregistered "
        "acceptance region, not P(p<=alpha_good|data)",
    ],
}
proto["protocol_hash"] = _sha(_canon(proto))
os.makedirs(OUT, exist_ok=True)
with open(f"{OUT}/protocol_powered_v2.json", "w") as f:
    json.dump(proto, f, indent=2, sort_keys=True)
print(f"protocol {proto['protocol_hash'][:16]} -> {OUT}/protocol_powered_v2.json")
print(f"  table: RELIABLE k<={table['reliable_max_failures']}, "
      f"UNRELIABLE k>={table['unreliable_min_failures']}, n={N}, "
      f"power {pa['power_at_alpha_good']:.3f}")
