"""
Builds workflow_task04_pilot.js -- measurement program for the Task-04 PILOT
family (estimation-only). Run from repo root:

    python3 build_workflow_task04_pilot.py

Differences from the powered program, all preregistered:
  - rungs W3,W2,W1,W0 at n=40 each (W4's estimate is carried from the
    archived aborted-run data; no further W4 sampling)
  - decoder is the small model ('haiku' -> claude-haiku-4-5) at low
    reasoning effort, to minimize tokens; this is a DIFFERENT decoder
    identity and its curve does not merge with any fable measurement
  - instances run in sequential batches of 10, ROUND-ROBIN across rungs
    (W3#j, W2#j, W1#j, W0#j, W3#j+1, ...), so truncation at any batch
    boundary leaves near-balanced per-rung counts -- the aborted powered
    run showed FIFO draining concentrates truncation on one rung
  - no verdicts: the run reports counts only; intervals and comparisons
    are computed by the reference analysis, not in-flight

Prompts are byte-identical to the powered family's committed prompts
(results/task04_powered_n150/prompts), so the two families differ only in
decoder identity and statistical purpose. The in-flight JS grader is the
same line-for-line port of grade_task04_v2.py; the journal cross-check
applies unchanged.
"""

import hashlib
import json

N = 40
BATCH = 10
RUNGS = ["W3", "W2", "W1", "W0"]
PROMPT_DIR = "results/task04_powered_n150/prompts"

WRAPPER = ("You will be given a self-contained task below. Do not use any "
           "tools, do not read any files, do not run any commands — answer "
           "using only the text below. Output exactly what the task requests "
           "and nothing else.\n\n")

prompts = {}
for r in RUNGS:
    with open(f"{PROMPT_DIR}/task_04_policy_validity__{r}.txt") as f:
        prompts[r] = WRAPPER + f.read()

probes_v2 = json.load(open(
    "CET_REAL_TASKS_v1/task_04_policy_validity/probes/probes_v2.json"))
TYPES = {"Q1": "bool", "Q2": "list", "Q3": "number", "Q4": "bool",
         "Q5": "string"}
probes_js = [
    {"id": p["id"], "type": TYPES[p["id"]],
     "expected": ([t.lower() for t in p["expected_outcome"]]
                  if isinstance(p["expected_outcome"], list)
                  else p["expected_outcome"]),
     "basis": [t.lower() for t in p["required_basis_tokens"]]}
    for p in probes_v2["probes"]
]

script = f"""export const meta = {{
  name: 'task04-pilot-ladder',
  description: 'Task 04 pilot (estimation-only): W3,W2,W1,W0 x n=40, haiku decoder, batches of 10 round-robin',
  phases: [{{ title: 'W3' }}, {{ title: 'W2' }}, {{ title: 'W1' }}, {{ title: 'W0' }}],
}}

const N = {N}
const BATCH = {BATCH}
const RUNGS = {json.dumps(RUNGS)}
const PROMPTS = {json.dumps(prompts, sort_keys=True)}
const PROBES = {json.dumps(probes_js)}

const QCELL = {{ type: 'object',
  properties: {{ answer: {{ type: 'string' }}, basis: {{ type: 'string' }} }},
  required: ['answer', 'basis'], additionalProperties: false }}
const SCHEMA = {{ type: 'object',
  properties: {{ Q1: QCELL, Q2: QCELL, Q3: QCELL, Q4: QCELL, Q5: QCELL }},
  required: ['Q1', 'Q2', 'Q3', 'Q4', 'Q5'], additionalProperties: false }}

// Line-for-line port of grade_task04_v2.py (unchanged from powered family).
function norm(s) {{ return String(s || '').trim().toLowerCase() }}
function outcomeCorrect(p, ans) {{
  const a = norm(ans)
  if (p.type === 'bool') {{
    if (a.startsWith('insufficient')) return false
    const head = a.split(/[.,;:\\s]/, 1)[0]
    if (head === 'no' || head === 'false' || head === 'not') return p.expected === false
    if (head === 'yes' || head === 'true') return p.expected === true
    return false
  }}
  if (p.type === 'number') {{
    const m = a.match(/-?\\d+(\\.\\d+)?/)
    return !!m && parseFloat(m[0]) === p.expected
  }}
  if (p.type === 'list') return !a.startsWith('insufficient') && p.expected.every(t => a.includes(t))
  return a.includes(norm(p.expected))
}}
function basisCorrect(p, basis) {{
  const b = norm(basis)
  return p.basis.some(t => b.includes(t))
}}

function gradeInstance(ans) {{
  const failed = [], ofail = [], bonly = []
  for (const p of PROBES) {{
    const cell = ans[p.id] || {{}}
    const oc = outcomeCorrect(p, cell.answer)
    const bc = basisCorrect(p, cell.basis)
    if (!(oc && bc)) failed.push(p.id + (oc ? ':b' : ':o'))
    if (!oc) ofail.push(p.id)
    if (oc && !bc) bonly.push(p.id)
  }}
  return {{ failed, ofail, bonly }}
}}

// Round-robin order: truncation at any batch boundary stays near-balanced.
const order = []
for (let j = 0; j < N; j++) for (const rung of RUNGS) order.push({{ rung, j }})

const done = []
for (let b = 0; b < order.length; b += BATCH) {{
  const batch = order.slice(b, b + BATCH)
  const res = await parallel(batch.map(({{ rung, j }}) => () =>
    agent(PROMPTS[rung], {{ label: rung + '#' + j, phase: rung,
                            schema: SCHEMA, model: 'haiku', effort: 'low' }})
      .then(ans => ({{ rung, j, ans }}))))
  done.push(...res.filter(Boolean))
  log('batch ' + (Math.floor(b / BATCH) + 1) + '/' + Math.ceil(order.length / BATCH)
      + ' done, ' + done.length + '/' + order.length + ' instances')
}}

const results = RUNGS.map(rung => {{
  const inst = done.filter(d => d.rung === rung)
  let runFail = 0, outcomeOnlyFail = 0, basisAloneFail = 0
  const failing = []
  for (const {{ j, ans }} of inst) {{
    const g = gradeInstance(ans)
    if (g.failed.length) runFail++
    if (g.ofail.length) outcomeOnlyFail++
    if (g.failed.length && !g.ofail.length) basisAloneFail++
    if (g.failed.length) failing.push(j + ':' + g.failed.join(','))
  }}
  return {{
    rung, n_requested: N, n_completed: inst.length,
    n_missing: N - inst.length,
    run_failures: runFail,
    run_failures_under_outcome_only_grading: outcomeOnlyFail,
    runs_failing_on_basis_alone: basisAloneFail,
    failing_instances: failing,
  }}
}})

return {{ results }}
"""

with open("workflow_task04_pilot.js", "w") as f:
    f.write(script)
h = hashlib.sha256(script.encode()).hexdigest()
print(f"workflow_task04_pilot.js written, sha256 {h}")
