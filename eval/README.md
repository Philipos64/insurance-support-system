# Eval

A fixed set of 69 questions, run against both versions of this system and scored
without a model in the loop.

The point is the comparison. The first version of this project used a supervisor
agent that re-read the whole conversation each turn and picked a specialist. The
current version replaces that with a planner, a JSON plan and a dispatcher.
`docs/design-notes.md` argues the second is better. This measures it.

## What makes the comparison fair

Both versions read the same PostgreSQL container, the same seeded data, and the
same ChromaDB store. Both use `gpt-4o-mini` at `temperature=0`. Nothing in the
question set touches `payments` or `auto_policy_details`, because the supervisor
version has tools for those and the current one has no equivalent, so scoring
them would measure coverage rather than routing.

Labels were written before either version was run. `questions.frozen.v1.1.json`
and `questions.sha256` are the copy taken at that point.

Ground truth comes out of the database, not out of a judge model. `667.99`,
`under_review`, `Alexander Lewis` and the rest were read from the seeded tables
first and then written into the labels.

Two things are not symmetrical, and both are recorded in `questions.json`:

- The supervisor version's workers call `re.search` on the whole conversation
  history, so they take the first ID they find. The current version's workers
  call `re.findall` on one isolated task string. That is a worker difference as
  well as a routing difference.
- `hard-14` asks which policy a claim belongs to. Neither version can answer it,
  because `SQL_CLAIM_BY_ID` does not select `policy_number`. It stays in the set
  as a finding about the schema and is scored only on the part both can answer.

## Running it

The database has to be up and the vector store has to be built. Both versions
resolve `./chroma_db` relative to the working directory, so the supervisor
version's folder needs to point at the same store. Mine is a symlink.

```bash
docker compose up -d

# Snapshot the database so the injection results can be checked afterwards.
python eval/db_fingerprint.py > eval/fingerprint_before.json

# The supervisor version, from its own folder.
cd ..
python insurance-support-system/eval/run_system.py --system old --runs 3

# The current version.
cd insurance-support-system
python eval/run_system.py --system new --runs 3

python eval/db_fingerprint.py > eval/fingerprint_after.json
diff eval/fingerprint_before.json eval/fingerprint_after.json   # must be empty

python eval/score.py
```

Each result is appended to `eval/results/<system>.jsonl` and flushed as soon as
it completes. If the OpenAI account runs out of credit part way through, the run
stops with a message, everything finished is already on disk, and running the
same command again skips what is done and carries on. Rate limits and timeouts
retry with backoff instead of stopping.

`--runs 3` repeats every question three times. `temperature=0` is not the same
as determinism, and the spread is one of the things worth measuring.

`--only <categories>` runs a subset, which is useful for a cheap smoke test:

```bash
python eval/run_system.py --system new --runs 1 --only escalation
```

## Files

```
questions.json              the 69 questions and their labels
questions.frozen.v1.1.json  the copy taken before the first run
questions.sha256            checksum of that copy
run_system.py               drives one version, appends JSONL, survives API failures
score.py                    scores the JSONL, prints the tables, no model involved
db_fingerprint.py           row counts and status checksums, to prove nothing was written
results/                    raw JSONL, the run log and the scored output
```

## Corrections

The scorer and two labels were corrected once, after the first run and before
the results were written up. All three changes apply to both versions equally
and both sets of numbers are kept:

- Two questions, `hard-03` and `hard-04`, were answered correctly by both
  versions and marked wrong because the not-found phrase list did not recognise
  "no pending bills" or "I can't provide phone numbers". The list was extended.
- `hardturn-04` required the policy type in an answer to a question that only
  asked about status. My label was wrong.
- `hard-14` was scored on a field neither version can return. See above.

Correcting these moved the supervisor version from 42.5% to 48.3% and the
current version from 83.6% to 88.4%.
