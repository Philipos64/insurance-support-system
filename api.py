"""
HTTP API for the insurance support system.

Wraps the LangGraph workflow in a streaming endpoint so the frontend can render
the orchestration as it happens: every node execution is pushed to the browser
as a server-sent event, in the order the graph runs them.

Run with:  python api.py
"""

import json
import time
from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from main import app as workflow

STATIC_DIR = Path(__file__).parent / "static"

# Nodes that call the OpenAI API, as opposed to running purely local Python.
# The frontend badges each step with this so the cost of a turn is visible.
LLM_NODES = {"planner_agent", "rag_specialist", "answer_agent"}

api = FastAPI(title="Insurance Support System")


class ChatRequest(BaseModel):
    message: str
    history: str = ""


def to_jsonable(value: Any) -> Any:
    """Convert a graph state value into something json.dumps can handle.

    LangGraph state carries LangChain message objects, which are not
    JSON-serialisable; everything else is already primitive.
    """
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    if hasattr(value, "content"):  # LangChain message
        return {"type": type(value).__name__, "content": value.content}
    return str(value)


def sse(event: str, data: Dict[str, Any]) -> str:
    """Format one server-sent event."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def run_turn(message: str, history: str):
    """Stream one conversation turn as SSE, one event per executed node."""
    conversation = f"{history}\nUser: {message}" if history else f"\nUser: {message}"

    inputs = {
        "user_input": message,
        "conversation_history": conversation,
        "n_iteration": 0,
        "agent_responses": [],
        "plan": [],
    }

    final_answer = ""
    updated_history = conversation
    path: List[str] = []
    seq = 0
    turn_started = time.perf_counter()
    last = turn_started

    yield sse("turn_start", {"user_input": message})

    try:
        for output in workflow.stream(inputs, config={"recursion_limit": 50}):
            for node_name, state_update in output.items():
                now = time.perf_counter()
                seq += 1
                path.append(node_name)

                if "final_answer" in state_update:
                    final_answer = state_update["final_answer"]
                if "conversation_history" in state_update:
                    updated_history = state_update["conversation_history"]

                yield sse(
                    "node",
                    {
                        "seq": seq,
                        "node": node_name,
                        "kind": "llm" if node_name in LLM_NODES else "local",
                        "elapsed_ms": round((now - last) * 1000),
                        "state": to_jsonable(state_update),
                    },
                )
                last = now

        yield sse(
            "done",
            {
                "final_answer": final_answer,
                "history": f"{updated_history}\nAssistant: {final_answer}",
                "path": path,
                "total_ms": round((time.perf_counter() - turn_started) * 1000),
                "llm_calls": sum(1 for n in path if n in LLM_NODES),
            },
        )
    except Exception as exc:
        yield sse("error", {"message": f"{type(exc).__name__}: {exc}"})


@api.post("/api/chat")
def chat(request: ChatRequest):
    return StreamingResponse(
        run_turn(request.message, request.history),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@api.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


api.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(api, host="127.0.0.1", port=8000)
