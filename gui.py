#streamlit run gui.py
import streamlit as st
import json
import time
from main import app

# =========================================================
# 1. PAGE CONFIG & STYLING
# =========================================================
st.set_page_config(page_title="Compound AI Support System", layout="wide")

st.markdown("""
<style>
    .ai-advice {
        background-color: #1a252f;
        border-left: 5px solid #00CC96;
        padding: 20px;
        border-radius: 5px;
        margin-bottom: 25px;
    }
    .queue-box {
        color: #ffcc00;
        font-size: 0.9em;
        margin-top: 5px;
    }
</style>
""", unsafe_allow_html=True)

# =========================================================
# 2. STATE MANAGEMENT
# =========================================================
if "session_history" not in st.session_state:
    st.session_state.session_history = ""

if "chat_messages" not in st.session_state:
    st.session_state.chat_messages = [{"role": "assistant", "content": "Hello! I am your AI insurance agent. How can I assist you today?"}]

if "trace_history" not in st.session_state:
    st.session_state.trace_history = []

# =========================================================
# 3. SIDEBAR & ARCHITECTURE VISUALIZATION
# =========================================================
with st.sidebar:
    st.header("System Architecture")
    st.caption("Plan-and-Execute workflow using LangGraph")

    try:
        st.image("architecture.png", width="stretch")
    except FileNotFoundError:
        st.warning("Please place 'architecture.png' in the root directory to view the flowchart.")

    st.divider()
    st.header("Developer Tools")

    debug_mode = st.radio(
        "Select View Mode:",
        ["Hidden", "Standard Trace", "Super Debugger"],
        index=1
    )

    st.divider()
    if st.button("Clear Conversation"):
        st.session_state.session_history = ""
        st.session_state.chat_messages = [{"role": "assistant", "content": "Hello! How can I assist you today?"}]
        st.session_state.trace_history = []
        st.rerun()

# =========================================================
# 4. MAIN INTERFACE
# =========================================================
st.title("Compound AI Insurance Support")
st.caption("End-to-End Orchestration with LangGraph, PostgreSQL, and ChromaDB")

layout_container = st.container()
chat_col, trace_col = layout_container.columns([1, 1] if debug_mode != "Hidden" else [1, 0.01])

with chat_col:
    st.subheader("Customer Interface")
    chat_container = st.container(height=500)
    with chat_container:
        for msg in st.session_state.chat_messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

# =========================================================
# 5. BOTTOM-PINNED CHAT INPUT
# =========================================================
user_input = st.chat_input("E.g., How much is the bill for POL000001 and how do I pay it?")

if user_input:
    st.session_state.chat_messages.append({"role": "user", "content": user_input})
    with chat_col:
        with chat_container:
            with st.chat_message("user"):
                st.markdown(user_input)

    current_conversation = st.session_state.session_history + f"\nUser: {user_input}"
    inputs = {
        "user_input": user_input,
        "conversation_history": current_conversation,
        "n_iteration": 0,
        "agent_responses": [],
        "plan": []
    }

    with chat_col:
        with chat_container:
            with st.chat_message("assistant"):
                final_answer = ""
                new_history = current_conversation

                status_text = st.empty()
                status_text.info("System is analyzing the request...")

                with trace_col:
                    if debug_mode != "Hidden":
                        st.subheader(f"Execution Log: {debug_mode}")
                        trace_container = st.container(height=500)

                        def render_trace_block(node_name, state_update, mode):
                            with st.expander(f"Executed Node: {node_name.replace('_', ' ').title()}", expanded=True):

                                # --- SUPER DEBUGGER: API vs LOCAL HIGHLIGHT ---
                                if mode == "Super Debugger":
                                    if node_name in ["planner_agent", "rag_specialist", "answer_agent"]:
                                        st.caption("Execution Type: **[API CALL - OPENAI]**")
                                    else:
                                        st.caption("Execution Type: **[LOCAL EXECUTION - PYTHON]**")
                                    st.divider()

                                # --- STANDARD TRACE INFO ---
                                if node_name == "planner_agent":
                                    st.markdown("**Planner Reasoning:**")
                                    st.info(state_update.get('justification', 'No justification provided.'))

                                    plan = state_update.get('plan', [])
                                    if plan:
                                        st.markdown("**Generated Plan:**")
                                        # Render the JSON plan as a formatted code block
                                        st.code(json.dumps(plan, indent=2), language="json")
                                    else:
                                        st.markdown(f"**Assigned Task:** {state_update.get('task', 'N/A')}")

                                elif node_name == "workflow_dispatcher":
                                    st.markdown("**Dispatch Status:**")
                                    dispatch_info = {
                                        "Dispatching to": state_update.get('next_agent'),
                                        "Isolated Task": state_update.get('task', 'N/A'),
                                        "Tasks Remaining in Plan": len(state_update.get('plan', []))
                                    }
                                    # Render the dispatcher state as formatted JSON
                                    st.code(json.dumps(dispatch_info, indent=2), language="json")

                                elif node_name == "rag_specialist":
                                    st.markdown("**Semantic Search Query:**")
                                    st.code(state_update.get("rag_search_query", "N/A"), language="text")
                                    st.markdown("**Retrieved FAQ Documents (ChromaDB):**")
                                    st.code(state_update.get('rag_docs', 'None found'), language="text")

                                elif node_name in ["policy_worker", "billing_worker", "claims_worker"]:
                                    st.markdown("**Database Result:**")
                                    responses = state_update.get('agent_responses', [])
                                    if responses:
                                        st.code(responses[-1], language="text")

                                elif node_name == "human_handoff":
                                    st.error("Routing to Human Queue...")
                                    st.success("Connected to Live Support")

                                elif node_name == "answer_agent":
                                    st.success("Drafting final response based on the collected data above.")

                                # --- SUPER DEBUGGER: RAW JSON GRAPHSTATE ---
                                if mode == "Super Debugger":
                                    st.divider()
                                    st.markdown("**Raw GraphState Data:**")
                                    st.json(state_update)

                        with trace_container:
                            for step in st.session_state.trace_history:
                                render_trace_block(step["node"], step["state"], debug_mode)

                try:
                    for output in app.stream(inputs, config={"recursion_limit": 50}):
                        for node_name, state_update in output.items():
                            st.session_state.trace_history.append({"node": node_name, "state": state_update})

                            if debug_mode != "Hidden":
                                with trace_col:
                                    with trace_container:
                                        render_trace_block(node_name, state_update, debug_mode)

                            if "final_answer" in state_update:
                                final_answer = state_update["final_answer"]
                            if "conversation_history" in state_update:
                                new_history = state_update["conversation_history"]

                    status_text.empty()

                    st.markdown(f"""
                    <div class="ai-advice">
                        {final_answer}
                    </div>
                    """, unsafe_allow_html=True)

                    st.session_state.chat_messages.append({"role": "assistant", "content": final_answer})
                    st.session_state.session_history = new_history + f"\nAssistant: {final_answer}"

                except Exception as e:
                    status_text.error(f"Execution Error: {e}")
