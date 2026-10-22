from pathlib import Path


# 数据库文件保存在 backend/data/chroma 中
DB_PATH = Path(__file__).resolve().parents[2] / "data" / "chroma"

_client = None
_collection = None


def _get_collection():
    """首次使用时再初始化 ChromaDB，避免阻塞应用启动。"""
    global _client, _collection

    if _collection is None:
        import chromadb

        DB_PATH.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(
            path=str(DB_PATH)
        )
        _collection = _client.get_or_create_collection(
            name="knowledge_chunks",
            metadata={"hnsw:space": "cosine"},
            embedding_function=None,
        )

    return _collection


def add_chunks(
    chunks: list[dict],
    filename: str,
) -> int:
    """将文本块向量化，并保存到 ChromaDB。"""

    if not chunks:
        return 0

    from app.services.embedding import embed_documents

    texts = [chunk["text"] for chunk in chunks]

    # 1. 将文本块转换为向量
    embeddings = embed_documents(texts)

    # 2. 准备来源元数据
    metadatas = [
        {
            "document_id": chunk["document_id"],
            "filename": filename,
            "page": chunk["page"],
            "chunk_index": chunk["chunk_index"],
        }
        for chunk in chunks
    ]

    # 3. 保存向量、正文、ID 和元数据
    _get_collection().upsert(
        ids=[chunk["chunk_id"] for chunk in chunks],
        embeddings=embeddings,
        documents=texts,
        metadatas=metadatas,
    )

    return len(chunks)


def search_chunks(
    query: str,
    top_k: int = 5,
    document_id: str | None = None,
) -> list[dict]:
    """根据问题检索最相关的文本块。"""

    from app.services.embedding import embed_query

    collection = _get_collection()
    total_count = collection.count()

    if total_count == 0:
        return []

    # 1. 将用户的问题转换为向量
    query_embedding = embed_query(query)

    # 2. 设置检索参数
    query_params = {
        "query_embeddings": [query_embedding],
        "n_results": min(top_k, total_count),
        "include": [
            "documents",
            "metadatas",
            "distances",
        ],
    }

    # 可选：只搜索指定文档
    if document_id:
        query_params["where"] = {
            "document_id": document_id
        }

    # 3. 执行语义检索
    results = collection.query(**query_params)

    ids = results["ids"][0]
    documents = results["documents"][0]
    metadatas = results["metadatas"][0]
    distances = results["distances"][0]

    # 4. 整理为前端更容易使用的结构
    formatted_results = []

    for chunk_id, text, metadata, distance in zip(
        ids,
        documents,
        metadatas,
        distances,
    ):
        formatted_results.append({
            "chunk_id": chunk_id,
            "text": text,
            "document_id": metadata["document_id"],
            "filename": metadata["filename"],
            "page": metadata["page"],
            "chunk_index": metadata["chunk_index"],
            "distance": float(distance),
        })

    return formatted_results

def list_documents() -> list[dict]:
    """从向量数据库中汇总所有文档。"""

    collection = _get_collection()
    records = collection.get(
        include=["metadatas"],
    )

    documents = {}

    for metadata in records["metadatas"] or []:
        if not metadata:
            continue

        document_id = metadata.get("document_id")

        if not document_id:
            continue

        if document_id not in documents:
            documents[document_id] = {
                "document_id": document_id,
                "filename": metadata.get(
                    "filename",
                    "未知文件",
                ),
                "chunk_count": 0,
            }

        documents[document_id]["chunk_count"] += 1

    return sorted(
        documents.values(),
        key=lambda item: item["filename"].lower(),
    )


def delete_document(document_id: str) -> int:
    """删除指定文档的全部文本块和向量。"""

    collection = _get_collection()
    records = collection.get(
        where={"document_id": document_id},
        include=["metadatas"],
    )

    chunk_ids = records["ids"]

    if not chunk_ids:
        return 0

    collection.delete(ids=chunk_ids)

    return len(chunk_ids)
