# Insurance Support System

A customer support system for an insurance company, built with LangGraph. You ask it something
like "how much is the bill for POL000001 and what's the status of claim CLM000005", and it works
out which lookups it needs, runs them separately, and writes one answer from the results.

I built this for a university course and then kept working on it afterwards, because the first
version had problems I wanted to fix properly.

![The developer view: workflow graph, execution trace and conversation](docs/interface.png)

<details>
<summary>Data-flow diagram</summary>

![Architecture](architecture.png)

</details>

## Why it's not a multi-agent system any more

I originally built this the usual way: a supervisor agent that read the whole conversation every
turn and picked a specialist to handle it. It demoed fine. I replaced it anyway.

Three things were wrong with it. It was unpredictable, because routing depended on whatever
happened to be in the conversation by then. It looped — once a policy number was mentioned, the
supervisor kept sending general questions back to the policy worker, and I was patching that with
more and more rules inside the prompt. And it made control-flow decisions by reading user text,
which means anything a user typed was competing with my system prompt for control of what the
system did next.

That last one is what decided it. If this were a real product, being talkable into a different
execution path is not something you can ship.

So I rewrote it. The planner still decides *what* should happen, but it writes a plan as JSON and
then a plain Python dispatcher executes it. The workers don't reason at all — they pull an ID out
of their task string with a regex and run one fixed SQL query. Five of the eight nodes never touch
a model.

That means it isn't really a multi-agent system now, and I stopped calling it one. It's closer to
a plan-and-execute workflow. I think losing the autonomy was worth it, and
[docs/design-notes.md](docs/design-notes.md) explains that in more detail, including the parts
that still don't work well.

## How it works

```
                        ┌──────────────────┐
     user query ───────▶│  planner_agent   │  LLM: emits a JSON plan
                        └────────┬─────────┘
                                 │  plan = [{agent, task}, ...]
                                 ▼
                        ┌──────────────────┐
                   ┌───▶│workflow_dispatch │  pops one task at a time
                   │    └────────┬─────────┘
                   │             │
                   │   ┌─────────┼─────────┬──────────────┐
                   │   ▼         ▼         ▼              ▼
                   │ policy_  billing_  claims_    rag_specialist
                   │ worker   worker    worker     (ChromaDB + LLM)
                   │   │         │         │              │
                   └───┴─────────┴─────────┴──────────────┘
                                 │  plan empty
                                 ▼
                        ┌──────────────────┐
                        │   answer_agent   │  LLM: synthesises final reply
                        └──────────────────┘
```

The planner reads the conversation and returns a list of `{agent, task}` steps. It doesn't fetch
anything itself. The dispatcher takes one task off that list at a time and hands it to a single
worker, then the worker comes back to the dispatcher for the next one. When the list is empty, the
answer agent writes the reply from whatever the workers collected.

The important detail is that a worker only ever sees its own task string. It never sees the
conversation. That's what fixed the looping — a policy number from three messages ago can't leak
into an unrelated lookup, because it isn't there to leak.

The policy, billing and claims workers are just regex plus one parameterised `SELECT`. If the ID
isn't in the database they say so rather than inventing something. The RAG specialist searches a
ChromaDB store of about a thousand insurance FAQ entries; the planner hands it keywords rather than
a question, so it can search directly instead of rewriting the query with another API call first.

## Running it

You'll need Python 3.10+, Docker, and an OpenAI API key.

```bash
pip install -r requirements.txt

cp .env.example .env          # then put your OPENAI_API_KEY in it

docker compose up -d          # PostgreSQL on port 5433
python database.py            # creates the schema and seeds synthetic data
python setup_rag.py           # builds the FAQ vector store, takes a minute

python api.py
```

Then open <http://localhost:8000>. If the database won't connect, `python test_connection.py`
checks that on its own.

All the data is fake. `database.py` generates 1,000 customers, 1,500 policies, 5,000 billing rows
and 300 claims from a seeded RNG, so everyone gets the same data. The names are random
combinations and the emails are all `@example.com`. The FAQ text comes from the public
[`deccan-ai/insuranceQA-v2`](https://huggingface.co/datasets/deccan-ai/insuranceQA-v2) dataset.

## Things to try

The **Examples** button has 37 questions grouped by what they exercise, so you don't have to think
of any: single lookups, multi-step plans, knowledge base questions, edge cases like missing or
malformed IDs, escalation to a human, and ten prompt injection attempts.

The injection ones are the interesting ones. Each has a note saying which layer should stop it, and
you can watch in the trace whether the attempt got as far as the plan, as far as a worker, or
nowhere. One of them does get into the plan — I wrote up what happened in the design notes rather
than leaving it out.

## The developer view

There's a **Customer** view, which is just a chat window, and a **Developer** view that shows the
same conversation next to what's actually happening.

The graph at the top is the real topology from `main.py`. Nodes light up as the request reaches
them and edges show the path it took, so you can see a two-step plan fan out to `billing` and
`claims` while `policy` and `rag` stay dark. Clicking a node jumps to that step in the log below;
since the dispatcher usually runs three times in a turn, clicking it repeatedly cycles through
each run.

Below that is the log: the plan the planner produced, each dispatch and the task it sent, what
each worker got back, and how long every step took with a marker for whether it cost an API call.

Each step has an **Inspect** button, which is the part I'd actually look at. It shows what that
step *received*, not just what it returned — the exact prompt for the LLM steps, and for a worker
the task string, the regex, the SQL statement it ran, the value bound to it and the rows that came
back. The answer agent's view shows the complete context it was handed, which is a useful way to
confirm it really can't see anything else.

You can hide the graph with the **Graph** toggle, and **Raw state** shows the full `GraphState`
after every node if you want everything.

## What's in here

```
main.py             the LangGraph workflow - 8 nodes, state, routing
prompts.py          prompts for the planner, RAG specialist and answer agent
agent_tools.py      the SQL lookups
database.py         schema and synthetic data generation
setup_rag.py        builds the ChromaDB FAQ store
api.py              FastAPI - serves the frontend, streams the graph events
static/             the frontend, no framework
test_connection.py  database connection check
docker-compose.yml  PostgreSQL 17 + pgvector
data/               demo FAQs and the example questions
docs/design-notes.md  why it's built this way, and what still doesn't work
```

## Known problems

Written up properly in [docs/design-notes.md](docs/design-notes.md), but the short version:

The planner sometimes only plans half of a two-part question — ask for a bill *and* how to pay it
and you'll often get the bill plus "I don't have information about that". ID matching is strict
regex, so `pol000002` or "policy 1" aren't recognised. There's no authentication, so anyone can
look up any policy. And I never built a proper eval set, so routing quality is something I checked
by reading traces rather than measuring.
