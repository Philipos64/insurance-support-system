/* ============================================================
   Workflow graph — a live view of the LangGraph state machine.

   The topology is fixed and mirrors the edges declared in main.py,
   so this is a picture of the real graph rather than a decoration.
   Nodes light up as execution reaches them and edges mark the path
   actually taken for the current turn.
   ============================================================ */

const NS = "http://www.w3.org/2000/svg";

const NODES = [
  { id: "planner_agent",       label: "planner",     kind: "llm",   x: 296, y: 14,  w: 148 },
  { id: "workflow_dispatcher", label: "dispatcher",  kind: "local", x: 296, y: 100, w: 148 },
  { id: "policy_worker",       label: "policy",      kind: "local", x: 44,  y: 186, w: 132 },
  { id: "billing_worker",      label: "billing",     kind: "local", x: 217, y: 186, w: 132 },
  { id: "claims_worker",       label: "claims",      kind: "local", x: 390, y: 186, w: 132 },
  { id: "rag_specialist",      label: "rag",         kind: "llm",   x: 563, y: 186, w: 132 },
  { id: "answer_agent",        label: "answer",      kind: "llm",   x: 165, y: 282, w: 150 },
  { id: "human_handoff",       label: "handoff",     kind: "local", x: 485, y: 282, w: 150 },
];

const H = 32;

// Edges as declared in main.py. `both` marks the dispatcher<->worker
// pairs, which carry traffic in each direction.
const EDGES = [
  { from: "planner_agent", to: "workflow_dispatcher", d: "M370,46 L370,100" },

  { from: "workflow_dispatcher", to: "policy_worker",  both: true, d: "M370,132 C370,166 110,152 110,186" },
  { from: "workflow_dispatcher", to: "billing_worker", both: true, d: "M370,132 C370,166 283,158 283,186" },
  { from: "workflow_dispatcher", to: "claims_worker",  both: true, d: "M370,132 C370,166 456,158 456,186" },
  { from: "workflow_dispatcher", to: "rag_specialist", both: true, d: "M370,132 C370,166 629,152 629,186" },

  // planner -> answer  (no plan produced)
  { from: "planner_agent", to: "answer_agent",
    d: "M296,30 C168,30 10,66 10,246 C10,290 108,298 165,298" },
  // dispatcher -> answer  (plan complete)
  { from: "workflow_dispatcher", to: "answer_agent",
    d: "M296,116 C214,116 34,148 34,250 C34,288 118,298 165,298" },

  // planner -> handoff  (explicit escalation)
  { from: "planner_agent", to: "human_handoff",
    d: "M444,30 C572,30 730,66 730,246 C730,290 632,298 635,298" },
  // dispatcher -> handoff
  { from: "workflow_dispatcher", to: "human_handoff",
    d: "M444,116 C526,116 706,148 706,250 C706,288 622,298 635,298" },

  { from: "answer_agent",  to: "END", d: "M240,314 C240,344 322,358 368,360" },
  { from: "human_handoff", to: "END", d: "M560,314 C560,344 478,358 432,360" },
];

const key = (a, b) => `${a}>${b}`;

/** A node is only interactive once the current turn has actually run it. */
function attachActivation(g, id) {
  const fire = (event) => {
    if (!g.classList.contains("is-visited")) return;
    if (!onNodeActivate) return;
    event.preventDefault();
    onNodeActivate(id);
  };
  g.addEventListener("click", fire);
  g.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") fire(e);
  });
}

/** Keep focusability in step with whether the node is interactive. */
function setInteractive(g, on) {
  if (on) {
    g.setAttribute("tabindex", "0");
    g.setAttribute("role", "button");
  } else {
    g.removeAttribute("tabindex");
    g.removeAttribute("role");
  }
}

let svg = null;
const nodeEls = new Map();
const edgeEls = new Map();
let previous = null;
let onNodeActivate = null;

function makeDefs() {
  const defs = document.createElementNS(NS, "defs");
  for (const [id, cls] of [["arrow", "arrow-idle"], ["arrow-on", "arrow-live"]]) {
    const m = document.createElementNS(NS, "marker");
    m.setAttribute("id", id);
    m.setAttribute("viewBox", "0 0 8 8");
    m.setAttribute("refX", "7");
    m.setAttribute("refY", "4");
    m.setAttribute("markerWidth", "5");
    m.setAttribute("markerHeight", "5");
    m.setAttribute("orient", "auto-start-reverse");
    const path = document.createElementNS(NS, "path");
    path.setAttribute("d", "M0,0 L8,4 L0,8 z");
    path.setAttribute("class", cls);
    m.append(path);
    defs.append(m);
  }
  return defs;
}

function buildGraph(container) {
  svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", "0 0 740 380");
  svg.setAttribute("class", "graph-svg");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Workflow graph showing the path of the current request");
  svg.append(makeDefs());

  // edges first so nodes paint over them
  for (const e of EDGES) {
    const p = document.createElementNS(NS, "path");
    p.setAttribute("d", e.d);
    p.setAttribute("class", "edge");
    p.setAttribute("marker-end", "url(#arrow)");
    if (e.both) p.setAttribute("marker-start", "url(#arrow)");
    svg.append(p);
    edgeEls.set(key(e.from, e.to), p);
    if (e.both) edgeEls.set(key(e.to, e.from), p);
  }

  for (const n of NODES) {
    const g = document.createElementNS(NS, "g");
    g.setAttribute("class", "gnode");
    g.dataset.kind = n.kind;
    g.dataset.id = n.id;

    const r = document.createElementNS(NS, "rect");
    r.setAttribute("x", n.x); r.setAttribute("y", n.y);
    r.setAttribute("width", n.w); r.setAttribute("height", H);
    r.setAttribute("rx", "4");
    g.append(r);

    const t = document.createElementNS(NS, "text");
    t.setAttribute("x", n.x + n.w / 2);
    t.setAttribute("y", n.y + H / 2 + 4);
    t.setAttribute("text-anchor", "middle");
    t.textContent = n.label;
    g.append(t);

    attachActivation(g, n.id);
    svg.append(g);
    nodeEls.set(n.id, g);
  }

  // terminal marker
  const end = document.createElementNS(NS, "g");
  end.setAttribute("class", "gnode gnode-end");
  const er = document.createElementNS(NS, "rect");
  er.setAttribute("x", "368"); er.setAttribute("y", "348");
  er.setAttribute("width", "64"); er.setAttribute("height", "24");
  er.setAttribute("rx", "12");
  end.append(er);
  const et = document.createElementNS(NS, "text");
  et.setAttribute("x", "400"); et.setAttribute("y", "364");
  et.setAttribute("text-anchor", "middle");
  et.textContent = "END";
  end.append(et);
  attachActivation(end, "END");
  svg.append(end);
  nodeEls.set("END", end);

  container.innerHTML = "";
  container.append(svg);
}

/** Mark one node as the current step, and the edge that led to it. */
function stepGraph(nodeId) {
  const current = nodeEls.get(nodeId);
  if (!current) return;

  for (const el of nodeEls.values()) el.classList.remove("is-current");

  if (previous) {
    const edge = edgeEls.get(key(previous, nodeId));
    if (edge) edge.classList.add("is-live");
  }

  current.classList.add("is-visited", "is-current");
  setInteractive(current, true);
  previous = nodeId;
}

/** Called when a turn finishes, so the terminal node is marked. */
function finishGraph(lastNode) {
  if (lastNode === "answer_agent" || lastNode === "human_handoff") {
    const edge = edgeEls.get(key(lastNode, "END"));
    if (edge) edge.classList.add("is-live");
    const endEl = nodeEls.get("END");
    endEl.classList.add("is-visited");
    setInteractive(endEl, true);
  }
}

/** Clear all highlighting for a new turn. */
function resetGraph() {
  previous = null;
  for (const el of nodeEls.values()) {
    el.classList.remove("is-visited", "is-current");
    setInteractive(el, false);
  }
  for (const el of new Set(edgeEls.values())) el.classList.remove("is-live");
}

/** Register the handler called when a visited node is clicked or keyed. */
function setNodeHandler(fn) { onNodeActivate = fn; }

window.Graph = {
  build: buildGraph,
  step: stepGraph,
  finish: finishGraph,
  reset: resetGraph,
  onNode: setNodeHandler,
};
