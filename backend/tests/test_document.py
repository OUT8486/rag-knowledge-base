from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


def test_upload_empty_pdf():
    with (
        patch("app.api.documents.extract_pdf_pages") as mock_parse,
        patch("app.api.documents.chunk_pages") as mock_chunk,
        patch("app.api.documents.add_chunks") as mock_index,
        TestClient(app) as client,
    ):
        # TODO：发送空 PDF
        response = client.post(
            "/api/documents/upload",
            files={"file": ("empty.pdf", b"", "application/pdf")},
        )
        # TODO：检查状态码和完整 JSON
        assert response.status_code == 400
        assert response.json() == {"detail":"上传的文件为空。"}
        # TODO：检查三个下游函数都没有被调用
        mock_parse.assert_not_called()
        mock_chunk.assert_not_called()
        mock_index.assert_not_called()
        
def test_upload_non_pdf():
    with (
        patch("app.api.documents.extract_pdf_pages") as mock_parse,
        patch("app.api.documents.chunk_pages") as mock_chunk,
        patch("app.api.documents.add_chunks") as mock_index,
        TestClient(app) as client,
    ):
        response = client.post(
            "/api/documents/upload",
            files={"file": ("note.txt", b"hello", "application/pdf")},
        )
        assert response.status_code == 400
        assert response.json() == {"detail":"当前只支持 PDF 文件。"}
        mock_parse.assert_not_called()
        mock_chunk.assert_not_called()
        mock_index.assert_not_called()

def test_upload_too_large_pdf():
    with (
        patch("app.api.documents.extract_pdf_pages") as mock_parse,
        patch("app.api.documents.chunk_pages") as mock_chunk,
        patch("app.api.documents.add_chunks") as mock_index,
        TestClient(app) as client,
    ):
        response = client.post(
            "/api/documents/upload",
            files={"file": ("large.pdf", b"x"*(10*1024*1024+1), "application/pdf")},
        )
        assert response.status_code == 413
        assert response.json() == {"detail":"文件大小不能超过 10 MB。"}
        mock_parse.assert_not_called()
        mock_chunk.assert_not_called()
        mock_index.assert_not_called()