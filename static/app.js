/* ============================================================
   Insurance Support System — frontend
   Streams graph events from /api/chat and renders both the
   customer conversation and the developer execution trace.
   ============================================================ */

const $ = (sel) => document.querySelector(sel);

const layout    = $(".layout");
const messages  = $("#messages");
const trace     = $("#trace");
const form      = $("#composer");
const input     = $("#input");
const sendBtn   = $("#send");
const status    = $("#status");
const statusText= $("#status-text");
const showRaw   = $("#show-raw");
const library   = $("#library");
const libTabs   = $("#library-tabs");
const libBlurb  = $("#library-blurb");
const libList   = $("#library-list");
const libToggle = $("#toggle-examples");

let history = "";
let turnCount = 0;
let busy = false;

/* ---------------- small DOM helpers ---------------- */

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;   // textContent: never inject markup
  return node;
}

function field(label, buildValue) {
  const wrap = el("div", "field");
  wrap.append(el("div", "field-label", label));
  wrap.append(buildValue());
  return wrap;
}

function pre(text, wrap = false) {
  const node = el("pre", wrap ? "wrap" : null, text);
  return node;
}

function humanise(node) {
  return node.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/* ---------------- chat ---------------- */

function addMessage(role, text) {
  const row = el("div", `msg ${role}`);
  row.append(el("div", "msg-bubble", text));
  messages.append(row);
  messages.scrollTop = messages.scrollHeight;
  return row;
}

/* ---------------- trace ---------------- */

function startTurn(question) {
  if (turnCount === 0) trace.innerHTML = "";
  turnCount += 1;

  const turn = el("section", "turn");

  const head = el("div", "turn-head");
  const label = el("div", "turn-label");
  label.append(el("span", "turn-n", `Turn ${turnCount}`));
  label.append(el("span", "turn-q", question));
  head.append(label);

  const flow = el("div", "flow");
  head.append(flow);

  const summary = el("div", "turn-summary");
  head.append(summary);

  turn.append(head);
  trace.append(turn);
  trace.scrollTop = trace.scrollHeight;

  return { turn, flow, summary };
}

function addFlowStep(flow, name, kind) {
  if (flow.children.length) flow.append(el("span", "flow-arrow", "→"));
  const step = el("span", "flow-step", name);
  step.dataset.kind = kind;
  flow.append(step);
}

/* Build the readable body for one executed node. */
function nodeBody(name, state) {
  const body = el("div", "node-body");

  if (name === "planner_agent") {
    if (state.justification) {
      body.append(field("Reasoning", () => el("p", null, state.justification)));
    }
    const plan = state.plan || [];
    if (plan.length) {
      body.append(field("Generated plan", () => {
        const list = el("div");
        plan.forEach((step, i) => {
          const row = el("div", "plan-step");
          row.append(el("span", "plan-i", `${i + 1}`));
          row.append(el("span", "plan-agent", step.agent || "?"));
          row.append(el("span", "plan-task", step.task || ""));
          list.append(row);
        });
        return list;
      }));
    } else if (state.next_agent === "end") {
      body.append(field("Outcome", () =>
        el("p", null, "No further work planned — routing straight to the answer agent.")));
    } else {
      body.append(field("Outcome", () =>
        el("p", null, "Plan already in progress — returning to the dispatcher.")));
    }

  } else if (name === "workflow_dispatcher") {
    body.append(field("Dispatching to", () =>
      el("p", null, state.next_agent || "—")));
    if (state.task) {
      body.append(field("Isolated task", () => pre(state.task, true)));
    }
    const left = (state.plan || []).length;
    body.append(field("Remaining in plan", () =>
      el("p", null, left === 0 ? "none — plan complete" : `${left} step${left === 1 ? "" : "s"}`)));

  } else if (["policy_worker", "billing_worker", "claims_worker"].includes(name)) {
    const responses = state.agent_responses || [];
    body.append(field("Database result", () =>
      pre(responses.length ? responses[responses.length - 1] : "(no result)", true)));

  } else if (name === "rag_specialist") {
    body.append(field("Semantic search query", () => pre(state.rag_search_query || "—", true)));
    body.append(field("Retrieved documents", () => pre(state.rag_docs || "(none)", true)));
    const responses = state.agent_responses || [];
    if (responses.length) {
      body.append(field("Summarised answer", () => pre(responses[responses.length - 1], true)));
    }

  } else if (name === "answer_agent") {
    body.append(field("Synthesis", () =>
      el("p", null, "Drafting the final reply from the data collected above.")));
    if (state.final_answer) {
      body.append(field("Final answer", () => pre(state.final_answer, true)));
    }

  } else if (name === "human_handoff") {
    body.append(field("Escalation", () =>
      el("p", null, state.final_answer || "Routing to a human representative.")));
  }

  const raw = el("details", "raw");
  raw.append(el("summary", null, "Raw GraphState"));
  raw.append(pre(JSON.stringify(state, null, 2)));
  body.append(raw);

  return body;
}

function addNode(turn, payload) {
  const card = el("article", "node");
  card.dataset.node = payload.node;

  const head = el("div", "node-head");
  head.append(el("span", "node-seq", String(payload.seq)));
  head.append(el("span", "node-name", humanise(payload.node)));
  head.append(el("span", `badge ${payload.kind}`, payload.kind === "llm" ? "API call" : "local"));
  head.append(el("span", "node-ms", `${payload.elapsed_ms} ms`));
  card.append(head);

  card.append(nodeBody(payload.node, payload.state || {}));
  turn.append(card);
  trace.scrollTop = trace.scrollHeight;
}

function finishTurn(summary, data) {
  summary.innerHTML = "";
  const add = (label, value) => {
    const span = el("span");
    span.append(document.createTextNode(`${label} `));
    span.append(el("b", null, value));
    summary.append(span);
  };
  add("steps", String(data.path.length));
  add("API calls", String(data.llm_calls));
  add("total", `${data.total_ms} ms`);
}

/* ---------------- streaming ---------------- */

async function send(question) {
  if (busy) return;
  busy = true;
  sendBtn.disabled = true;
  libList.querySelectorAll(".q").forEach((b) => (b.disabled = true));
  input.value = "";

  addMessage("user", question);
  const { turn, flow, summary } = startTurn(question);

  status.hidden = false;
  statusText.textContent = "Planning…";

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: question, history }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // SSE frames are separated by a blank line
      const frames = buffer.split("\n\n");
      buffer = frames.pop();

      for (const frame of frames) {
        if (!frame.trim()) continue;
        let event = "message";
        const dataLines = [];
        for (const line of frame.split("\n")) {
          if (line.startsWith("event:")) event = line.slice(6).trim();
          else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
        }
        if (!dataLines.length) continue;
        const data = JSON.parse(dataLines.join("\n"));

        if (event === "node") {
          addFlowStep(flow, data.node, data.kind);
          addNode(turn, data);
          statusText.textContent = `${humanise(data.node)}…`;
        } else if (event === "done") {
          finishTurn(summary, data);
          history = data.history;
          addMessage("assistant", data.final_answer || "(no answer produced)");
        } else if (event === "error") {
          addMessage("error", data.message);
        }
      }
    }
  } catch (err) {
    addMessage("error", `Request failed: ${err.message}`);
  } finally {
    status.hidden = true;
    busy = false;
    sendBtn.disabled = false;
    libList.querySelectorAll(".q").forEach((b) => (b.disabled = false));
    input.focus();
  }
}

/* ---------------- wiring ---------------- */

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const q = input.value.trim();
  if (q) send(q);
});

/* ---------------- example library ---------------- */

let categories = [];

function renderCategory(cat) {
  library.dataset.cat = cat.id;
  libBlurb.textContent = cat.blurb;

  libTabs.querySelectorAll(".tab").forEach((t) =>
    t.classList.toggle("is-active", t.dataset.id === cat.id));

  libList.innerHTML = "";
  cat.questions.forEach((q) => {
    const btn = el("button", "q");
    btn.type = "button";
    btn.append(el("span", "q-text", q.text));
    if (q.note) btn.append(el("span", "q-note", q.note));
    btn.addEventListener("click", () => {
      if (busy) return;
      send(q.text);
    });
    libList.append(btn);
  });
}

async function loadLibrary() {
  try {
    categories = await (await fetch("/api/samples")).json();
  } catch {
    libBlurb.textContent = "Could not load the example questions.";
    return;
  }

  libTabs.innerHTML = "";
  categories.forEach((cat) => {
    const tab = el("button", "tab", cat.label);
    tab.type = "button";
    tab.dataset.id = cat.id;
    tab.addEventListener("click", () => renderCategory(cat));
    libTabs.append(tab);
  });

  if (categories.length) renderCategory(categories[0]);
}

libToggle.addEventListener("click", () => {
  const open = library.hidden;
  library.hidden = !open;
  libToggle.setAttribute("aria-expanded", String(open));
  libToggle.textContent = open ? "Hide examples" : "Examples";
  if (open && !categories.length) loadLibrary();
});

document.querySelectorAll(".view-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".view-btn").forEach((b) => b.classList.remove("is-active"));
    btn.classList.add("is-active");
    layout.dataset.view = btn.dataset.view;
  });
});

showRaw.addEventListener("change", () => {
  trace.classList.toggle("show-raw", showRaw.checked);
});

$("#reset").addEventListener("click", () => {
  if (busy) return;
  history = "";
  turnCount = 0;
  messages.innerHTML = "";
  trace.innerHTML = "";
  const empty = el("div", "empty");
  empty.append(el("p", "empty-title", "No execution yet"));
  empty.append(el("p", "empty-body",
    "Send a message to watch the graph run. Each node appears here as it executes, " +
    "with the plan it produced, the task it received, and what it returned."));
  trace.append(empty);
  greet();
});

function greet() {
  addMessage("assistant", "Hello. I can help with policy details, billing, claims, and general insurance questions. How can I assist you?");
}

greet();
input.focus();
