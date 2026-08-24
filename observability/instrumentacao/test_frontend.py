from __future__ import annotations

import httpx
import respx
from fastapi.testclient import TestClient

from observability.frontend.app import create_app
from observability.frontend.store import (
    create_annotation,
    delete_annotation,
    list_annotations,
)


def test_annotation_store_roundtrip(tmp_path):
    db_path = tmp_path / "observability.db"

    item = create_annotation(
        target_type="pipeline",
        target_id="job-1",
        severity="warning",
        note="Fila acima do esperado.",
        tags="fila,teste",
        db_path=db_path,
    )

    assert item["id"]
    assert list_annotations(db_path) == [item]
    assert delete_annotation(item["id"], db_path) is True
    assert list_annotations(db_path) == []


def test_frontend_annotation_endpoints(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSERVABILITY_DB_PATH", str(tmp_path / "ui.db"))
    app = create_app()
    client = TestClient(app)

    response = client.post(
        "/api/annotations",
        json={
            "target_type": "llm",
            "target_id": "VisionAgent",
            "severity": "note",
            "note": "Verificar custo desta chamada.",
            "tags": "llm",
        },
    )

    assert response.status_code == 201
    annotation_id = response.json()["item"]["id"]
    assert client.get("/api/annotations").json()["items"][0]["id"] == annotation_id
    assert client.delete(f"/api/annotations/{annotation_id}").status_code == 204
    assert client.get("/api/annotations").json()["items"] == []


def test_frontend_index_renders(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSERVABILITY_DB_PATH", str(tmp_path / "index.db"))
    app = create_app()
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert "Acessília Observabilidade" in response.text
    assert "Tempo real" in response.text
    assert "Status da stack" in response.text
    assert "Req/s usuários" in response.text
    assert "Pipeline em tempo real" in response.text
    assert "LLM em tempo real" in response.text
    assert "Tokens, TTFT e custo" in response.text
    assert "Console Agno" in response.text


def test_agno_console_renders(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSERVABILITY_DB_PATH", str(tmp_path / "agno.db"))
    monkeypatch.setenv("AGNO_OS_URL", "http://agent-os.local")
    app = create_app()
    client = TestClient(app)

    response = client.get("/agno")

    assert response.status_code == 200
    assert "Acessília Console Agno" in response.text
    assert "Descoberta automática" in response.text
    assert "Chat direto" in response.text
    assert "http://agent-os.local" in response.text


def test_agno_entities_degrades_when_agentos_is_down(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSERVABILITY_DB_PATH", str(tmp_path / "agno-down.db"))
    monkeypatch.setenv("AGNO_OS_URL", "http://127.0.0.1:9")
    app = create_app()
    client = TestClient(app)

    response = client.get("/api/agno/entities")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"]["available"] is False
    assert payload["entities"]["agents"] == []
    assert payload["entities"]["teams"] == []
    assert payload["capabilities"]["workflows"] is False


def test_agno_entities_reads_agents_and_teams(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSERVABILITY_DB_PATH", str(tmp_path / "agno-ok.db"))
    monkeypatch.setenv("AGNO_OS_URL", "http://agent-os.test")
    app = create_app()
    client = TestClient(app)

    with respx.mock:
        respx.get("http://agent-os.test/health").mock(
            return_value=httpx.Response(200, json={"status": "ok"})
        )
        respx.get("http://agent-os.test/agents").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "id": "vision",
                        "name": "Vision Agent",
                        "db_id": "db-vision",
                        "model": {"provider": "openai", "model": "gpt-test"},
                    }
                ],
            )
        )
        respx.get("http://agent-os.test/teams").mock(
            return_value=httpx.Response(
                200,
                json=[{"id": "review", "name": "Review Team"}],
            )
        )

        response = client.get("/api/agno/entities")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"]["available"] is True
    assert payload["entities"]["agents"][0]["id"] == "vision"
    assert payload["entities"]["agents"][0]["model"]["model"] == "gpt-test"
    assert payload["entities"]["teams"][0]["id"] == "review"


def test_agno_run_proxies_agent_stream(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSERVABILITY_DB_PATH", str(tmp_path / "agno-run.db"))
    monkeypatch.setenv("AGNO_OS_URL", "http://agent-os.test")
    app = create_app()
    client = TestClient(app)

    with respx.mock:
        route = respx.post("http://agent-os.test/agents/vision/runs").mock(
            return_value=httpx.Response(
                200,
                content=(
                    b'{"event":"RunStarted","session_id":"s1","created_at":1}'
                    b'{"event":"RunContent","content":"ok","created_at":2}'
                ),
            )
        )

        response = client.post(
            "/api/agno/runs",
            json={
                "entity_type": "agent",
                "entity_id": "vision",
                "message": "teste",
                "session_id": "",
            },
        )

    assert response.status_code == 200
    assert route.called
    assert '"RunStarted"' in response.text
    assert '"RunContent"' in response.text


def test_snapshot_degrades_when_stack_is_down(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSERVABILITY_DB_PATH", str(tmp_path / "snapshot.db"))
    monkeypatch.setenv("ACESSILIA_API_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("PROMETHEUS_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("LOKI_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("LANGFUSE_URL", "http://127.0.0.1:9")
    app = create_app()
    client = TestClient(app)

    response = client.get("/api/snapshot")

    assert response.status_code == 200
    payload = response.json()
    assert payload["services"] == {
        "api": False,
        "prometheus": False,
        "loki": False,
        "langfuse": False,
    }
    assert payload["logs"] == []
    assert payload["annotations"] == []


def test_realtime_degrades_when_prometheus_is_down(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSERVABILITY_DB_PATH", str(tmp_path / "realtime.db"))
    monkeypatch.setenv("PROMETHEUS_URL", "http://127.0.0.1:9")
    app = create_app()
    client = TestClient(app)

    response = client.get("/api/realtime")

    assert response.status_code == 200
    payload = response.json()
    assert payload["generated_at"]
    assert {metric["key"] for metric in payload["metrics"]} >= {
        "req_user",
        "req_internal",
        "http_4xx",
        "http_5xx",
    }
    assert all(metric["value"] is None for metric in payload["metrics"])


def test_timeseries_degrades_when_prometheus_is_down(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSERVABILITY_DB_PATH", str(tmp_path / "timeseries.db"))
    monkeypatch.setenv("PROMETHEUS_URL", "http://127.0.0.1:9")
    app = create_app()
    client = TestClient(app)

    response = client.get("/api/timeseries?range_seconds=60&step_seconds=1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["range_seconds"] == 60
    assert payload["step_seconds"] == 1
    assert {serie["key"] for serie in payload["series"]} >= {
        "req_user",
        "req_internal",
        "cpu",
        "ram",
        "llm_total_tokens_rate",
        "llm_ttft_avg",
        "conversion_avg",
        "exports_per_min",
    }
    assert all(serie["points"] == [] for serie in payload["series"])
