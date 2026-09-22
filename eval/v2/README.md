# Eval v2

A larger question set, built from the data instead of by hand, with a split
that is only run once. The first eval (`eval/`, 69 questions) is kept as is.
It found the bugs and it settled the supervisor-vs-workflow question. What it
could not do is tell a real improvement from a wording that happened to fit
69 questions, because I read its failures while tuning the Jev planner.

## How the questions were made

**Templates filled from the database.** `generate.py` takes real rows from
PostgreSQL and the FAQ store and fills fixed templates: "Is policy {id}
active?", "How much do I owe on {id}?", "What claims are there on {id}?", and
so on, 31 families in all. The expected route is the template's; the expected
facts (a status, an amount, an owner's name, a list of claim ids) are read
from the same row. No model wrote a label, and neither did I, apart from the
template itself. Knowledge questions are taken from FAQ documents in the store,
so the document a question came from is its expected retrieval hit.

**Paraphrases.** `paraphrase.py` sends a sample of the base items to Claude
Sonnet (through OpenRouter, so a different model family from the one being
tested) and asks for the same request in another style: casual, terse, formal,
with typos, roundabout, or in Swedish. The rewrite inherits the base item's
labels. A validator rejects any rewrite that changes the set of ids, changes
the number of turns, or comes back identical; five were rejected out of 170.
The injection items are not paraphrased, so the adversarial slice stays
exactly as written.

**Split.** `build.py` puts every base item, together with all of its
paraphrases, into either `dev` or `test`, alternating within each family so
the halves have the same shape. Paraphrases never straddle the split, so a
wording cannot be tuned on one half and met again, reworded, in the other.
The result is frozen in `questions.json` and hashed in `questions.sha256`.

**The two halves.** `dev` is for looking at failures and changing things. `test`
is run once per candidate and its failures are not read; `score.py --split
test` deliberately does not list them.

## What is measured

`score.py` reuses the first eval's `score_row`, so a pass means the same
thing: every expected route reached and no other, every expected fact in the
answer, the expected behaviour (asking for an id, saying not found), and
nothing forbidden in the reply. On top of that:

- **Retrieval, hit@4.** On knowledge questions, was the document the question
  came from among the four the RAG node retrieved? This is the measurement the
  first eval lacked: it scored knowledge questions on routing alone.
- **Confidence intervals.** Wilson 95% intervals on the headline rates.
- **Paired comparison.** Every system sees the same questions, so the honest
  test is McNemar's on the discordant pairs: how many questions did A get
  right and B wrong, and the reverse.
- **Template vs paraphrase.** A gap between the two is wording sensitivity.
- **Known gap.** Policies with overdue bills and no pending ones. The billing
  SQL only reads pending, so both systems say nothing is due. These are scored
  on routing only and reported separately, not folded into the headline.

## Shape of the set

443 items, 223 dev / 220 test, 278 templates and 165 paraphrases. The mix
leans toward single lookups because that is what support traffic looks like.

| slice | what it holds | items |
|---|---|---|
| single_lookup | one id, one fact | 193 |
| knowledge | FAQ questions, with retrieval labels | 44 |
| multi_lookup | two or three ids or facts in one message | 42 |
| not_found | ids that do not exist, policies with no bills | 40 |
| lookup_plus_faq | a lookup and a how-to in one sentence | 30 |
| multiturn | the id is in an earlier turn | 22 |
| non_task | greetings, thanks, off-topic | 20 |
| vague_or_odd_id | no id given, lowercase id | 20 |
| escalation | asks for a human | 14 |
| injection | prompt injection, with and without a real lookup | 12 |
| known_gap | overdue-only billing | 6 |

## Running it

Same driver as the first eval, pointed at this set:

    python eval/run_system.py --system new --runs 3 --questions eval/v2/questions.json --split dev --out eval/v2/results/new.jsonl
    python eval/run_system.py --system jev --runs 3 --questions eval/v2/questions.json --split dev --out eval/v2/results/jev.jsonl
    python eval/v2/score.py --split dev

Then, once, `--split test` for each, and `score.py --split test`.

## Limits

- The paraphrases are one model's idea of six styles, and they are formulaic
  in places ("I would be grateful if you could kindly..."). Real customers
  vary more.
- Facts are matched as substrings, so an answer that states the right amount
  in words would fail, and an answer that states it by accident would pass.
  Neither has been seen to happen, but the check is that crude.
- The FAQ store is 1,000 sampled InsuranceQA pairs plus two company FAQs.
  The retrieval measure is against that store, not against a realistic
  company knowledge base.
- The set was generated on one seeded database. Regenerating on another seed
  gives a different set with the same shape.

## Changes after the first dev run (v2.1)

Reading the dev failures showed four problems with the labels and the
matcher, none with the systems. All four are fixed in the same way for every
system, and the test half had not been run.

- Swedish paraphrases were answered in Swedish and the fact matcher only knew
  English. `score.py` now accepts Swedish forms of each status and type
  ("aktiv", "avbruten", "hemförsäkring"), and "denial" for "denied".
- "Cannot be found" and its Swedish equivalents were not on the not-found
  list. Added, alongside Swedish forms of asking for an id.
- `injection_with_lookup-04` asks who owns a policy and was labelled with the
  policy's status. The owner is now the fact.
- `multi_three` asks "are there any claims against it?" and accepted only the
  claim id. The answer agent sometimes describes the claim by its amount
  instead, which is a correct answer. The amount now counts too.

`questions.sha256` is the v2.1 hash. The v2.0 dev results were scored again
under v2.1 and are what the tables show.

## Results (v2.1, 2026-09-19)

Both systems ran the dev half (223 questions × 3) and then, unchanged, the
test half (220 × 3) once. `gpt-4o-mini` wrote every answer in both; only the
planner differs. Full tables in `results/scores_dev_v2.1.txt` and
`results/scores_test_v2.1.txt`.

| test half | workflow (GPT planner) | Jev planner |
|---|---|---|
| overall pass | 92.6% [90.4, 94.4] | 96.3% [94.6, 97.5] |
| routing accuracy | 92.8% | 96.6% |
| paired (McNemar) | right alone 22 times | right alone 46 times, p = 0.0049 |
| retrieval hit@4 | 71.6% | 90.2% |
| LLM calls per question | 2.19 | 1.18 |
| seconds per question | 2.72 | 1.97 |
| injection held | 18/18 | 18/18 |

On the dev half the gap was wider (97.0% vs 91.7%, p < 0.0001). Some of that
was tuning: the Jev question wording had been adjusted against the first eval,
whose questions resemble the dev templates. The test number is the one to quote.

Where each loses, by slice. The GPT planner drops the how-to half of two-part
questions (`lookup_plus_faq` 60%) and does not send "is there anything due on
POL..." to billing (`not_found` 59%). The Jev planner is weaker on Swedish
paraphrases (70% against GPT's 100%), on bare questions with no id, and on
off-topic questions, which it sends to RAG. Which questions those were on the
test half has not been looked at, on purpose.

Retrieval was a surprise. The Jev planner cannot write a search query, so the
RAG node gets the user's own words with ids removed. That retrieves the right
FAQ document more often than the GPT planner's keyword rewrite, on both halves.
The rewrite abstracts the question away from the store's wording.
