from uuid import UUID

from fastapi.testclient import TestClient
from app.main import app


def test_health_check():
    with TestClient(app) as client:
        response = client.get("/api/health")

    # TODO 1：断言状态码等于 200
    assert response.status_code == 200

    # TODO 2：断言 response.json() 等于完整的预期字典
    assert response.json() == {
        "status": "ok",
        "message": "RAG Knowledge Base is running",
    }

    # TODO 3：读取 X-Request-ID，断言它是 UUID4
    request_id = response.headers["X-Request-ID"]
    assert UUID(request_id).version == 4
    
    # TODO 4：读取 X-Process-Time-Ms，转成 float 后断言非负
    time = float(response.headers["X-Process-Time-Ms"])
    assert time >= 0
    
def test_request_ids_are_unique():
    with TestClient(app) as client:
        response1 = client.get("/api/health")
        response2 = client.get("/api/health")
        
    assert response1.status_code == 200
    assert response2.status_code == 200
    
    request1_id = response1.headers["X-Request-ID"]
    assert UUID(request1_id).version == 4
    request2_id = response2.headers["X-Request-ID"]
    assert UUID(request2_id).version == 4
    
    assert request1_id != request2_id