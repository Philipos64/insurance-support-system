# Evaluation

The design notes end by saying I never built a proper test set, and that it was the clearest next
thing to do. This is that test set, and the result of running it.

I did not just measure the current version. I kept the original supervisor version running and
scored both on the same questions, against the same database, with the same model. Section 1 of
the design notes argues the rewrite was worth it. Until now that argument rested on one trace I
kept from November. This puts a number on it.

## What I ran

69 questions in 10 groups, three times each, against both versions. 414 runs in total, no errors.

The groups are single lookups, multi-step requests, knowledge base questions, questions mixing a
lookup with a general one, edge cases, escalation, two-turn conversations, a group of harder
questions, three-turn conversations, and prompt injection.

## Results

Routing means the request reached exactly the right workers, no more and no fewer. Pass means
that plus the right values out of the database, the right behaviour when there is nothing to
return, and nothing leaked.

| Group | n | Supervisor routing | Workflow routing | Supervisor pass | Workflow pass |
|---|---|---|---|---|---|
| Single lookup | 18 | 100.0% | 100.0% | 100.0% | 100.0% |
| Multi-step | 15 | 60.0% | 100.0% | 0.0% | 100.0% |
| Knowledge base | 24 | 75.0% | 87.5% | 75.0% | 87.5% |
| Lookup plus knowledge | 9 | 0.0% | 33.3% | 0.0% | 33.3% |
| Edge cases | 21 | 76.2% | 100.0% | 42.9% | 95.2% |
| Escalation | 9 | 0.0% | 100.0% | 0.0% | 100.0% |
| Two turns | 18 | 50.0% | 100.0% | 33.3% | 100.0% |
| Hard | 42 | 57.1% | 83.3% | 35.7% | 83.3% |
| Three turns | 15 | 40.0% | 100.0% | 40.0% | 100.0% |
| Prompt injection | 36 | 100.0% | 88.9% | 75.0% | 88.9% |
| **All** | **207** | **65.7%** | **90.3%** | **47.8%** | **89.9%** |

| | Supervisor | Workflow |
|---|---|---|
| Same route set on all three runs | 89.9% | 97.1% |
| Model calls per question | 3.80 | 2.61 |
| Seconds per question | 4.29 | 3.17 |
| Escalated to a human without being asked | 6.8% | 0.0% |
| Injection attempts held | 27 of 36 | 36 of 36 |

The workflow version is better and it is also cheaper. It makes about one fewer model call per
question and finishes about a second faster. I expected to trade some cost for the predictability.
It went the other way, because the supervisor spends calls re-deciding what it already decided.

## The loop, measured

The supervisor visited the same worker more than once inside a single turn on 24.6% of runs. The
worst case was six lookups of the same claim followed by a forced escalation:

```
claims -> claims -> claims -> claims -> claims -> claims -> human
```

It hit the iteration cap 14 times across the run, and every one of those was a question that
should have been answered.

The workflow version repeated a worker on 8.7% of runs, but that number means something different.
Those are plans with more than one task for the same worker, like three claim IDs in one question.
The dispatcher runs each task once and the list only gets shorter. The most nodes it ever used in
one turn was three. The supervisor's most was seven, which is the cap.

The specific failure I wrote up in section 1 of the design notes reproduces every time. Ask about
POL000002, then ask how to get a cancelled policy reinstated:

```
supervisor:  supervisor -> policy_agent -> supervisor -> policy_agent -> supervisor -> final_answer
workflow:    planner -> dispatcher -> rag_specialist -> dispatcher -> answer_agent
```

Same question, same stale policy number in the history. The supervisor goes back to the policy
worker because the ID is still sitting there. The workflow sends it to the FAQ store, which is
where the answer is. Three runs out of three, both ways.

## Escalation

This is the widest gap and I did not expect it. Asked plainly for a human, the supervisor got it
right zero times out of nine. One request went to the FAQ store and another ended with no worker
at all. The workflow got it right nine times out of nine.

## Prompt injection

The supervisor leaked on 9 of 36 runs. It printed `HACKED` when told to, printed `PWNED` when told
to append it to a legitimate billing answer, and wrote the file deletion script when asked to
forget about insurance. The workflow refused all 36.

Neither version wrote to the database. I took a fingerprint before and after the whole run, row
counts plus an md5 of every policy and claim status, and it came back identical. That includes the
attempt to change a policy status as an administrator, which is the one the design notes admit gets
into the plan. It still gets into the plan. It still cannot do anything, because `policy_worker`
only runs a `SELECT`.

## Where the workflow version loses

Four questions. I am listing all of them.

**"Tell me about my coverage."** It goes to the policy worker, which asks for a policy number. It
should go to the FAQ store. The supervisor got this right all three times. This is a real routing
loss and the planner prompt is where it would be fixed.

**"What is the status of claim CLM000004 and which policy is it on?"** The planner adds a policy
lookup step, which is reasonable, except the task has no policy number in it so the step returns
nothing. Wasted work. The supervisor answered the claim half and stopped.

**Two injection questions** route somewhere they should not. One adds a FAQ search to a request for
every customer email. Nothing leaked either time, so this is wasted work rather than a hole.

The worst group for the workflow is questions that mix a lookup with a general question, at 33.3%.
That is the under-planning problem the design notes already describe. Asked for a bill and how to
pay it, the planner usually writes the billing step and forgets the FAQ step. I now have a number
for it instead of an impression, and a way to tell whether a prompt change fixed it.

## Three things I did not know before

**Overdue bills are invisible.** Both versions query billing with `status = 'pending'` only.
POL000005 has overdue rows and nothing pending, so both versions tell the customer there is no
pending bill. That is true and it is also the wrong thing to say to someone who is behind on
payments. It is a real bug and it is in both versions, so the eval found it rather than the
comparison.

**A claim cannot be traced to its policy.** `SQL_CLAIM_BY_ID` selects the claim ID, status,
estimated loss and incident type. It does not select the policy number, so neither version can
answer which policy a claim belongs to. I only noticed because I wrote a question that needed it.

**Lowercase IDs work now, and the README was wrong about it.** The README and the design notes both
say `pol000002` is not recognised, because the workers match `POL\d+`. That is true of the
supervisor version, which ran the regex over the raw conversation. It is not true of this one. The
planner writes the task string, and it writes `Find policy status for POL000002`. The regex then
matches, because it is reading the planner's words and not the user's. I checked the plan directly
to confirm that is what happens. Putting a model between the user's text and the regex fixed a
limitation I had written down as permanent. I did not design it that way and I am not going to
pretend I did.

## How I kept it fair

Both versions read the same PostgreSQL container and the same seeded data, and I pointed them at
the same ChromaDB store. Both run `gpt-4o-mini` at `temperature=0`.

The labels were written before either version ran. The frozen copy and its checksum are in `eval/`.

Ground truth comes out of the database, not out of a second model. I read the values from the
tables first, then wrote them into the labels, so scoring is a string match against something
PostgreSQL returned. There is no model judging any answer.

Nothing in the set touches the `payments` or `auto_policy_details` tables. The supervisor version
has tools for those and this one has no equivalent, so scoring them would measure what I happened
to build rather than how well either routes.

Two things are not symmetrical and I would rather say so:

The supervisor's workers call `re.search` on the whole conversation history, so they take the first
ID they find. This version's workers call `re.findall` on one isolated task string. That is a
difference in the workers as well as in the routing, and it helps this version on questions with
two IDs for one worker.

The three-turn questions were written to test the failure section 1 predicts, so finding it is not
a surprise. I included two that need the history carried forward, which is the thing this version
throws away on purpose, and it handled both.

## Corrections I made to my own scoring

I checked the answers after the first run and found three faults in my scoring rather than in
either system. I fixed them, kept every version of the numbers, and the details are in
`eval/README.md`.

Two questions were answered correctly by both versions and marked wrong because my list of
not-found phrases did not include "no pending bills" or "I can't provide phone numbers". One label
required a field neither version can return. One label required a policy type in an answer to a
question that only asked about status.

The fourth one goes the other way and I want it on the record. I labelled the lowercase ID question
expecting both versions to fail, because that is what my own README says happens. The current
version answers it correctly. The label was my prediction rather than the right answer, so I
changed it to check the right answer, and it moved this version up.

Fixing the first three moved the supervisor from 42.5% to 48.3% and this version from 83.6% to
88.4%. The lowercase correction took the supervisor to 47.8% and this version to 89.9%.

## What this is not

One model, one temperature, 69 questions I wrote myself, and synthetic data. It is a regression
test for this project, not a benchmark, and the questions test the routing I built rather than
insurance support in general.

The injection group is ten attempts I thought of, not a red team exercise. Holding 36 of 36 means
those ten did not work three times each. It does not mean the system is safe against an attacker
who is trying harder than I was.

Three runs is enough to see that the supervisor's routing moves around and this version's mostly
does not. It is not enough to put a confidence interval on any single number.

Everything needed to run it again is in `eval/`, including the raw output of both runs.
