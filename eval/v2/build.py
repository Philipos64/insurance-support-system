"""
Assemble the v2 question set: base items plus their paraphrases, split into
dev and test, then frozen.

The split is by base item. Every paraphrase of a base item lands in the same
half as the item itself, so a wording can never be tuned on the dev half and
then met again, reworded, in the test half. Within each family the base items
alternate between halves, so both halves have the same shape.

The dev half is for looking at failures and changing things. The test half is
run once per candidate and its failures are not read. `questions.sha256`
records the frozen file.

    python eval/v2/build.py            # writes eval/v2/questions.json
"""

import hashlib
import json
import random
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEED = 20260918

INHERIT = ("family", "category", "slice", "expected_routes", "expected_facts", "behaviour",
           "forbidden", "expected_faq_ids", "known_gap", "max_policy_ids_in_answer", "note", "meta")


def main():
    base = json.load(open(HERE / "base.json", encoding="utf-8"))["items"]
    paras = json.load(open(HERE / "paraphrases.json", encoding="utf-8"))
    by_id = {it["id"]: it for it in base}

    items = []
    for it in base:
        items.append({**it, "base_id": it["id"]})
    for p in paras["items"]:
        b = by_id[p["base_id"]]
        new = {k: b[k] for k in INHERIT if k in b}
        new.update({"id": f"{p['base_id']}-{p['style']}", "base_id": p["base_id"], "turns": p["turns"],
                    "source": "paraphrase", "style": p["style"], "paraphrase_model": p["model"]})
        items.append(new)

    # Split by base item, alternating within each family.
    rng = random.Random(SEED)
    split_of = {}
    for family in sorted({it["family"] for it in base}):
        ids = sorted(it["id"] for it in base if it["family"] == family)
        rng.shuffle(ids)
        for i, bid in enumerate(ids):
            split_of[bid] = "dev" if i % 2 == 0 else "test"
    for it in items:
        it["split"] = split_of[it["base_id"]]

    items.sort(key=lambda it: (it["family"], it["base_id"], it.get("style", "")))
    doc = {
        "version": "2.1",
        "frozen_at": str(date.today()),
        "seed": SEED,
        "paraphrase_model": paras["model"],
        "how_labelled": "Templates filled from PostgreSQL rows and FAQ-store documents; expected routes and facts "
                        "come from the data, paraphrases inherit them. No model wrote any label.",
        "items": items,
    }
    out = HERE / "questions.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1, ensure_ascii=False)
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    (HERE / "questions.sha256").write_text(f"{digest}  questions.json\n")

    print(f"{len(items)} items -> {out}")
    print(f"sha256 {digest[:16]}...")
    print(f"\n{'slice':18s} {'dev':>5s} {'test':>5s} {'total':>6s}   templ/para")
    per = defaultdict(Counter)
    for it in items:
        per[it["slice"]][it["split"]] += 1
        per[it["slice"]][it["source"]] += 1
    for sl, c in sorted(per.items(), key=lambda x: -(x[1]["dev"] + x[1]["test"])):
        print(f"{sl:18s} {c['dev']:>5d} {c['test']:>5d} {c['dev'] + c['test']:>6d}   {c['template']}/{c['paraphrase']}")
    tot = Counter(it["split"] for it in items)
    print(f"{'ALL':18s} {tot['dev']:>5d} {tot['test']:>5d} {len(items):>6d}")


if __name__ == "__main__":
    main()
