"""
Compound AI Insurance Support System.
Implements a Plan-and-Execute workflow using LangGraph.
"""

import os
import json
import logging
import chromadb
import re
from typing import TypedDict, Dict, Any, Optional
from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from dotenv import load_dotenv

# Import updated prompts
from prompts import (
    PLANNER_PROMPT, RAG_SPECIALIST_PROMPT, ANSWER_AGENT_PROMPT
)

# Import database tools
from agent_tools import (
    get_policy_details, get_claim_status, get_billing_info, TOOL_SQL
)

# Load environment variables
load_dotenv()

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(name)s - %(message)s')
logger = logging.getLogger("CompoundAISystem")

# Setup LLM
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

# Setup Vector Store (ChromaDB for RAG)
try:
    chroma_client = chromadb.PersistentClient(path="./chroma_db")
    collection = chroma_client.get_collection(name="insurance_FAQ_collection")
except Exception as e:
    logger.warning(f"Vector DB not found or failed to initialize. Error: {e}")

# ==========================================
# STATE DEFINITION
# ==========================================
class GraphState(TypedDict):
    """Represents the state of the graph during execution."""
    user_input: str
    conversation_history: Optional[str]
    n_iteration: Optional[int]
    next_agent: Any

    # Task execution state
    plan: Optional[list]  # Array of pending sub-tasks
    task: Optional[str]   # The current specific task being executed
    agent_responses: Optional[list] # Collected results from workers

    # Routing and synthesis
    justification: Optional[str]
    final_answer: Optional[str]

    # Debug / Trace variables
    rag_search_query: Optional[str]
    rag_docs: Optional[str]

    # Per-node inspection record: what the node received and did, as opposed
    # to what it returned. Consumed by the developer view; the graph itself
    # never reads it.
    detail: Optional[Dict[str, Any]]

# ==========================================
# WORKFLOW NODES
# ==========================================

def planner_agent_node(state: GraphState):
    """
    Acts as the semantic routing brain. Generates a 'plan' array of isolated tasks.
    """
    n_iter = state.get("n_iteration", 0) + 1

    # Safety mechanism to prevent infinite loops
    if n_iter > 7:
        logger.warning("Max iterations reached. Escalating to human.")
        return {"next_agent": "human_handoff", "n_iteration": n_iter}

    history = state.get("conversation_history", f"User: {state['user_input']}")
    current_plan = state.get("plan", [])
    agent_responses = state.get("agent_responses", [])

    # Logic: If a plan is already in progress, route back to the dispatcher
    if current_plan and len(current_plan) > 0:
        return {
            "next_agent": "workflow_dispatcher",
            "n_iteration": n_iter,
            "conversation_history": history
        }

    # Logic: If the plan is empty but we have collected data, the task is complete
    if not current_plan and len(agent_responses) > 0:
        return {
            "next_agent": "end",
            "n_iteration": n_iter,
            "conversation_history": history
        }

    # If no active plan, prompt the LLM to create one
    prompt = PLANNER_PROMPT.format(conversation_history=history)
    messages = [
        SystemMessage(content=prompt),
        HumanMessage(content="Analyze the conversation history and create a routing plan.")
    ]

    try:
        response = llm.invoke(messages)
        content = response.content.replace("```json", "").replace("```", "").strip()
        decision = json.loads(content)

        plan = decision.get("plan", [])

        # Handle termination edge case
        if not plan or plan[0].get("agent") == "end":
            return {"next_agent": "end", "n_iteration": n_iter, "conversation_history": history, "plan": []}

        agent_names = [step.get("agent") for step in plan]

        return {
            "next_agent": agent_names,
            "plan": plan,
            "justification": decision.get("justification"),
            "n_iteration": n_iter,
            "conversation_history": history,
            "detail": {
                "role": "Routes the request. Produces a plan as data; executes nothing.",
                "model": llm.model_name,
                "system_prompt": prompt,
                "user_message": "Analyze the conversation history and create a routing plan.",
                "raw_response": response.content,
                "parsed_plan": plan,
            },
        }
    except Exception as e:
        logger.error(f"Planner parsing error: {e}")
        return {"next_agent": "answer_agent", "n_iteration": n_iter}

def workflow_dispatcher_node(state: GraphState):
    """
    Task Dispatcher. Pops the first task from the plan array and assigns
    it exclusively to the designated deterministic worker.
    """
    current_plan = state.get("plan", [])

    if len(current_plan) > 0:
        current_step = current_plan[0]
        first_agent = current_step.get("agent")
        specific_task = current_step.get("task")

        remaining_plan = current_plan[1:]

        return {
            "next_agent": first_agent,
            "task": specific_task,
            "plan": remaining_plan,
            "detail": {
                "role": "Pops one task off the plan and routes it. Pure Python, no model.",
                "plan_before": current_plan,
                "popped": current_step,
                "plan_after": remaining_plan,
                "routed_to": first_agent,
            },
        }

    return {
        "next_agent": "answer_agent",
        "detail": {
            "role": "Pops one task off the plan and routes it. Pure Python, no model.",
            "plan_before": current_plan,
            "popped": None,
            "plan_after": [],
            "routed_to": "answer_agent",
            "note": "Plan is empty - every task has run, so the turn moves to synthesis.",
        },
    }

def policy_worker_node(state: GraphState):
    """Deterministic worker node using Regex and Postgres for Policy details."""
    history = state.get("conversation_history", "")
    task = state.get("task", "")

    pol_matches = re.findall(r"POL\d+", task)
    clm_match = re.search(r"CLM\d+", task)

    result_texts = []
    lookups = []

    if pol_matches:
        for policy_num in pol_matches:
            try:
                info = get_policy_details(policy_number=policy_num)
                lookups.append({"params": [policy_num], "result": info})
                if "error" in info:
                    result_texts.append(f"Error for {policy_num}: {info['error']}")
                else:
                    result_texts.append(
                        f"Policy Details for {policy_num}:\n"
                        f"- Type: {info.get('type')}\n"
                        f"- Status: {info.get('status')}\n"
                        f"- Owner: {info.get('customer_name')}\n"
                        f"- Email: {info.get('email')}"
                    )
            except Exception as e:
                result_texts.append(f"System Error for {policy_num}: {e}")

        final_result_text = "\n\n".join(result_texts)

    elif clm_match:
        claim_id = clm_match.group(0)
        final_result_text = f"I see you provided a Claim ID ({claim_id}), but I need a Policy number (starting with POL) to look up general policy details."
    else:
        final_result_text = "I need a policy number (e.g., POL000001) to look up details."

    return {
        "conversation_history": history + f"\nPolicy Worker: {final_result_text}",
        "agent_responses": state.get("agent_responses", []) + [final_result_text],
            "detail": {
                "role": "Deterministic worker. Extracts an ID by regex, then runs one "
                        "fixed parameterised statement. No model call, no generated SQL.",
                "task_received": task,
                "regex": r"POL\d+",
                "ids_extracted": pol_matches,
                "tool": "get_policy_details",
                "sql": TOOL_SQL["get_policy_details"],
                "rows": lookups,
                "formatted_output": final_result_text,
            },
    }

def billing_worker_node(state: GraphState):
    """Deterministic worker node using Regex and Postgres for Billing details."""
    history = state.get("conversation_history", "")
    task = state.get("task", "")

    pol_matches = re.findall(r"POL\d+", task)
    clm_match = re.search(r"CLM\d+", task)

    result_texts = []
    lookups = []

    if pol_matches:
        for policy_num in pol_matches:
            try:
                info = get_billing_info(policy_number=policy_num)
                lookups.append({"params": [policy_num], "result": info})
                if "error" in info:
                    result_texts.append(f"Billing Info for {policy_num}: {info['error']}")
                else:
                    result_texts.append(
                        f"Billing Details for {policy_num}:\n"
                        f"- Status: {info.get('status')}\n"
                        f"- Amount Due: ${info.get('amount_due')}\n"
                        f"- Due Date: {info.get('due_date')}"
                    )
            except Exception as e:
                result_texts.append(f"System Error for {policy_num}: {e}")

        final_result_text = "\n\n".join(result_texts)

    elif clm_match:
        claim_id = clm_match.group(0)
        final_result_text = f"I see you want billing info for a claim ({claim_id}), but billing requires a Policy number (POL...). Please provide it."
    else:
        final_result_text = "I could not find a valid Policy number (POL...) in the request."

    return {
        "conversation_history": history + f"\nBilling Worker: {final_result_text}",
        "agent_responses": state.get("agent_responses", []) + [final_result_text],
            "detail": {
                "role": "Deterministic worker. Extracts an ID by regex, then runs one "
                        "fixed parameterised statement. No model call, no generated SQL.",
                "task_received": task,
                "regex": r"POL\d+",
                "ids_extracted": pol_matches,
                "tool": "get_billing_info",
                "sql": TOOL_SQL["get_billing_info"],
                "rows": lookups,
                "formatted_output": final_result_text,
            },
    }

def claims_worker_node(state: GraphState):
    """Deterministic worker node using Regex and Postgres for Claim status."""
    history = state.get("conversation_history", "")
    task = state.get("task", "")

    claim_matches = re.findall(r"CLM\d+", task)
    policy_matches = re.findall(r"POL\d+", task)

    result_texts = []
    lookups = []

    # 1. Look up by Claim ID
    if claim_matches:
        for claim_id in claim_matches:
            try:
                info = get_claim_status(claim_id=claim_id)
                if "error" in info:
                    result_texts.append(f"Error for {claim_id}: {info['error']}")
                else:
                    # Format with line breaks, consistent with the policy and billing workers
                    result_texts.append(
                        f"Claim Details for {claim_id}:\n"
                        f"- Type: {str(info.get('type', 'N/A')).title()}\n"
                        f"- Status: {str(info.get('status', 'N/A')).title()}\n"
                        f"- Amount: ${info.get('amount', '0.00')}"
                    )
            except Exception as e:
                result_texts.append(f"System Error for {claim_id}: {e}")

    # 2. Look up by Policy Number (fallback)
    if policy_matches:
        for policy_num in policy_matches:
            try:
                info = get_claim_status(policy_number=policy_num)
                lookups.append({"params": [policy_num], "via": "by policy_number", "result": info})
                if isinstance(info, list):
                    claims_str = "\n".join([f" - {c.get('claim_id')}: {str(c.get('status')).title()} (${c.get('amount')})" for c in info])
                    result_texts.append(f"Recent Claims for {policy_num}:\n{claims_str}")
                elif isinstance(info, dict) and "error" not in info:
                     result_texts.append(
                        f"Claim Details for {policy_num}:\n"
                        f"- Type: {str(info.get('type', 'N/A')).title()}\n"
                        f"- Status: {str(info.get('status', 'N/A')).title()}\n"
                        f"- Amount: ${info.get('amount', '0.00')}"
                    )
                else:
                    result_texts.append(f"Recent Claims for {policy_num}: {info}")
            except Exception as e:
                result_texts.append(f"System Error for {policy_num}: {e}")

    if result_texts:
        final_result_text = "\n\n".join(result_texts)
    else:
        final_result_text = "I need a Claim ID (CLM...) or Policy Number (POL...) to check status."

    return {
        "conversation_history": history + f"\nClaims Worker: {final_result_text}",
        "agent_responses": state.get("agent_responses", []) + [final_result_text],
        "detail": {
            "role": "Deterministic worker. Extracts an ID by regex, then runs one "
                    "fixed parameterised statement. No model call, no generated SQL.",
            "task_received": task,
            "regex": r"CLM\d+ | POL\d+",
            "ids_extracted": claim_matches + policy_matches,
            "tool": "get_claim_status",
            "sql": TOOL_SQL["get_claim_status"],
            "rows": lookups,
            "formatted_output": final_result_text,
        },
    }

def rag_specialist_node(state: GraphState):
    """RAG-based AI worker node using ChromaDB for general inquiries."""
    task = state.get("task", "")
    history = state.get("conversation_history", "")

    # --- OPTIMIZATION: Skipping the LLM call for query generation! ---
    # Since the Planner Agent has already perfectly isolated the task,
    # we can use the 'task' string directly as our semantic search query.
    search_query = task
    logger.info(f"RAG query: {search_query}")

    # 1. Retrieve documents (Directly against ChromaDB)
    results = collection.query(query_texts=[search_query], n_results=4)

    context = ""
    if results['documents']:
        for i, doc in enumerate(results['documents'][0]):
            context += f"FAQ {i+1}: {doc}\n"

    # 2. Generate summarized answer (This is now the ONLY API call in this node!)
    prompt = RAG_SPECIALIST_PROMPT.format(task=task, faq_context=context)
    response = llm.invoke([SystemMessage(content=prompt)])

    return {
        "conversation_history": history + f"\nRAG Specialist: {response.content}",
        "agent_responses": state.get("agent_responses", []) + [response.content],
        "rag_search_query": search_query,
        "rag_docs": context,
        "detail": {
            "role": "Vector search over the FAQ store, then one model call to summarise. "
                    "The planner already shaped the task into a keyword query, so no "
                    "query-rewriting call is needed.",
            "model": llm.model_name,
            "task_received": task,
            "search_query": search_query,
            "n_results": 4,
            "retrieved_documents": results["documents"][0] if results.get("documents") else [],
            "system_prompt": prompt,
            "raw_response": response.content,
        },
    }


def human_handoff_node(state: GraphState):
    """Handles explicit requests for human representatives.

    Deliberately deterministic: escalation is a fixed response, not a
    generated one. There is nothing for a model to decide here, and a
    guaranteed message is worth more than a fluent one.
    """
    msg = "I understand. I will transfer you to a human representative immediately."
    return {
        "final_answer": msg,
        "detail": {
            "role": "Escalation. A fixed string, deliberately not generated - there is "
                    "nothing for a model to decide, and a guaranteed message is worth "
                    "more than a fluent one.",
            "model": None,
            "response": msg,
        },
    }

def answer_agent_node(state: GraphState):
    """Synthesizes the collected data into a conversational response."""
    if state.get("final_answer"):
        return {}

    agent_responses = state.get("agent_responses", [])

    if len(agent_responses) > 0:
        specialist_response = "\n\n".join(agent_responses)
    else:
        specialist_response = state.get("conversation_history", "")

    prompt = ANSWER_AGENT_PROMPT.format(
        user_query=state["user_input"],
        specialist_response=specialist_response
    )

    response = llm.invoke([SystemMessage(content=prompt)])
    return {
        "final_answer": response.content,
        "detail": {
            "role": "Synthesises the reply. Sees the user question and the workers' "
                    "results - never the conversation history, and never the tools.",
            "model": llm.model_name,
            "context_received": agent_responses,
            "context_source": ("worker results" if agent_responses
                               else "conversation history (no worker ran)"),
            "system_prompt": prompt,
            "raw_response": response.content,
        },
    }


# ==========================================
# GRAPH ROUTING AND EXECUTION
# ==========================================
workflow = StateGraph(GraphState)

# Add Nodes
workflow.add_node("planner_agent", planner_agent_node)
workflow.add_node("workflow_dispatcher", workflow_dispatcher_node)
workflow.add_node("policy_worker", policy_worker_node)
workflow.add_node("billing_worker", billing_worker_node)
workflow.add_node("claims_worker", claims_worker_node)
workflow.add_node("rag_specialist", rag_specialist_node)
workflow.add_node("human_handoff", human_handoff_node)
workflow.add_node("answer_agent", answer_agent_node)

workflow.set_entry_point("planner_agent")

def route_planner(state):
    """Determines where the Planner should send the state next."""
    next_node = state.get("next_agent")

    if isinstance(next_node, list):
        return "workflow_dispatcher"
    elif next_node == "end" or next_node is None:
        return "answer_agent"

    return next_node

# Edges from Planner
workflow.add_conditional_edges(
    "planner_agent",
    route_planner,
    {
        "human_handoff": "human_handoff",
        "answer_agent": "answer_agent",
        "workflow_dispatcher": "workflow_dispatcher"
    }
)

# Edges from Dispatcher
workflow.add_conditional_edges(
    "workflow_dispatcher",
    lambda x: x["next_agent"],
    {
        "policy_worker": "policy_worker",
        "billing_worker": "billing_worker",
        "claims_worker": "claims_worker",
        "rag_specialist": "rag_specialist",
        "human_handoff": "human_handoff",
        "answer_agent": "answer_agent"
    }
)

# Return Edges
workflow.add_edge("policy_worker", "workflow_dispatcher")
workflow.add_edge("billing_worker", "workflow_dispatcher")
workflow.add_edge("claims_worker", "workflow_dispatcher")
workflow.add_edge("rag_specialist", "workflow_dispatcher")

# Terminal Edges
workflow.add_edge("answer_agent", END)
workflow.add_edge("human_handoff", END)

# Compile Graph
app = workflow.compile()