"""
Rewrite a sample of the base items in varied language.

The labels are inherited from the base item: the model only changes the
surface form, never the intent, and every ID has to survive verbatim. A
different model family from the one under test (Claude, through OpenRouter)
writes the rewrites, so the test set is not shaped by the system's own
habits. Resumable: (base id, style) pairs already in the output are skipped.

    python eval/v2/paraphrase.py            # writes eval/v2/paraphrases.json
"""

import json
import os
import random
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
SEED = 20260918
MODEL = "anthropic/claude-sonnet-5"
ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
ID_RE = re.compile(r"(?:POL|CLM)\d+", re.I)

# Styles, each a different way real customers write. Two per sampled item.
STYLES = {
    "casual": "casual and chatty, like a text message to a friend, lowercase is fine",
    "terse": "as short as possible, a fragment, no greeting, no please",
    "formal": "formal and polite, a full sentence, as in a written letter",
    "typos": "hurried, with two or three realistic typos or missing letters, but still understandable",
    "indirect": "roundabout, giving some context first and only then getting to the question",
    "swedish": "in Swedish (the customer is Swedish), natural and idiomatic",
}

# Families whose wording is the point, or which are already natural language.
SKIP = {"knowledge_dataset", "injection_pure", "injection_with_lookup", "billing_overdue_only", "lowercase_id"}

SYSTEM = """You rewrite customer messages for a test set of an insurance support chatbot.
Rules:
- Keep exactly the same request(s). Do not add, drop or change what is being asked.
- Every policy or claim ID (like POL000123 or CLM000045) must appear exactly as written, same letters, same digits, same case.
- Write in the requested style. One message per turn, first person, from the customer.
- If there are several turns, rewrite each and keep the same number of turns; a follow-up turn that refers back ("it", "that policy") must still refer back the same way.
- Do not answer the question. Do not add anything that is not in the original.
Return only JSON: {"turns": ["...", "..."]}"""


def ask(client, key, turns, style):
    user = f"Style: {STYLES[style]}.\nOriginal turns (JSON): {json.dumps(turns, ensure_ascii=False)}"
    r = client.post(ENDPOINT, headers={"Authorization": f"Bearer {key}"}, timeout=60,
                    json={"model": MODEL, "max_tokens": 400, "temperature": 0.9,
                          "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]})
    data = r.json()
    if "choices" not in data:
        raise RuntimeError(f"HTTP {r.status_code}: {str(data)[:200]}")
    text = data["choices"][0]["message"]["content"].strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    out = json.loads(text)["turns"]
    return out, data.get("usage", {}).get("cost", 0.0)


def valid(original, rewritten, style):
    """Reject rewrites that would change the label."""
    if not isinstance(rewritten, list) or len(rewritten) != len(original):
        return "turn count"
    for o, n in zip(original, rewritten):
        if not isinstance(n, str) or not n.strip() or len(n) > 400:
            return "empty or too long"
        if sorted(ID_RE.findall(o)) != sorted(ID_RE.findall(n)):
            return "ids changed"
        if re.sub(r"\W+", "", o.lower()) == re.sub(r"\W+", "", n.lower()):
            return "identical"
    return None


def main():
    load_dotenv(".env")
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        sys.exit("OPENROUTER_API_KEY not set")
    base = json.load(open(HERE / "base.json", encoding="utf-8"))["items"]
    out_path = HERE / "paraphrases.json"
    done = {}
    if out_path.exists():
        for p in json.load(open(out_path, encoding="utf-8"))["items"]:
            done[(p["base_id"], p["style"])] = p

    rng = random.Random(SEED)
    candidates = [it for it in base if it["family"] not in SKIP]
    per_item = 2
    target = int(os.environ.get("PARAPHRASE_TARGET", "170"))
    sampled = rng.sample(candidates, min(len(candidates), target // per_item))
    styles = list(STYLES)
    jobs = []
    for it in sampled:
        for style in rng.sample(styles, per_item):
            if (it["id"], style) not in done:
                jobs.append((it, style))
    print(f"{len(sampled)} base items x {per_item} styles; {len(done)} done, {len(jobs)} to write")

    results = dict(done)
    rejected = []
    total_cost = 0.0
    with httpx.Client() as client, ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(ask, client, key, it["turns"], style): (it, style) for it, style in jobs}
        for n, fut in enumerate(as_completed(futures), 1):
            it, style = futures[fut]
            try:
                turns, cost = fut.result()
                total_cost += cost or 0.0
                why = valid(it["turns"], turns, style)
                if why:
                    rejected.append({"base_id": it["id"], "style": style, "why": why, "turns": turns})
                    continue
                results[(it["id"], style)] = {"base_id": it["id"], "style": style, "turns": turns, "model": MODEL}
            except Exception as exc:  # noqa: BLE001
                rejected.append({"base_id": it["id"], "style": style, "why": f"error: {exc}"[:200]})
            if n % 20 == 0:
                print(f"  {n}/{len(jobs)}")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"version": "2.0-paraphrases", "model": MODEL, "seed": SEED,
                   "items": sorted(results.values(), key=lambda p: (p["base_id"], p["style"]))}, f, indent=1, ensure_ascii=False)
    with open(HERE / "paraphrases.rejected.json", "w", encoding="utf-8") as f:
        json.dump(rejected, f, indent=1, ensure_ascii=False)
    print(f"{len(results)} paraphrases kept, {len(rejected)} rejected -> {out_path}   (cost this run ${total_cost:.3f})")


if __name__ == "__main__":
    main()
