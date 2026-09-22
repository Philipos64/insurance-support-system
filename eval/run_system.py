"""
Run the frozen eval set against one system and append results to a JSONL file.

Invoked with the working directory set to the system's own folder, so that
`import main`, `load_dotenv()` and the relative `./chroma_db` path all resolve
the way that system expects. Both folders point at the same Postgres container
and, via a symlink, the same Chroma store.

Every result is appended the moment it completes, and a rerun skips work that is
already in the file. So if the OpenAI account runs out of credit part way
through, you top it up and run the same command again to carry on.

    cd <system folder>
    python <abs path>/run_system.py --system old --runs 3
"""

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path

# The system under test lives in the working directory, not next to this file.
sys.path.insert(0, os.getcwd())

from langchain_core.callbacks import BaseCallbackHandler

EVAL_DIR = Path(__file__).resolve().parent

# Each system's node names, mapped to one shared vocabulary so the two are
# comparable. Nodes that only route or write prose are not lookup destinations.
ROUTE_MAP = {
    "old": {
        "policy_agent": "policy",
        "billing_agent": "billing",
        "claims_agent": "claims",
        "general_help_agent": "rag",
        "human_escalation_agent": "human",
    },
    "new": {
        "policy_worker": "policy",
        "billing_worker": "billing",
        "claims_worker": "claims",
        "rag_specialist": "rag",
        "human_handoff": "human",
    },
}
# The jev system is the current graph with the planner swapped for Jev. Same
# node names, same route vocabulary.
ROUTE_MAP["jev"] = ROUTE_MAP["new"]

ANSWER_KEYS = ("final_answer",)

# Errors worth retrying: the request failed for a reason that may not recur.
TRANSIENT = ("rate_limit", "timeout", "timed out", "connection", "overloaded",
             "503", "502", "500", "apiconnection", "internalserver")
# Errors that mean stop and fix the account. Retrying just burns time.
FATAL = ("insufficient_quota", "exceeded your current quota", "billing",
         "invalid_api_key", "incorrect api key", "401", "authentication")


class LLMCounter(BaseCallbackHandler):
    """Counts model calls made anywhere inside one graph invocation."""

    def __init__(self):
        self.calls = 0

    def on_llm_start(self, *args, **kwargs):
        self.calls += 1

    def on_chat_model_start(self, *args, **kwargs):
        self.calls += 1


def classify_error(exc):
    text = f"{type(exc).__name__} {exc}".lower()
    for marker in FATAL:
        if marker in text:
            return "fatal"
    for marker in TRANSIENT:
        if marker in text:
            return "transient"
    return "other"


def run_one_turn(app, message, history, system):
    """Stream one turn and record which nodes ran, in order."""
    conversation = f"{history}\nUser: {message}" if history else f"\nUser: {message}"
    inputs = {
        "user_input": message,
        "conversation_history": conversation,
        "n_iteration": 0,
    }
    if system in ("new", "jev"):
        inputs["agent_responses"] = []
        inputs["plan"] = []

    counter = LLMCounter()
    node_order = []
    final_state = {}

    started = time.perf_counter()
    for output in app.stream(inputs, config={"recursion_limit": 50,
                                             "callbacks": [counter]}):
        for node_name, state_update in output.items():
            node_order.append(node_name)
            if isinstance(state_update, dict):
                final_state.update(state_update)
    elapsed = time.perf_counter() - started

    answer = ""
    for key in ANSWER_KEYS:
        if final_state.get(key):
            answer = final_state[key]
            break

    routes = [ROUTE_MAP[system][n] for n in node_order if n in ROUTE_MAP[system]]
    record = {
        "answer": answer or "",
        "node_order": node_order,
        "routes": routes,
        "llm_calls": counter.calls,
        "seconds": round(elapsed, 3),
        "history_out": final_state.get("conversation_history", conversation),
        # Ids of the FAQ documents the RAG node retrieved, if it ran. The v2
        # eval scores retrieval against these; nothing else reads them.
        "rag_doc_ids": final_state.get("rag_doc_ids", []),
    }
    # The Jev planner is an HTTP call, not a LangChain model, so LLMCounter
    # never sees it. The node leaves a record in state; copy it out here so
    # planner cost and latency are comparable across systems.
    jev = final_state.get("jev_trace")
    if jev:
        record["jev_calls"] = jev.get("calls", 0)
        record["jev_seconds"] = jev.get("seconds", 0.0)
        record["jev_cost"] = jev.get("cost", 0.0)
        record["jev_fallback"] = jev.get("fallback", False)
        record["jev_unsure"] = jev.get("unsure", False)
        record["jev_injection_flagged"] = jev.get("injection_flagged", False)
        record["jev_model"] = jev.get("model")
    return record


def run_item(app, item, system):
    """Run every turn of an item. Only the last turn is scored."""
    history = ""
    turn_records = []
    for message in item["turns"]:
        record = run_one_turn(app, message, history, system)
        turn_records.append(record)
        # Feed the turn back in the same shape the app uses.
        history = f"{history}\nUser: {message}" if history else f"\nUser: {message}"
        history = f"{history}\nAssistant: {record['answer']}"

    scored = turn_records[-1]
    row = {
        "answer": scored["answer"],
        "routes": scored["routes"],
        "node_order": scored["node_order"],
        "llm_calls": sum(t["llm_calls"] for t in turn_records),
        "seconds": round(sum(t["seconds"] for t in turn_records), 3),
        "turns": turn_records,
        "rag_doc_ids": scored.get("rag_doc_ids", []),
    }
    if any("jev_calls" in t for t in turn_records):
        # Summed over turns like llm_calls and seconds; the flags describe
        # the scored (last) turn, like routes.
        row["jev_calls"] = sum(t.get("jev_calls", 0) for t in turn_records)
        row["jev_seconds"] = round(sum(t.get("jev_seconds", 0.0) for t in turn_records), 3)
        row["jev_cost"] = sum(t.get("jev_cost", 0.0) for t in turn_records)
        row["jev_fallback"] = scored.get("jev_fallback", False)
        row["jev_unsure"] = scored.get("jev_unsure", False)
        row["jev_injection_flagged"] = scored.get("jev_injection_flagged", False)
        row["jev_model"] = next((t.get("jev_model") for t in turn_records if t.get("jev_model")), None)
    return row


def already_done(path):
    """Read the output file so a rerun resumes instead of repeating work."""
    done = set()
    if not path.exists():
        return done
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue  # A partial last line from an interrupted run.
            if row.get("status") == "ok":
                done.add((row["item_id"], row["run"]))
    return done


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--system", choices=["old", "new", "jev"], required=True)
    parser.add_argument("--runs", type=int, default=3,
                        help="Repeats per question, to measure run-to-run stability.")
    parser.add_argument("--out", default=None)
    parser.add_argument("--questions", default=str(EVAL_DIR / "questions.json"))
    parser.add_argument("--only", default=None,
                        help="Comma-separated categories, for a smoke test.")
    parser.add_argument("--split", default=None, choices=["dev", "test"],
                        help="v2 sets carry a dev/test split; run only one half.")
    parser.add_argument("--retries", type=int, default=2)
    args = parser.parse_args()

    out_path = Path(args.out) if args.out else EVAL_DIR / "results" / f"{args.system}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(args.questions, encoding="utf-8") as f:
        items = json.load(f)["items"]
    if args.only:
        wanted = {c.strip() for c in args.only.split(",")}
        items = [i for i in items if i["category"] in wanted]
    if args.split:
        items = [i for i in items if i.get("split") == args.split]

    done = already_done(out_path)
    if done:
        print(f"Resuming: {len(done)} results already in {out_path}")

    if args.system == "jev":
        os.environ["PLANNER"] = "jev"  # main.py reads this at import time
    import main as system_module  # Resolved from the working directory.
    app = system_module.app

    todo = [(item, run) for run in range(1, args.runs + 1)
            for item in items if (item["id"], run) not in done]
    print(f"[{args.system}] {len(todo)} invocations to run "
          f"({len(items)} questions x {args.runs} runs)")

    for index, (item, run) in enumerate(todo, start=1):
        label = f"[{args.system}] {index}/{len(todo)} {item['id']} run{run}"
        row = {"system": args.system, "item_id": item["id"],
               "category": item["category"], "run": run,
               # Hosted models move under you; record exactly what answered.
               "llm_model": getattr(system_module.llm, "model_name", None),
               "planner": os.environ.get("PLANNER", "gpt")}

        for attempt in range(args.retries + 1):
            try:
                row.update(run_item(app, item, args.system))
                row["status"] = "ok"
                break
            except Exception as exc:  # noqa: BLE001 - we classify and report it
                kind = classify_error(exc)
                if kind == "fatal":
                    print(f"\n{label}: FATAL API error: {exc}\n")
                    print("Stopping here. Results so far are saved in")
                    print(f"  {out_path}")
                    print("Top the account up, then run the same command again "
                          "and it will carry on from this point.")
                    sys.exit(2)
                if kind == "transient" and attempt < args.retries:
                    wait = 5 * (2 ** attempt)
                    print(f"{label}: {type(exc).__name__}, retrying in {wait}s")
                    time.sleep(wait)
                    continue
                row["status"] = "error"
                row["error"] = f"{type(exc).__name__}: {exc}"
                row["traceback"] = traceback.format_exc()[-1500:]
                break

        with open(out_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
            f.flush()
            os.fsync(f.fileno())

        if row["status"] == "ok":
            print(f"{label}: routes={row['routes'] or ['-']} "
                  f"llm={row['llm_calls']} {row['seconds']}s")
        else:
            print(f"{label}: ERROR {row.get('error', '')[:120]}")

    print(f"[{args.system}] finished. Results in {out_path}")


if __name__ == "__main__":
    main()
