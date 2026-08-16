"""Policy corpus chunking + ChromaDB retrieval. Local embeddings via
sentence-transformers (all-MiniLM-L6-v2) — free, CPU-fine, zero LLM cost.
"""
import re
from pathlib import Path

import chromadb
from chromadb.utils import embedding_functions

ROOT = Path(__file__).resolve().parent.parent.parent
POLICY_DIR = ROOT / "data" / "policies"
CHROMA_DIR = ROOT / "data" / "chroma_db"

CHUNK_TOKENS = 400
CHUNK_OVERLAP = 50

_embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="all-MiniLM-L6-v2"
)

_client = None
_collection = None


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if not m:
        return {}, text
    fm_raw, body = m.group(1), m.group(2)
    meta = {}
    for line in fm_raw.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, body


def _chunk(text: str, chunk_tokens: int = CHUNK_TOKENS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    words = text.split()
    if len(words) <= chunk_tokens:
        return [text]
    chunks = []
    start = 0
    while start < len(words):
        end = start + chunk_tokens
        chunks.append(" ".join(words[start:end]))
        if end >= len(words):
            break
        start = end - overlap
    return chunks


def _get_collection():
    global _client, _collection
    if _collection is not None:
        return _collection
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    _client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    _collection = _client.get_or_create_collection(
        name="policies", embedding_function=_embed_fn
    )
    return _collection


def build_index(force: bool = False) -> int:
    """(Re)build the ChromaDB index from data/policies/*.md. Returns chunk count."""
    coll = _get_collection()
    if force:
        global _client, _collection
        _client.delete_collection("policies")
        _collection = _client.get_or_create_collection(name="policies", embedding_function=_embed_fn)
        coll = _collection
    elif coll.count() > 0:
        return coll.count()

    ids, docs, metas = [], [], []
    for path in sorted(POLICY_DIR.glob("*.md")):
        raw = path.read_text()
        meta, body = _parse_frontmatter(raw)
        policy_id = meta.get("id", path.stem)
        title = meta.get("title", "")
        chunks = _chunk(body)
        for i, chunk in enumerate(chunks):
            ids.append(f"{policy_id}::chunk{i}")
            docs.append(chunk)
            metas.append({"policy_id": policy_id, "title": title, "chunk_index": i, "source_file": path.name})

    if ids:
        coll.add(ids=ids, documents=docs, metadatas=metas)
    return len(ids)


def query_policies(query: str, k: int = 3) -> list[dict]:
    coll = _get_collection()
    if coll.count() == 0:
        build_index()
    result = coll.query(query_texts=[query], n_results=k)
    hits = []
    if not result["ids"] or not result["ids"][0]:
        return hits
    for doc_id, doc, meta, dist in zip(
        result["ids"][0], result["documents"][0], result["metadatas"][0], result["distances"][0]
    ):
        hits.append({
            "policy_id": meta["policy_id"],
            "title": meta.get("title", ""),
            "excerpt": doc[:400],
            "distance": round(float(dist), 4),
        })
    return hits


if __name__ == "__main__":
    n = build_index(force=True)
    print(f"indexed {n} chunks from {POLICY_DIR}")
    hits = query_policies("shared device cluster", k=3)
    print("sanity check: search_policy('shared device cluster') ->")
    for h in hits:
        print(f"  {h['policy_id']} ({h['title']}) distance={h['distance']}")
