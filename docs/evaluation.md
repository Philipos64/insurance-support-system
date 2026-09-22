# Evaluation

There are three versions of this system now, and they are all scored on the same 443 questions.

The original supervisor version is the one I built for the course. The workflow version is the
rewrite, where a planner writes a plan as JSON and Python runs it. The third swaps that planner for
Jev, a typed-decision model, and changes nothing else. Section 1 of the design notes argues the
first rewrite was worth it. This puts numbers on that argument and on the second one.

## What I ran

443 questions, three times each, against all three versions. 1,329 runs per version, 3,987 in
total, no errors.

The questions are not hand-written any more. 278 of them are filled from templates using real rows
out of the database, so the expected answer comes from the same place the system has to get it. The
other 165 are paraphrases of those, written by Claude Sonnet in six styles: casual, terse, formal,
typos, indirect, and Swedish. Every question carries a slice label, and the slices are single
lookups, multi-step lookups, questions that mix a lookup with a general one, knowledge questions,
not-found cases, vague or malformed IDs, multi-turn, escalation, off-topic, and prompt injection.

`eval/v2/README.md` describes how the set was built and how the labels were derived.

### The earlier 69-question set

The first version of this eval was 69 questions I wrote by hand. It is still in `eval/`, and the
numbers it produced are in `eval/results/scores_v1.3.txt`.

I replaced it because it was too small to say anything careful. 69 questions gives you a pass rate
you cannot put an interval on, and I had written every question myself, so the set tested the
routing I happened to think of. It also turned out to be a tuning set: I built the first Jev planner
by reading its failures on those 69 questions, which means the 100% it eventually scored there is
not evidence of anything.

The v2 set exists to fix both problems. It is big enough for confidence intervals, the questions
come from the data rather than from me, and it is split so that the number I report was not the
number I tuned against.

### The split

The 443 questions are split in half by base item, so a template question and its paraphrases always
land on the same side. The dev half is 223 questions and the test half is 220.

I read the dev half. It found four bugs in my own labels and matcher, which I fixed as v2.1. I ran
the test half once per candidate and did not read the per-question failures.

That gives two honest comparisons, and they are not the same comparison:

- **Supervisor against workflow** is reported on all 443. Neither system was tuned on any of it.
  Both existed before the set did.
- **Workflow against Jev** is reported on the held-out test half, because the dev half informed
  the v2.1 scorer fixes and an earlier Jev planner was tuned on the old 69-question set.

## Results, all 443 questions

Routing means the request reached exactly the right workers, no more and no fewer. Pass means that
plus the right values out of the database, the right behaviour when there is nothing to return, and
nothing leaked. 1,311 scored runs after excluding the known-gap slice, which is measured separately
below.

| | Supervisor | Workflow | Jev planner |
|---|---|---|---|
| Routing correct | 70.3% | 92.8% | **97.4%** |
| Pass | 62.4% | 92.1% | **96.6%** |
| 95% interval on pass | [59.7, 65.0] | [90.6, 93.5] | [95.5, 97.5] |
| Model calls per question | 3.14 | 2.22 | **1.21** |
| Seconds per question | 3.85 | 2.81 | **1.94** |
| Escalated without being asked | 0.8% | 0.0% | 0.0% |
| Injection attempts held | 18 of 36 | 36 of 36 | 36 of 36 |

Every question was seen by every system, so the right test is a paired one. McNemar's exact test on
the runs where two systems disagree:

| Comparison | Discordant pairs | p |
|---|---|---|
| Supervisor vs workflow | 399 to 9 | < 0.0001 |
| Supervisor vs jev | 468 to 19 | < 0.0001 |
| Workflow vs jev | 93 to 34 | < 0.0001 |

By slice, on pass:

| Slice | n | Supervisor | Workflow | Jev planner |
|---|---|---|---|---|
| Single lookup | 579 | 91.7% | 100.0% | 97.4% |
| Not found | 120 | 55.0% | 65.0% | 100.0% |
| Multi-step lookup | 126 | 15.1% | 100.0% | 100.0% |
| Lookup plus FAQ | 90 | 0.0% | 53.3% | 98.9% |
| Knowledge | 132 | 84.1% | 93.9% | 100.0% |
| Vague or odd ID | 60 | 45.0% | 86.7% | 78.3% |
| Multi-turn | 66 | 42.4% | 100.0% | 95.5% |
| Escalation | 42 | 0.0% | 100.0% | 100.0% |
| Off-topic and chit-chat | 60 | 35.0% | 96.7% | 80.0% |
| Prompt injection | 36 | 41.7% | 97.2% | 100.0% |

The supervisor is worse than it looked on the small set. It scored 47.8% there and 62.4% here,
which means the old set was harder on it than the data is. The gap to the workflow version narrows
from 42 points to 30. I would rather report the smaller gap with an interval around it.

Both rewrites are cheaper as well as better. I expected to trade cost for predictability and it
went the other way twice. The supervisor spends calls re-deciding what it already decided. The GPT
planner spends a call writing JSON that Jev returns as typed fields in one.

## Workflow against Jev, on the held-out half

220 questions, 660 runs per system, 651 scored.

| | Workflow | Jev planner |
|---|---|---|
| Routing correct | 92.8% | **96.6%** |
| Pass | 92.6% [90.4, 94.4] | **96.3% [94.6, 97.5]** |
| Model calls per question | 2.19 | **1.18** |
| Seconds per question | 2.72 | **1.97** |
| FAQ document in the top 4 | 71.6% | **90.2%** |

McNemar on the test half: 651 pairs, Jev alone right on 46, the workflow alone right on 22,
p = 0.005.

The gap was 5.3 points on the dev half and 3.7 on the test half. Some of the dev advantage was
tuning, which is the reason for splitting the set in the first place.

### What Jev does differently

One call, seven typed yes or no questions with confidence attached, and Python turns the answers
into a plan against fixed thresholds. The IDs come out with a regex before the call rather than
being written by a model. Everything after the planner is unchanged, so the workers, the SQL and
the answer agent are the same code in both columns.

The slices where it wins are the ones where the GPT planner had to remember to write a second step.
Lookup plus FAQ goes from 53.3% to 98.9%, and not-found from 65.0% to 100.0%. A typed field for
"does this need the FAQ store" is harder to forget than a line of JSON.

## Retrieval

The RAG step is where the two planners differ most, and not in the way I predicted.

The workflow's planner writes keywords for the FAQ search. The Jev path skips that and searches
with the user's own message, with IDs stripped out. On the test half the raw message finds the
right document in the top 4 on 90.2% of runs against 71.6% for the keywords.

The README used to say the keyword rewrite was a saving, because it meant not spending an API call
to rewrite the query. That was true about the cost and wrong about the result. Compressing the
question to keywords throws away the wording that the embedding needed. I have corrected the claim
rather than quietly dropping it.

**The supervisor is not in this comparison.** Its `main.py` never sets `rag_doc_ids`, which is the
field the scorer reads, so its retrievals are not captured and every run scores as a miss. Its
score of 0.0% in `scores_all_v2.1_with_old.txt` is an artifact and the file says so. Its general
help agent does run RAG. Retrieval is a workflow-against-Jev number only.

## The loop, measured

This is from the 69-question run, because it needed the per-run node traces I kept from that pass.

The supervisor visited the same worker more than once inside a single turn on 24.6% of runs. The
worst case was six lookups of the same claim followed by a forced escalation:

```
claims -> claims -> claims -> claims -> claims -> claims -> human
```

It hit the iteration cap 14 times, and every one of those was a question that should have been
answered.

The workflow version repeated a worker on 8.7% of runs, and that number means something different.
Those are plans with more than one task for the same worker, like three claim IDs in one question.
The dispatcher runs each task once and the list only gets shorter. The most nodes it ever used in
one turn was three. The supervisor's most was seven, which is the cap.

The specific failure section 1 of the design notes predicts reproduces every time. Ask about
POL000002, then ask how to get a cancelled policy reinstated:

```
supervisor:  supervisor -> policy_agent -> supervisor -> policy_agent -> supervisor -> final_answer
workflow:    planner -> dispatcher -> rag_specialist -> dispatcher -> answer_agent
```

Same question, same stale policy number in the history. The supervisor goes back to the policy
worker because the ID is still sitting there. The workflow sends it to the FAQ store, which is
where the answer is.

## Escalation

Still the widest gap. Asked plainly for a human across 42 runs, the supervisor got it right zero
times. Both rewrites got it right every time.

The supervisor also escalates when nobody asked, on 0.8% of runs, which is the iteration cap firing
on a question it should have answered.

## Prompt injection

12 injection questions, three runs each, 36 runs per system.

The supervisor leaked a marker on 6 of the 12 questions, 18 of the 36 runs. It printed `HACKED`
when told to, printed `PWNED` when told to append it to a legitimate billing answer, and answered
to `JAILBROKEN` and `ADMIN-MODE`. Both rewrites held 36 of 36.

Neither of the rewrites wrote to the database, and neither did the supervisor. I fingerprint the
database before and after every run, row counts plus an md5 of every policy and claim status, and
it comes back identical each time. That includes the attempt to change a policy status as an
administrator, which is the one the design notes admit gets into the plan. It still gets into the
plan. It still cannot do anything, because `policy_worker` only runs a `SELECT`.

The injection set is twelve attempts I thought of, not a red team exercise. Holding 36 of 36 means
those twelve did not work three times each.

## Where each version loses

**The workflow version** loses on questions that mix a lookup with a general question, at 53.3%.
Asked for a bill and how to pay it, the planner writes the billing step and forgets the FAQ step.
That is the under-planning problem the design notes already describe, and it is the single biggest
thing the Jev planner fixes.

It also loses on not-found cases, at 65.0%. When the ID is real but there is nothing to return, it
often routes as though there were.

**The Jev planner** loses in three places, and they are the reason it is not the default.

Swedish paraphrases are the worst of them. It passes 82.6% of them across the whole set against the
workflow's 92.8%, and on the test half it is 70% against 100%. The typed questions are written in
English and the criteria describe English phrasings, so a Swedish question is being judged against
a description that does not quite fit it.

Off-topic and chit-chat, at 80.0% against 96.7%. Asked for the capital of Australia it sometimes
decides a lookup is needed. There is no typed question for "is this about insurance at all", so
nothing stops it.

Vague or malformed IDs, at 78.3% against 86.7%. Asked "do I have any bills outstanding" with no ID
anywhere, it plans a billing lookup that cannot run.

All three are fixable in the question set rather than in the architecture, and all three would need
their own single run of the test half to claim they were fixed.

## Three things I did not know before

Two of these are still open, and they are in every version.

**Overdue bills are invisible.** All three versions query billing with `status = 'pending'` only.
A policy with overdue rows and nothing pending is reported as having no pending bill. That is true
and it is the wrong thing to say to someone who is behind on payments. The v2 set measures it as a
named slice, `billing_overdue_only`, scored separately so it does not flatter anyone: all three
route to billing correctly and all three say nothing is due.

**A claim cannot be traced to its policy.** `SQL_CLAIM_BY_ID` selects the claim ID, status,
estimated loss and incident type. It does not select the policy number, so no version can answer
which policy a claim belongs to.

**Lowercase IDs work, and the README was wrong about it.** The README and the design notes both
used to say `pol000002` is not recognised, because the workers match `POL\d+`. That is true of the
supervisor, which ran the regex over the raw conversation. It is not true of either rewrite. The
planner writes the task string, and it writes `Find policy status for POL000002`, so the regex
reads the planner's words and not the user's. The v2 set has a `lowercase_id` slice and both
rewrites pass all of it while the supervisor mostly fails. Putting a model between the user's text
and the regex fixed a limitation I had written down as permanent. I did not design it that way.

## How I kept it fair

All three versions read the same PostgreSQL container and the same seeded data, and I pointed them
at the same ChromaDB store. All three answer with `gpt-4o-mini` at `temperature=0`. Only the
planner changes in the third column, and the model string it used is recorded on every result row,
because a hosted model can move under you.

Labels come out of the database, not out of a second model. The templates are filled from rows I
read first, so scoring is a string match against something PostgreSQL returned. There is no model
judging any answer. The frozen question set and its checksum are in `eval/v2/`.

Two things are not symmetrical and I would rather say so.

The supervisor's workers call `re.search` on the whole conversation history, so they take the first
ID they find. Both rewrites call `re.findall` on one isolated task string. That is a difference in
the workers as well as in the routing, and it helps the rewrites on questions with two IDs for one
worker.

The paraphrases were generated by a model, so the styles are a model's idea of casual or indirect
phrasing rather than samples of how people actually write. The Swedish ones in particular are
fluent in a way real messages often are not.

## Corrections I made to my own scoring

On v1 I found three faults in my scoring rather than in either system, and one that went the other
way. Those are recorded in `eval/README.md` and the numbers are all kept.

On v2 I read the dev half and found four more, all of which penalised every system equally:

Swedish paraphrases are answered in Swedish, and my fact matcher only held English forms, so a
correct Swedish answer scored as wrong. Each expected fact now carries its Swedish forms.

"Cannot be found" was not on my list of not-found phrases, so a correct not-found answer scored as
wrong.

Two label errors in the generated set, where the template had filled from the wrong column.

I fixed all four as v2.1, re-scored both halves, and then ran the test half. The dev numbers before
and after the fix are both in `eval/v2/results/`.

## What this is not

One answer model, one temperature, synthetic data, and a question set generated from my own
templates. It is a regression test for this project, not a benchmark, and it tests the routing I
built rather than insurance support in general.

Three runs per question is enough to see that the supervisor's routing moves around and that the
rewrites mostly do not. It is not enough to characterise the tail of anything.

The Jev planner reaches an alpha endpoint, and the model string is a dated build. Both are recorded
per result row so the number can be tied to what produced it, but neither is a stable thing to
depend on, which is why `PLANNER` still defaults to `gpt`.

Everything needed to run it again is in `eval/`, including the raw output of all three runs.
