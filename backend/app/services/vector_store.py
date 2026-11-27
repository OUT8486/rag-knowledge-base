"""One collection per authorized KB. Staged/retired versions are never retrieval candidates."""

from pathlib import Path
from threading import Lock

from app.services import embedding


class VectorStore:
    def __init__(self, path: Path):
        self.path = path
        self._client = None
        self._collections = {}
        self._lock = Lock()

    def client(self):
        with self._lock:
            if self._client is None:
                import chromadb
                from chromadb.config import Settings

                self.path.mkdir(parents=True, exist_ok=True)
                self._client = chromadb.PersistentClient(
                    path=str(self.path), settings=Settings(anonymized_telemetry=False)
                )
            return self._client

    def close(self):
        with self._lock:
            self._collections.clear()
            if self._client is not None:
                self._client.close()
                self._client = None

    def collection(self, kb_id):
        client = self.client()
        with self._lock:
            if kb_id not in self._collections:
                self._collections[kb_id] = client.get_or_create_collection(
                    name=f"kb_{kb_id}",
                    configuration={"hnsw": {"space": "cosine"}},
                    embedding_function=None,
                )
            return self._collections[kb_id]

    def index(self, kb_id, version, doc, filename, chunks):
        collection = self.collection(kb_id)
        # Deterministic version-scoped IDs. A retry discards only its unpublished partial index.
        collection.delete(where={"version_id": version})
        for start in range(0, len(chunks), 64):
            batch = chunks[start : start + 64]
            texts = [c["text"] for c in batch]
            collection.upsert(
                ids=[c["chunk_id"] for c in batch],
                documents=texts,
                embeddings=embedding.embed_documents(texts),
                metadatas=[
                    {
                        "document_id": doc,
                        "version_id": version,
                        "filename": filename,
                        "page": c["page"],
                        "chunk_index": c["chunk_index"],
                    }
                    for c in batch
                ],
            )

    def discard(self, kb_id, version):
        self.collection(kb_id).delete(where={"version_id": version})

    def search(self, kb_id, versions, query, top_k):
        if not versions:
            return []  # No way to request an unfiltered search, including for an empty KB.
        where = {"version_id": versions[0] if len(versions) == 1 else {"$in": versions}}
        found = self.collection(kb_id).query(
            query_embeddings=[embedding.embed_query(query)],
            where=where,
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
        return [
            {"chunk_id": cid, "text": text, **meta, "distance": float(dist)}
            for cid, text, meta, dist in zip(
                found["ids"][0], found["documents"][0], found["metadatas"][0], found["distances"][0]
            )
        ]
