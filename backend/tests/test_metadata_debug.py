from metadata_debug import build_metadatas


def test_one_chunk():
    chunks = [
        {"document_id": "doc-demo", "page": 3, "chunk_index": 1},
    ]

    result = build_metadatas(chunks, "manual.pdf")

    assert result == [
        {
            "document_id": "doc-demo",
            "filename": "manual.pdf",
            "page": 3,
            "chunk_index": 1,
        },
    ]


def test_two_chunks():
    chunks = [
        {"document_id": "doc-demo", "page": 3, "chunk_index": 1},
        {"document_id": "doc-demo", "page": 7, "chunk_index": 2},
    ]

    result = build_metadatas(chunks, "manual.pdf")

    assert result == [
        {
            "document_id": "doc-demo",
            "filename": "manual.pdf",
            "page": 3,
            "chunk_index": 1,
        },
        {
            "document_id": "doc-demo",
            "filename": "manual.pdf",
            "page": 7,
            "chunk_index": 2,
        },
    ]

def test_zero_chunk():
    chunks = []

    result = build_metadatas(chunks, "manual1.pdf")

    assert result == []