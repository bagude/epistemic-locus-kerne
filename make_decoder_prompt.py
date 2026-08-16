"""
Decoder prompt generator.

Emits the exact text handed to a fresh decoder session, assembled ONLY from
pack files. No author-supplied prose about the task enters the prompt, because
whoever assembles the prompt may have seen evaluator-only material and prose is
where ground truth leaks without anyone noticing.

Three separation rules the generator enforces:

1. ORACLE BARRIER. No path matching an oracle marker may enter a prompt, and
   probes.json is excluded too -- it carries the expected answers, so it is
   evaluator-only despite living outside oracle/.

2. RUNG BLINDNESS. The prompt is byte-identical across rungs except for window
   contents. It never names the rung, never says a ladder exists, and never
   mentions that evidence sufficiency is being measured. A decoder told it is
   in an ablation study answers differently -- most obviously by over-using
   "insufficient" -- and that would be measured as distortion.

3. EXPLICIT PROBE BINDING. probes.json carries ids and expected values but no
   question text; the questions live as a numbered list inside task.md. Mapping
   Q1..Q5 to that list by position is inference. The binding must be declared
   in probe_questions.json and is verified here before a prompt is emitted.

Run:
  python3 make_decoder_prompt.py <pack_root> <task_id> <rung> [--out DIR]
  python3 make_decoder_prompt.py <pack_root> --all --out DIR
"""

from __future__ import annotations

import hashlib
import json
import os
import sys

ORACLE_MARKERS = ("oracle/", "ground_truth", "hidden_cases", "/oracle")
EVALUATOR_ONLY = ("probes/probes.json", "probe_questions.json")

PREAMBLE = (
    "You are given a task and a set of files. Answer the questions using only "
    "the files provided.\n"
    "If the provided files do not contain enough information to answer a "
    "question, answer exactly: INSUFFICIENT\n"
)

SCHEMA_INSTRUCTION = (
    "Respond with a single JSON object and nothing else. Use exactly these "
    "keys, with a string value for each:\n"
)


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def is_oracle(path: str) -> bool:
    p = path.replace("\\", "/")
    return any(m in p for m in ORACLE_MARKERS) or any(
        p.endswith(e) for e in EVALUATOR_ONLY)


def load_questions(task_dir: str, probe_ids: list[str]) -> dict:
    """probe_id -> question text. Must be declared, not inferred by position."""
    qp = os.path.join(task_dir, "probe_questions.json")
    if not os.path.exists(qp):
        raise SystemExit(
            f"MISSING BINDING: {qp}\n"
            f"  probes.json declares ids {probe_ids} but carries no question "
            f"text.\n"
            f"  The questions appear as a numbered list in task.md. Binding "
            f"them by position\n"
            f"  is inference, and a mis-binding silently scores the wrong "
            f"answer against the\n"
            f"  wrong expectation. Declare the mapping explicitly, e.g.\n"
            f'  {{"Q1": "First user-visible failure time", ...}}')
    q = json.load(open(qp))
    missing = [p for p in probe_ids if p not in q]
    extra = [k for k in q if k not in probe_ids]
    if missing or extra:
        raise SystemExit(f"BINDING MISMATCH: missing {missing}, extra {extra}")
    return q


def build_prompt(pack_root: str, task_id: str, rung: str,
                 ladder_file: str | None = None) -> dict:
    task_dir = os.path.join(pack_root, task_id)
    wdir = os.path.join(task_dir, "windows")
    lf = ladder_file or next(
        f for f in sorted(os.listdir(wdir))
        if isinstance(json.load(open(os.path.join(wdir, f))).get(rung), list))
    ladder = json.load(open(os.path.join(wdir, lf)))
    paths = ladder[rung]

    leaked = [p for p in paths if is_oracle(p)]
    if leaked:
        raise SystemExit(f"E_ORACLE_LEAK: {leaked} in {task_id}:{rung}")

    probes = json.load(open(os.path.join(task_dir, "probes", "probes.json")))
    ids = [p["id"] for p in probes["probes"]]
    questions = load_questions(task_dir, ids)

    parts = [PREAMBLE, "\n=== FILES ===\n"]
    file_hashes = {}
    for p in paths:
        full = os.path.join(task_dir, p)
        body = open(full, "rb").read()
        file_hashes[p] = sha(body)
        parts.append(f"\n--- {p} ---\n{body.decode('utf-8', 'replace')}\n")

    parts.append("\n=== QUESTIONS ===\n")
    for i in ids:
        parts.append(f"{i}: {questions[i]}\n")
    parts.append("\n" + SCHEMA_INSTRUCTION)
    parts.append(json.dumps({i: "<answer or INSUFFICIENT>" for i in ids},
                            indent=2) + "\n")

    text = "".join(parts)
    return {
        "task_id": task_id,
        "rung": rung,
        "ladder_file": lf,
        "file_hashes": file_hashes,
        "window_hash": sha(json.dumps(file_hashes, sort_keys=True).encode()),
        "rate_bytes": sum(os.path.getsize(os.path.join(task_dir, p))
                          for p in paths),
        "probe_set_hash": sha(json.dumps(probes["probes"],
                                         sort_keys=True).encode()),
        "prompt_hash": sha(text.encode()),
        "prompt": text,
    }


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    pack_root = sys.argv[1]
    out = None
    if "--out" in sys.argv:
        out = sys.argv[sys.argv.index("--out") + 1]
        os.makedirs(out, exist_ok=True)

    targets = []
    if "--all" in sys.argv:
        man = json.load(open(os.path.join(pack_root, "manifest.json")))
        for t in man["tasks"]:
            wdir = os.path.join(pack_root, t["task_id"], "windows")
            for fn in sorted(os.listdir(wdir)):
                lad = json.load(open(os.path.join(wdir, fn)))
                for rung, v in lad.items():
                    if isinstance(v, list):
                        targets.append((t["task_id"], rung, fn))
    else:
        targets.append((sys.argv[2], sys.argv[3], None))

    index = []
    for task_id, rung, lf in targets:
        try:
            rec = build_prompt(pack_root, task_id, rung, lf)
        except SystemExit as e:
            print(f"{task_id}:{rung}  {e}")
            continue
        index.append({k: v for k, v in rec.items() if k != "prompt"})
        print(f"{task_id}:{rung:<20} {rec['rate_bytes']:>6}B  "
              f"prompt {rec['prompt_hash'][:12]}  window {rec['window_hash'][:12]}")
        if out:
            fn = os.path.join(out, f"{task_id}__{rung}.txt")
            with open(fn, "w") as f:
                f.write(rec["prompt"])
    if out and index:
        with open(os.path.join(out, "prompt_index.json"), "w") as f:
            json.dump(index, f, indent=2, sort_keys=True)
        print(f"\n{len(index)} prompts + prompt_index.json -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
