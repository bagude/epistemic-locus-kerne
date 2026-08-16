"""
Decoder prompt generator, schema v2: outcome + basis.

Identical to make_decoder_prompt.py in every separation rule -- oracle
barrier, rung blindness, explicit probe binding -- with one schema change
motivated by Task04 Smoke v1: the decoder must state, per question, the
basis its answer relies on. Smoke v1's W4 Q4 produced a correct surface
answer from a wrong causal structure, invisible to outcome-only grading;
basis-aware grading requires the basis to exist as a first-class field in
the response, not be inferred from answer prose.

The basis request is generic and byte-identical across rungs: it never
names any artifact, never hints which grounding is expected, and applies
uniformly to every question, so rung blindness is preserved.

Run:
  python3 make_decoder_prompt_v2.py <pack_root> <task_id> <rung> [--out DIR]
"""

from __future__ import annotations

import hashlib
import json
import os
import sys

ORACLE_MARKERS = ("oracle/", "ground_truth", "hidden_cases", "/oracle")
EVALUATOR_ONLY = ("probes/probes.json", "probes/probes_v2.json",
                  "probe_questions.json")

PREAMBLE = (
    "You are given a task and a set of files. Answer the questions using only "
    "the files provided.\n"
    "If the provided files do not contain enough information to answer a "
    "question, answer exactly: INSUFFICIENT\n"
)

SCHEMA_INSTRUCTION = (
    "Respond with a single JSON object and nothing else. For each question "
    "give an object with two string fields: \"answer\" (the answer, or "
    "INSUFFICIENT) and \"basis\" (name or quote the specific provision or "
    "file among those provided that your answer relies on, or INSUFFICIENT). "
    "Use exactly these keys:\n"
)


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def is_oracle(path: str) -> bool:
    p = path.replace("\\", "/")
    return any(m in p for m in ORACLE_MARKERS) or any(
        p.endswith(e) for e in EVALUATOR_ONLY)


def load_questions(task_dir: str, probe_ids: list[str]) -> dict:
    qp = os.path.join(task_dir, "probe_questions.json")
    if not os.path.exists(qp):
        raise SystemExit(f"MISSING BINDING: {qp}")
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
    parts.append(json.dumps(
        {i: {"answer": "<answer or INSUFFICIENT>",
             "basis": "<provision or file relied on, or INSUFFICIENT>"}
         for i in ids}, indent=2) + "\n")

    text = "".join(parts)
    return {
        "task_id": task_id,
        "rung": rung,
        "ladder_file": lf,
        "schema_version": 2,
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
    if len(sys.argv) < 4:
        print(__doc__)
        return 2
    pack_root, task_id, rung = sys.argv[1], sys.argv[2], sys.argv[3]
    out = None
    if "--out" in sys.argv:
        out = sys.argv[sys.argv.index("--out") + 1]
        os.makedirs(out, exist_ok=True)
    rec = build_prompt(pack_root, task_id, rung)
    print(f"{task_id}:{rung:<6} {rec['rate_bytes']:>6}B  "
          f"prompt {rec['prompt_hash'][:12]}  window {rec['window_hash'][:12]}")
    if out:
        with open(os.path.join(out, f"{task_id}__{rung}.txt"), "w") as f:
            f.write(rec["prompt"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
