"""Tests for API routes — push, data, command endpoints."""


def test_push_mobile_activity(client):
    resp = client.post("/api/v1/push/activity", json={
        "app_usage": [
            {
                "package": "com.kakao.talk",
                "app_name": "KakaoTalk",
                "started_at": "2026-03-14T09:00:00",
                "ended_at": "2026-03-14T09:30:00",
                "duration_s": 1800,
            },
            {
                "package": "com.youtube",
                "app_name": "YouTube",
                "started_at": "2026-03-14T10:00:00",
                "duration_s": 600,
            },
        ],
        "locations": [
            {
                "latitude": 37.5665,
                "longitude": 126.978,
                "label": "office",
                "recorded_at": "2026-03-14T09:00:00",
            },
        ],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["ingested"]["app_usage"] == 2
    assert data["ingested"]["locations"] == 1


def test_push_pc_activity(client):
    resp = client.post("/api/v1/push/pc-activity", json={
        "activities": [
            {
                "window_title": "VSCode - jarvis",
                "process_name": "Code.exe",
                "started_at": "2026-03-14T09:00:00",
                "duration_s": 3600,
            },
        ],
    })
    assert resp.status_code == 200
    assert resp.json()["ingested"]["pc_activity"] == 1


def test_activity_summary(client):
    resp = client.get("/api/v1/data/activity/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_active_s" in data
    assert "mobile" in data
    assert "pc" in data


def test_activity_trend(client):
    resp = client.get("/api/v1/data/activity/trend?days=3")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


def test_task_crud_via_api(client):
    # Create
    resp = client.post("/api/v1/push/tasks", json={
        "title": "테스트 할 일",
        "priority": "high",
    })
    assert resp.status_code == 200
    task_id = resp.json()["task_id"]

    # Read
    resp = client.get("/api/v1/data/tasks")
    assert resp.status_code == 200
    assert resp.json()["count"] >= 1

    # Update
    resp = client.put(f"/api/v1/push/tasks/{task_id}", json={
        "status": "done",
    })
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    # Delete
    resp = client.delete(f"/api/v1/push/tasks/{task_id}")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_unreplied_emails_endpoint(client):
    resp = client.get("/api/v1/data/emails/unreplied")
    assert resp.status_code == 200
    assert "emails" in resp.json()


def test_promises_endpoint(client):
    resp = client.get("/api/v1/data/promises")
    assert resp.status_code == 200
    assert "promises" in resp.json()


def test_command_endpoint(client):
    """Test the orchestrator command endpoint (uses mock Claude)."""
    resp = client.post("/api/v1/command", json={
        "text": "안녕하세요",
        "locale": "ko",
    })
    assert resp.status_code == 200
    assert "reply" in resp.json()


def test_briefing_endpoint(client):
    """Test briefing generation (uses mock Claude)."""
    resp = client.post("/api/v1/data/briefing", json={
        "type": "morning",
        "locale": "ko",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "morning"
    assert len(data["content"]) > 0


def test_notifications_endpoint(client):
    resp = client.get("/api/v1/data/notifications")
    assert resp.status_code == 200
    assert "notifications" in resp.json()


def test_proactive_check_endpoint(client):
    resp = client.post("/api/v1/data/proactive/check")
    assert resp.status_code == 200
    data = resp.json()
    assert "alerts" in data
    assert "count" in data


def test_health_shows_pc_status(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "pc_connected" in data
    assert data["pc_connected"] is False  # no PC client connected in tests
