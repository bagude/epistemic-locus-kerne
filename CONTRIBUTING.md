# Change control

The substrate is frozen at `CET-0 Experimental Substrate v1.1`
(`c871cc8e2994639c`). Verify with:

    python3 freeze.py

## Frozen (11 files, listed in MILESTONE.json)

`harness/`, `adversarial.py`, `audit_topology.py`, `run_experiment.py`,
`experiment_002_window_rd.py`, `experiment_003_protocol_calibration.py`,
`experiment_004_frontier.py`, `README.md`.

Until Experiment 004 has run against a real decoder, do not change eps,
alpha_good, alpha_bad, n, the probe set, the ladder, rung ordering, the cutoff
table, the selection rule, or the family-wise rule. Any such change produces a
new `protocol_hash` and starts a new experiment family; it does not extend this
one. Editing a frozen file and re-running `freeze.py --write` without recording
a supersession destroys the provenance chain.

## Not frozen -- the permitted variable

`taskpack.py` and `make_decoder_prompt.py` are the decoder-side adapter, added
after v1.1. They may change freely. They are deliberately absent from
`MILESTONE.json` so `freeze.py` still reports VERIFIED while they evolve.

## Open blockers before a valid measurement

1. `E_PROBE_COUNT_MISMATCH` -- real tasks have k=5 (task 5: k=8); the frozen
   protocol assumes k=20. At k=5, eps=0.05 means zero probe failures allowed.
   Declare a new eps by rule (granularity 1/k, so eps=0.2 tolerates one
   failure) BEFORE any pilot, and fork the protocol family.
2. `E_PROBE_NOT_GRADABLE` -- most probes need a judge, which is an unmodeled
   decoder inside D_Q. Task 04 is the exception: all five are exact-match.
3. `probe_questions.json` -- must be authored per task by someone who has not
   read that task's oracle. The task_04 draft in this repo was written by a
   contaminated author and needs review.
4. Decoder contamination -- `gate_decoder()` treats a missing attestation as
   contamination, because contamination leaves no trace in decoder output.
