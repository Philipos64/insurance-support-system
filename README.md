# Insurance Support System — a Plan-and-Execute Multi-Agent Architecture

A customer-support system for an insurance company, built as a **compound AI system**: a planner
LLM decomposes each request into isolated sub-tasks, a dispatcher routes them to specialised
workers, and an answer agent synthesises the collected evidence into a single reply.

The design goal was to keep the LLM in charge of *routing* while keeping data retrieval
**deterministic** — database lookups are plain SQL behind regex extraction, not tool-calling
guesswork. This keeps answers grounded and makes failures debuggable.

![Architecture](architecture.png)

---

## How it works

A request flows through a [LangGraph](https://langchain-ai.github.io/langgraph/) state machine:

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

**The planner** reads the conversation and outputs a strict-JSON plan — an array of
`{agent, task}` steps plus a justification. It does not fetch anything itself.

**The dispatcher** pops one task off the plan per iteration and routes it to exactly one worker.
Workers return to the dispatcher, so a multi-step request ("what's my bill *and* how do I pay it")
executes as separate, isolated lookups rather than one muddled query.

**Deterministic workers** (`policy`, `billing`, `claims`) extract IDs with regex (`POL\d+`,
`CLM\d+`) and run parameterised SQL against PostgreSQL. No LLM call, no hallucinated data — if the
policy isn't in the database, the worker says so.

**The RAG specialist** queries a ChromaDB vector store of 1,002 insurance FAQ entries. The planner
is prompted to hand it a *pure keyword string* rather than a question, so the node skips a
query-rewriting LLM call and searches directly — one API call instead of two.

**Task isolation** is the key idea: because each worker sees only its own task string and never the
full conversation, one agent's context cannot contaminate another's lookup.

---

## Tech stack

| Layer | Choice |
|---|---|
| Orchestration | LangGraph (`StateGraph`, conditional edges) |
| LLM | OpenAI `gpt-4o-mini`, `temperature=0` |
| Structured data | PostgreSQL 17 (Docker, `pgvector/pgvector:pg17`) |
| Vector store | ChromaDB (persistent, local) |
| DB driver | Psycopg 3 (binary) |
| Interface | FastAPI (SSE streaming) + hand-written HTML/CSS/JS |

---

## Running it

**Prerequisites:** Python 3.10+, Docker, and an OpenAI API key.

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure credentials
cp .env.example .env
#    then edit .env and add your OPENAI_API_KEY

# 3. Start PostgreSQL (host port 5433)
docker compose up -d

# 4. Create the schema and seed synthetic data
#    1,000 customers · 1,500 policies · 5,000 billing rows · 300 claims
python database.py

# 5. Build the FAQ vector store (downloads a dataset, takes a minute)
python setup_rag.py

# 6. Launch the app
python api.py
```

Then open <http://localhost:8000>.

To verify the database connection on its own: `python test_connection.py`

### Try these

The **Examples** button opens a library of 37 ready-made questions grouped by what they exercise,
so you can click instead of typing:

| Group | What it exercises |
|---|---|
| Single lookup | one worker, one parameterised query |
| Multi-step plans | several isolated tasks dispatched in sequence |
| Knowledge base | RAG over the FAQ store, no database involved |
| Database + knowledge | the hardest planning case — both in one plan |
| Edge cases | missing, malformed and non-existent identifiers |
| Escalation | the human-handoff path |
| **Prompt injection** | 10 attempts to steer the system through user input |

The injection group is worth opening the Developer view for: each entry carries a note on which
layer is expected to stop it, and the trace shows whether the attempt reached the plan, reached a
worker, or changed anything. Results are written up in
[docs/design-notes.md](docs/design-notes.md).

The question library lives in `data/sample_questions.json` and is served at `/api/samples`, so you
can add your own without touching the frontend.

### Two views

The interface has a **Customer** view — an ordinary chat window — and a **Developer** view that
shows the same conversation alongside a live execution trace. The trace streams in as the graph
runs and, for each turn, shows:

- the **flow chain** of every node the request passed through, in order
- the planner's reasoning and the **JSON plan** it produced, before any of it executes
- each dispatch: which worker was chosen, and the isolated task string it received
- the SQL result each worker returned, and the query and documents RAG retrieved
- per-node timing, and whether the step was an **API call** or **local execution**

A **Raw state** toggle expands the complete `GraphState` after every node. Because the plan is
produced as data before execution, the trace shows what the system intended to do next to the same
detail as what it actually did.

---

## Data

All data is **synthetic**. `database.py` generates it from a seeded RNG (`random_state=42`) —
names are random first/last combinations and emails are `user1@example.com` … `user1000@example.com`.
No real customer information is used anywhere in this project.

The FAQ corpus is sampled from the public
[`deccan-ai/insuranceQA-v2`](https://huggingface.co/datasets/deccan-ai/insuranceQA-v2) dataset.

---

## Project layout

```
main.py             LangGraph workflow — 8 nodes, state schema, routing
prompts.py          System prompts for planner, RAG specialist, answer agent
agent_tools.py      SQL handlers for policy / billing / claims lookups
database.py         Schema definition and synthetic data generation
setup_rag.py        Builds the ChromaDB FAQ vector store
api.py              FastAPI app: serves the frontend, streams graph events (SSE)
static/             Frontend - index.html, style.css, app.js (no framework)
test_connection.py  Standalone database connectivity check
docker-compose.yml  PostgreSQL 17 + pgvector
data/               Demo FAQs and the example-question library (JSON)
docs/design-notes.md  Architecture rationale and known limitations
```

---

## Design rationale

This was first built as a **supervisor-agent** system — one LLM re-reading the conversation each
turn and freely choosing a specialist. That version was replaced because it was unpredictable, it
could loop, and it made control-flow decisions by reading raw user text, which is the standard
prompt-injection setup. For something framed as a customer-facing product, those are the wrong
properties to ship.

The current design trades autonomy for predictability: the LLM decides *what* should happen, but
the set of things a worker can actually do is fixed in code and short enough to enumerate.

**[docs/design-notes.md](docs/design-notes.md)** covers that reasoning in full, along with the
remaining known limitations — including the failure traces that prompted the rewrite.
