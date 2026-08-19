from __future__ import annotations

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
