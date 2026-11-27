from uuid import UUID


def test_health_check(pilot):
    response = pilot.client.get("/api/health")

    assert response.status_code == 200

    assert response.json() == {
        "status": "ok",
        "message": "RAG Knowledge Base is running",
    }

    request_id = response.headers["X-Request-ID"]
    assert UUID(request_id).version == 4

    time = float(response.headers["X-Process-Time-Ms"])
    assert time >= 0


def test_request_ids_are_unique(pilot):
    response1 = pilot.client.get("/api/health")
    response2 = pilot.client.get("/api/health")

    assert response1.status_code == 200
    assert response2.status_code == 200

    request1_id = response1.headers["X-Request-ID"]
    assert UUID(request1_id).version == 4
    request2_id = response2.headers["X-Request-ID"]
    assert UUID(request2_id).version == 4

    assert request1_id != request2_id
