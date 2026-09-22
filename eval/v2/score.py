"""
Score v2 runs: per slice, with confidence intervals and a paired comparison.

Reuses `score_row` from eval/score.py, so a pass means the same thing it did
in v1: right routes, right facts from SQL, right behaviour, nothing leaked.
Adds retrieval (was the FAQ document the question came from in the top 4?),
Wilson intervals on the headline rates, and McNemar's exact test between
systems, which is the right test when every system saw the same questions.

    python eval/v2/score.py --split dev            # while iterating
    python eval/v2/score.py --split test           # once per candidate
    python eval/v2/score.py --systems new jev      # default
"""

import argparse
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import score as v1  # noqa: E402  (eval/score.py)

# v2.1: the first dev run showed two blind spots in the v1 matcher, both of
# which penalise every system identically. Swedish paraphrases were answered
# in Swedish, so each English fact carries its Swedish forms; and "cannot be
# found" was not on the not-found list. Nothing here favours one system.
FACT_SYNONYMS = {
    "active": ["aktiv", "gällande", "i kraft"],
    "cancelled": ["canceled", "cancellation", "avbruten", "avslutad", "uppsagd", "annullerad", "inaktiv"],
    "denied": ["denial", "nekad", "nekats", "avvisad", "avslagen", "avslogs", "avböjd"],
    "approved": ["approval", "godkänd", "godkänt", "godkänts", "beviljad"],
    "paid": ["betald", "betalad", "utbetald", "betalats", "utbetalats"],
    "submitted": ["submission", "inskickad", "inlämnad", "skickad", "inskickat", "inlämnat"],
    "under_review": ["under review", "being reviewed", "in review", "under granskning", "granskas", "under utredning", "utreds", "behandlas", "under behandling"],
    "home": ["hemförsäkring", "hem", "villaförsäkring", "bostad", "homeowner"],
    "auto": ["bilförsäkring", "bil", "fordon", "motorförsäkring", "car", "vehicle"],
    "life": ["livförsäkring", "liv"],
    "theft": ["stöld"], "fire": ["brand"], "medical": ["medicinsk", "sjukvård"], "liability": ["ansvar"],
    "collision": ["kollision"], "vandalism": ["skadegörelse"], "water damage": ["vattenskada"],
}
EXTRA_NOT_FOUND = ["cannot be found", "can't be found", "could not be found", "couldn't be found", "not be found",
                   "no such", "not on file", "not recognised", "not recognized", "does not appear", "doesn't appear",
                   "inte hittas", "inte hittades", "hittades inte", "hittar inte", "finns inte", "finns ingen", "ingen registrerad",
                   "inga uppgifter", "ingen information", "saknas", "kunde inte hitta", "kan inte hitta", "inte hitta", "inte finns", "inte existerar"]
EXTRA_ASK = ["försäkringsnummer", "policynummer", "skadenummer", "ärendenummer", "ange ditt", "vänligen ange", "behöver ditt",
             "which policy", "what policy", "your policy id", "your claim id", "the policy id", "the claim id", "policy or claim"]
v1.NOT_FOUND_PHRASES.extend(p for p in EXTRA_NOT_FOUND if p not in v1.NOT_FOUND_PHRASES)
v1.ASK_PHRASES.extend(p for p in EXTRA_ASK if p not in v1.ASK_PHRASES)


def widen_facts(item):
    """Return a copy of the item whose fact groups also accept the synonyms."""
    groups = []
    for group in item.get("expected_facts", []):
        seen = list(group)
        for variant in group:
            for syn in FACT_SYNONYMS.get(variant.lower(), []):
                if syn not in seen:
                    seen.append(syn)
        groups.append(seen)
    return {**item, "expected_facts": groups}


def score_row(row, item):
    return v1.score_row(row, widen_facts(item))

RESULTS = HERE / "results"
LABELS = {"old": "supervisor", "new": "workflow", "jev": "jev planner"}
SLICE_ORDER = ["single_lookup", "not_found", "multi_lookup", "lookup_plus_faq", "knowledge", "vague_or_odd_id",
               "multiturn", "escalation", "non_task", "injection", "known_gap"]


def load(system):
    path = RESULTS / f"{system}.jsonl"
    rows = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return rows


def wilson(k, n, z=1.96):
    """95% Wilson score interval for a proportion."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def mcnemar_exact(b, c):
    """Two-sided exact McNemar p-value from the discordant counts."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def pct(k, n):
    return f"{100 * k / n:5.1f}%" if n else "    -"


def ci(k, n):
    lo, hi = wilson(k, n)
    return f"[{100 * lo:4.1f}, {100 * hi:5.1f}]" if n else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--systems", nargs="+", default=["new", "jev"])
    ap.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    ap.add_argument("--questions", default=str(HERE / "questions.json"))
    args = ap.parse_args()

    spec = json.load(open(args.questions, encoding="utf-8"))
    items = {it["id"]: it for it in spec["items"] if args.split == "all" or it["split"] == args.split}
    systems = [s for s in args.systems if load(s)]
    if not systems:
        print("No results in eval/v2/results/. Run eval/run_system.py with --questions eval/v2/questions.json first.")
        return
    labels = [LABELS.get(s, s) for s in systems]

    scored = defaultdict(list)
    for system in systems:
        for row in load(system):
            it = items.get(row["item_id"])
            if not it:
                continue
            f = score_row(row, it)
            if not f["usable"]:
                continue
            f.update({"item_id": it["id"], "run": row["run"], "slice": it["slice"], "family": it["family"],
                      "source": it["source"], "style": it.get("style"), "known_gap": it.get("known_gap"),
                      "jev_seconds": row.get("jev_seconds"), "jev_cost": row.get("jev_cost"),
                      "jev_model": row.get("jev_model"), "llm_model": row.get("llm_model")})
            if it.get("expected_faq_ids"):
                got = set(row.get("rag_doc_ids") or [])
                f["retrieval_hit"] = bool(got & set(it["expected_faq_ids"]))
            scored[system].append(f)

    n_items = len(items)
    print(f"\nV2 EVAL, split={args.split}: {n_items} questions, "
          + ", ".join(f"{LABELS.get(s, s)} {len(scored[s])} runs" for s in systems))
    models = {s: (Counter(f["llm_model"] for f in scored[s]).most_common(1)[0][0],
                  Counter(f["jev_model"] for f in scored[s] if f["jev_model"]).most_common(1)) for s in systems}
    for s in systems:
        llm, jev = models[s]
        print(f"  {LABELS.get(s, s):12s} answer model {llm}" + (f", planner {jev[0][0]}" if jev else ", planner gpt"))

    width = 20 + 6 + 12 * len(systems)

    def table(title, metric, rows_of):
        print(f"\n{title}\n")
        print(f"{'slice':<20} {'n':>4}  " + "  ".join(f"{l:>10}" for l in labels))
        print("-" * width)
        for sl in SLICE_ORDER:
            groups = [[f for f in rows_of(s) if f["slice"] == sl] for s in systems]
            if not any(groups):
                continue
            print(f"{sl:<20} {max(len(g) for g in groups):>4}  "
                  + "  ".join(f"{pct(sum(f[metric] for f in g), len(g)):>10}" for g in groups))
        print("-" * width)
        groups = [[f for f in rows_of(s) if f["slice"] != "known_gap"] for s in systems]
        print(f"{'ALL (excl. known_gap)':<20} {max(len(g) for g in groups):>4}  "
              + "  ".join(f"{pct(sum(f[metric] for f in g), len(g)):>10}" for g in groups))
        print(f"{'  95% CI':<20} {'':>4}  "
              + "  ".join(f"{ci(sum(f[metric] for f in g), len(g)):>10}" for g in groups))

    table("ROUTING ACCURACY  (exact match)", "route_exact", lambda s: scored[s])
    table("OVERALL PASS  (routes + SQL facts + behaviour + nothing leaked)", "pass", lambda s: scored[s])

    print("\n\nTEMPLATE vs PARAPHRASE  (pass rate; a gap here means wording sensitivity)\n")
    print(f"{'source / style':<20} {'n':>4}  " + "  ".join(f"{l:>10}" for l in labels))
    print("-" * width)
    for src in ("template", "paraphrase"):
        groups = [[f for f in scored[s] if f["source"] == src and f["slice"] != "known_gap"] for s in systems]
        print(f"{src:<20} {max(len(g) for g in groups):>4}  " + "  ".join(f"{pct(sum(f['pass'] for f in g), len(g)):>10}" for g in groups))
    for style in sorted({f["style"] for s in systems for f in scored[s] if f["style"]}):
        groups = [[f for f in scored[s] if f["style"] == style] for s in systems]
        print(f"  {style:<18} {max(len(g) for g in groups):>4}  " + "  ".join(f"{pct(sum(f['pass'] for f in g), len(g)):>10}" for g in groups))

    print("\n\nRETRIEVAL  (expected FAQ document in the top 4, on questions that have one)\n")
    for s, l in zip(systems, labels):
        rows = [f for f in scored[s] if "retrieval_hit" in f]
        print(f"  {l:<12} hit@4 {pct(sum(f['retrieval_hit'] for f in rows), len(rows))} of {len(rows)} runs  {ci(sum(f['retrieval_hit'] for f in rows), len(rows))}")

    print("\n\nPAIRED COMPARISON  (same question and run; McNemar exact test on discordant pairs)\n")
    for i in range(len(systems)):
        for j in range(i + 1, len(systems)):
            a, b = systems[i], systems[j]
            fa = {(f["item_id"], f["run"]): f["pass"] for f in scored[a] if f["slice"] != "known_gap"}
            fb = {(f["item_id"], f["run"]): f["pass"] for f in scored[b] if f["slice"] != "known_gap"}
            keys = fa.keys() & fb.keys()
            only_a = sum(1 for k in keys if fa[k] and not fb[k])
            only_b = sum(1 for k in keys if fb[k] and not fa[k])
            p = mcnemar_exact(only_a, only_b)
            print(f"  {LABELS.get(a, a)} vs {LABELS.get(b, b)}: {len(keys)} pairs, "
                  f"{LABELS.get(a, a)} alone right {only_a}, {LABELS.get(b, b)} alone right {only_b}, p = {p:.4f}")

    print("\n\nCOST PER QUESTION\n")
    print(f"{'system':<12} {'LLM calls':>10}  {'seconds':>9}  {'escalated':>10}")
    for s, l in zip(systems, labels):
        rows = scored[s]
        print(f"{l:<12} {statistics.mean(f['llm_calls'] for f in rows):>10.2f}  {statistics.mean(f['seconds'] for f in rows):>9.2f}  "
              f"{pct(sum(f['unexpected_escalation'] for f in rows), len(rows)):>10}")
    jev_rows = [f for f in scored.get("jev", []) if f["jev_seconds"] is not None]
    if jev_rows:
        secs = [f["jev_seconds"] for f in jev_rows]
        print(f"\n  jev planner: latency mean {statistics.mean(secs):.2f}s median {statistics.median(secs):.2f}s, "
              f"cost ${sum(f['jev_cost'] or 0 for f in jev_rows):.4f} over {len(jev_rows)} runs")

    print("\n\nINJECTION\n")
    for s, l in zip(systems, labels):
        rows = [f for f in scored[s] if f["slice"] == "injection"]
        leaks = Counter(x for f in rows for x in f["leaked"])
        print(f"  {l:<12} held {sum(f['injection_held'] for f in rows)}/{len(rows)}" + (f"   leaks: {dict(leaks)}" if leaks else ""))

    gap = [f for s in systems for f in scored[s] if f["slice"] == "known_gap"]
    if gap:
        print("\n\nKNOWN GAP  (overdue-only policies; scored as 'not found' to measure routing, real answer is the overdue amount)\n")
        for s, l in zip(systems, labels):
            rows = [f for f in scored[s] if f["slice"] == "known_gap"]
            print(f"  {l:<12} routed to billing {pct(sum(f['route_exact'] for f in rows), len(rows))}, "
                  f"said nothing due {pct(sum(f['behaviour_ok'] for f in rows), len(rows))}")

    if args.split != "test":
        print("\n\nWHERE THEY DIFFER  (pass rate per question where systems disagree; dev split only, by design)\n")
        by_item = {s: defaultdict(list) for s in systems}
        for s in systems:
            for f in scored[s]:
                by_item[s][f["item_id"]].append(f["pass"])
        print(f"{'question':<36}" + "".join(f"{l:>12}" for l in labels))
        shown = 0
        for iid, it in items.items():
            rates = [(sum(by_item[s][iid]) / len(by_item[s][iid])) if by_item[s].get(iid) else None for s in systems]
            known = [r for r in rates if r is not None]
            if len(known) < 2 or len(set(known)) == 1:
                continue
            print(f"{iid:<36}" + "".join(f"{(f'{r:.0%}' if r is not None else '-'):>12}" for r in rates))
            print(f"    {it['turns'][-1][:90]}")
            shown += 1
        if not shown:
            print("  none")
    else:
        print("\n(test split: per-question failures deliberately not listed)")
    print()


if __name__ == "__main__":
    main()
