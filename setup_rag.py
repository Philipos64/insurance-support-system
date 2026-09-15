import json
from pathlib import Path

import pandas as pd
from datasets import load_dataset
import chromadb
from tqdm import tqdm
import os

# 1. Setup ChromaDB (Local Vector Store)
# This creates a folder named 'chroma_db' in your project directory
PERSIST_DIRECTORY = "./chroma_db"

CUSTOM_FAQ_PATH = Path(__file__).parent / "data" / "custom_faqs.json"


def load_custom_faqs():
    """Load the hand-written demo FAQs and shape them like the sampled dataset."""
    with open(CUSTOM_FAQ_PATH, encoding="utf-8") as f:
        faqs = json.load(f)

    return [
        {
            "input": faq["question"],
            "output": faq["answer"],
            "combined": f'Question: {faq["question"]} \n Answer: {faq["answer"]}',
        }
        for faq in faqs
    ]


def setup_vector_db():
    print("Downloading FAQ Dataset from Hugging Face...")

    try:
        ds = load_dataset("deccan-ai/insuranceQA-v2")
    except Exception as e:
        print(f"Error downloading dataset: {e}")
        return None

    print("Processing Data...")
    df = pd.concat([split.to_pandas() for split in ds.values()], ignore_index=True)

    # Format: "Question: ... \n Answer: ..."
    df["combined"] = "Question: " + df["input"] + " \n Answer:  " + df["output"]

    # Sample 1000 rows
    df = df.sample(1000, random_state=42).reset_index(drop=True)

    # Demo FAQ entries are kept in data/custom_faqs.json so the content can be
    # edited without touching this script. They are prepended to the sampled
    # dataset so they always exist in the vector store for demonstrations.
    custom_faqs = pd.DataFrame(load_custom_faqs())
    df = pd.concat([custom_faqs, df], ignore_index=True)

    print(f"Prepared {len(df)} FAQ pairs (including custom demo FAQs).")

    print("Initializing Vector Store...")
    chroma_client = chromadb.PersistentClient(path=PERSIST_DIRECTORY)

    try:
        chroma_client.delete_collection(name="insurance_FAQ_collection")
    except:
        pass

    collection = chroma_client.create_collection(name="insurance_FAQ_collection")

    batch_size = 100
    print("Embedding and Indexing (This might take a minute)...")

    for i in tqdm(range(0, len(df), batch_size)):
        batch_df = df.iloc[i:i+batch_size]

        collection.add(
            documents=batch_df["combined"].tolist(),
            metadatas=[{"question": q, "answer": a} for q, a in zip(batch_df["input"], batch_df["output"])],
            ids=batch_df.index.astype(str).tolist()
        )

    print("Vector Database Built Successfully!")
    return collection

def test_retrieval():
    """Tests if we can actually find answers"""
    print("\nTesting RAG Retrieval...")
    chroma_client = chromadb.PersistentClient(path=PERSIST_DIRECTORY)
    collection = chroma_client.get_collection(name="insurance_FAQ_collection")

    query = "What does life insurance cover?"
    results = collection.query(
        query_texts=[query],
        n_results=1
    )

    print(f"Query: {query}")
    if results['documents']:
        print(f"Retrieved Answer: {results['documents'][0][0][:200]}...") # Show first 200 chars
    else:
        print("Nothing found.")

if __name__ == "__main__":
    setup_vector_db()
    test_retrieval()