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
const graphBox  = $("#graph");
const showGraph = $("#show-graph");
const chatPanel = $(".chat-panel");
const inspectPanel = $("#inspect");
const inspectBody = $("#inspect-body");

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

/* Cards rendered for the turn the graph currently represents, keyed by node.
   A node can run several times in one turn - the dispatcher usually runs three
   times - so each key holds every occurrence, in execution order. */
let turnCards = new Map();
let cycleIndex = new Map();
let currentTurnEl = null;

function startTurn(question) {
  closeInspect();
  Graph.reset();
  turnCards = new Map();
  cycleIndex = new Map();
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
  currentTurnEl = turn;
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

  if (payload.detail) {
    const btn = el("button", "inspect-btn", "Inspect");
    btn.type = "button";
    btn.title = "See what this step received and did";
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      openInspect(payload);
    });
    head.append(btn);
  }

  card.append(head);

  card.append(nodeBody(payload.node, payload.state || {}));
  turn.append(card);

  if (!turnCards.has(payload.node)) turnCards.set(payload.node, []);
  turnCards.get(payload.node).push(card);

  trace.scrollTop = trace.scrollHeight;
}

/* ---------------- graph -> log navigation ---------------- */

function flash(card) {
  // clear every previous target, not just this one, or stale rings accumulate
  trace.querySelectorAll(".node.is-target").forEach((c) => c.classList.remove("is-target"));
  void card.offsetWidth;          // restart the animation
  card.classList.add("is-target");
}

function scrollTraceTo(card) {
  // The turn header is sticky, so measure it rather than guessing a gap -
  // its height varies with how far the flow chain wraps.
  const head = card.closest(".turn")?.querySelector(".turn-head");
  const clearance = (head ? head.getBoundingClientRect().height : 0) + 10;

  const cardRect = card.getBoundingClientRect();
  const traceRect = trace.getBoundingClientRect();
  trace.scrollTop += cardRect.top - traceRect.top - clearance;
}

function jumpToNode(nodeId) {
  let cards = turnCards.get(nodeId);

  // END has no card of its own - send it to the final step of the turn.
  // Read it from the DOM rather than the registry, whose key order is
  // first-occurrence order and need not end with the last node to run.
  if (nodeId === "END" && !cards) {
    const steps = currentTurnEl ? currentTurnEl.querySelectorAll(".node") : [];
    cards = steps.length ? [steps[steps.length - 1]] : null;
  }
  if (!cards || !cards.length) return;

  const next = (cycleIndex.get(nodeId) ?? -1) + 1;
  const i = next % cards.length;
  cycleIndex.set(nodeId, i);

  const card = cards[i];
  if (!card.isConnected) return;   // trace was cleared underneath us

  scrollTraceTo(card);
  flash(card);

  if (cards.length > 1) showOccurrence(card, i + 1, cards.length);
}

/** Transient "2 / 3" marker so cycling through repeats is legible. */
function showOccurrence(card, n, total) {
  const head = card.querySelector(".node-head");
  if (!head) return;
  head.querySelectorAll(".occurrence").forEach((e) => e.remove());
  const tag = el("span", "occurrence", `${n} / ${total}`);
  head.append(tag);
  setTimeout(() => tag.remove(), 1800);
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


/* ---------------- step inspector ---------------- */

/** Render one labelled block. `mono` renders the value as preformatted text. */
function block(label, value, { mono = true, note = "" } = {}) {
  const wrap = el("div", "ins-block");
  wrap.append(el("div", "ins-label", label));
  if (note) wrap.append(el("p", "ins-note", note));
  if (value === null || value === undefined || value === "") {
    wrap.append(el("p", "ins-empty", "(none)"));
  } else if (mono) {
    wrap.append(pre(typeof value === "string" ? value : JSON.stringify(value, null, 2), true));
  } else {
    wrap.append(el("p", "ins-text", String(value)));
  }
  return wrap;
}


/** Strip the common leading indentation off a block of text. */
function dedent(text) {
  const lines = String(text).replace(/\t/g, "    ").split("\n");
  const indents = lines.filter((l) => l.trim()).map((l) => l.match(/^ */)[0].length);
  const cut = indents.length ? Math.min(...indents) : 0;
  return lines.map((l) => l.slice(cut)).join("\n").trim();
}

/** SQL arrives as {label: statement}. Render each readably, not as JSON. */
function sqlBlocks(sqlMap, note) {
  const wrap = el("div", "ins-block");
  wrap.append(el("div", "ins-label", "SQL it can run"));
  if (note) wrap.append(el("p", "ins-note", note));
  const entries = Object.entries(sqlMap || {});
  if (!entries.length) {
    wrap.append(el("p", "ins-empty", "(none)"));
    return wrap;
  }
  for (const [label, sql] of entries) {
    wrap.append(el("div", "ins-sublabel", label));
    wrap.append(pre(dedent(sql)));
  }
  return wrap;
}

function renderDetail(node, d) {
  const out = document.createDocumentFragment();

  out.append(block("What this step is", d.role, { mono: false }));
  if (d.model) out.append(block("Model", d.model, { mono: false }));
  else if ("model" in d) out.append(block("Model", "none - this step runs no model", { mono: false }));

  if (node === "planner_agent") {
    out.append(block("Prompt sent", d.system_prompt,
      { note: "The full system prompt. The conversation is interpolated into it." }));
    out.append(block("User message", d.user_message));
    out.append(block("Raw model response", d.raw_response,
      { note: "Parsed as strict JSON. A parse failure routes straight to the answer agent." }));
    out.append(block("Parsed plan", d.parsed_plan,
      { note: "This is data, produced before anything executes." }));

  } else if (node === "workflow_dispatcher") {
    if (d.note) out.append(block("Note", d.note, { mono: false }));
    out.append(block("Plan before", d.plan_before));
    out.append(block("Task taken", d.popped));
    out.append(block("Plan after", d.plan_after));
    out.append(block("Routed to", d.routed_to, { mono: false }));

  } else if (node.endsWith("_worker")) {
    out.append(block("Task received", d.task_received,
      { note: "The only input. The worker never sees the conversation." }));
    out.append(block("Extraction pattern", d.regex));
    out.append(block("IDs extracted", d.ids_extracted));
    out.append(block("Tool", d.tool, { mono: false }));
    out.append(sqlBlocks(d.sql,
      "Fixed statements, parameterised with %s. Nothing is generated or concatenated."));
    out.append(block("Query parameters and rows", d.rows,
      { note: "What was bound as a value, and what came back." }));
    out.append(block("Formatted output", d.formatted_output));

  } else if (node === "rag_specialist") {
    out.append(block("Task received", d.task_received));
    out.append(block("Search query", d.search_query,
      { note: "Used verbatim against the vector store - the planner already shaped it into keywords." }));
    out.append(block(`Retrieved documents (top ${d.n_results})`, d.retrieved_documents));
    out.append(block("Prompt sent", d.system_prompt));
    out.append(block("Raw model response", d.raw_response));

  } else if (node === "answer_agent") {
    out.append(block("Context received", d.context_received,
      { note: `Source: ${d.context_source}. This is everything the answer agent can see.` }));
    out.append(block("Prompt sent", d.system_prompt,
      { note: "User text sits inside <user_input> and is framed as untrusted data." }));
    out.append(block("Raw model response", d.raw_response));

  } else if (node === "human_handoff") {
    out.append(block("Response", d.response,
      { note: "Returned verbatim. No model call." }));

  } else {
    out.append(block("Detail", d));
  }
  return out;
}

function openInspect(payload) {
  inspectBody.innerHTML = "";

  const head = el("div", "ins-head");
  head.append(el("span", "node-seq", `Step ${payload.seq}`));
  head.append(el("span", "ins-name", humanise(payload.node)));
  head.append(el("span", `badge ${payload.kind}`, payload.kind === "llm" ? "API call" : "local"));
  head.append(el("span", "node-ms", `${payload.elapsed_ms} ms`));
  inspectBody.append(head);

  try {
    inspectBody.append(renderDetail(payload.node, payload.detail || {}));
  } catch (err) {
    inspectBody.append(block("Could not render this step", String(err), { mono: false }));
    inspectBody.append(block("Raw detail", payload.detail));
  }

  inspectBody.scrollTop = 0;
  chatPanel.hidden = true;
  inspectPanel.hidden = false;
}

function closeInspect() {
  inspectPanel.hidden = true;
  chatPanel.hidden = false;
}

$("#inspect-close").addEventListener("click", closeInspect);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !inspectPanel.hidden) closeInspect();
});

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
          Graph.step(data.node);
          addFlowStep(flow, data.node, data.kind);
          addNode(turn, data);
          statusText.textContent = `${humanise(data.node)}…`;
        } else if (event === "done") {
          Graph.finish(data.path[data.path.length - 1]);
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
  turnCards = new Map();
  cycleIndex = new Map();
  currentTurnEl = null;
  Graph.reset();
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

Graph.build(graphBox);
Graph.onNode(jumpToNode);

/* graph visibility, remembered between sessions */
function applyGraphVisibility(visible) {
  graphBox.hidden = !visible;
  try { localStorage.setItem("showGraph", visible ? "1" : "0"); } catch {}
}

showGraph.addEventListener("change", () => applyGraphVisibility(showGraph.checked));

try {
  const saved = localStorage.getItem("showGraph");
  if (saved !== null) showGraph.checked = saved === "1";
} catch {}
applyGraphVisibility(showGraph.checked);
