def build_metadatas(chunks: list[dict], filename: str) -> list[dict]:
    """为每个文本块生成一条来源信息；没有文本块时返回空列表。"""
    metadatas = []

    for chunk in chunks:
        metadatas.append({
            "document_id": chunk["document_id"],
            "filename": filename,
            "page": chunk["page"],
            "chunk_index": chunk["chunk_index"],
        })

    return metadatas