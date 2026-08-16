"""
Builds workflow_task04_powered.js -- the executable measurement program for
the Task-04 powered family. Run from repo root:

    python3 build_workflow_task04.py

The generated script is a preregistration artifact: its sha256 goes into the
protocol record BEFORE any decoder runs, so the exact fan-out, prompts,
schema, and in-flight grading rules are committed ahead of measurement. The
in-flight JS grader is a line-for-line port of grade_task04_v2.py; after the
run, the reference grader is re-applied to the raw answers in the workflow
journal and the two gradings must agree exactly (a mismatch voids the run).
"""

import hashlib
import json

N = 150
RUNGS = ["W4", "W3", "W2", "W1", "W0"]   # rate-ascending: ordered testing
PROMPT_DIR = "results/task04_powered_n150/prompts"

# Byte-identical wrapper, unchanged from Task04 Smoke v1.
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
  name: 'task04-powered-ladder',
  description: 'Task 04 powered run: 5 rungs x n=150 fresh rung-blind decoder instances, outcome+basis grading',
  phases: [{{ title: 'W4' }}, {{ title: 'W3' }}, {{ title: 'W2' }}, {{ title: 'W1' }}, {{ title: 'W0' }}],
}}

const N = {N}
const RUNGS = {json.dumps(RUNGS)}
const PROMPTS = {json.dumps(prompts, sort_keys=True)}
const PROBES = {json.dumps(probes_js)}

const QCELL = {{ type: 'object',
  properties: {{ answer: {{ type: 'string' }}, basis: {{ type: 'string' }} }},
  required: ['answer', 'basis'], additionalProperties: false }}
const SCHEMA = {{ type: 'object',
  properties: {{ Q1: QCELL, Q2: QCELL, Q3: QCELL, Q4: QCELL, Q5: QCELL }},
  required: ['Q1', 'Q2', 'Q3', 'Q4', 'Q5'], additionalProperties: false }}

// Line-for-line port of grade_task04_v2.py. Verified against the reference
// grader over the journal after the run; disagreement voids the run.
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

function summarize(rung, instances) {{
  const done = instances.filter(Boolean)
  let runFail = 0, outcomeOnlyFail = 0, basisAloneFail = 0
  const failing = []
  for (const {{ j, ans }} of done) {{
    const failed = [], ofail = [], bonly = []
    for (const p of PROBES) {{
      const cell = ans[p.id] || {{}}
      const oc = outcomeCorrect(p, cell.answer)
      const bc = basisCorrect(p, cell.basis)
      if (!(oc && bc)) failed.push(p.id + (oc ? ':b' : ':o'))
      if (!oc) ofail.push(p.id)
      if (oc && !bc) bonly.push(p.id)
    }}
    if (failed.length) runFail++
    if (ofail.length) outcomeOnlyFail++
    if (failed.length && !ofail.length) basisAloneFail++
    if (failed.length) failing.push(j + ':' + failed.join(','))
  }}
  return {{
    rung, n_requested: N, n_completed: done.length,
    n_missing: N - done.length,
    run_failures: runFail,
    run_failures_under_outcome_only_grading: outcomeOnlyFail,
    runs_failing_on_basis_alone: basisAloneFail,
    failing_instances: failing,
  }}
}}

const results = await parallel(RUNGS.map(rung => () =>
  parallel(Array.from({{ length: N }}, (_, j) => () =>
    agent(PROMPTS[rung], {{ label: rung + '#' + j, phase: rung,
                            schema: SCHEMA, effort: 'low' }})
      .then(ans => ({{ j, ans }}))
  )).then(instances => {{
    const s = summarize(rung, instances)
    log(rung + ': ' + s.run_failures + '/' + s.n_completed + ' run failures'
        + (s.n_missing ? ' (' + s.n_missing + ' missing)' : ''))
    return s
  }})
))

return {{ results }}
"""

with open("workflow_task04_powered.js", "w") as f:
    f.write(script)
h = hashlib.sha256(script.encode()).hexdigest()
print(f"workflow_task04_powered.js written, sha256 {h}")
