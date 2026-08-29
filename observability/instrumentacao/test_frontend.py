from __future__ import annotations

import httpx
import respx
from fastapi.testclient import TestClient

from observability.src.app import create_app
from observability.src.storage.sqlite import (
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
    assert "Chat Direto" in response.text
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
    db_path = tmp_path / "agno-run.db"
    monkeypatch.setenv("OBSERVABILITY_DB_PATH", str(db_path))
    monkeypatch.setenv("AGNO_OS_URL", "http://agent-os.test")
    app = create_app()
    client = TestClient(app)

    with respx.mock:
        route = respx.post("http://agent-os.test/agents/vision/runs").mock(
            return_value=httpx.Response(
                200,
                content=(
                    b'{"event":"RunStarted","session_id":"s1","created_at":1}\n'
                    b'{"event":"RunContent","content":"ola mundo acessivel","created_at":2}\n'
                    b'{"event":"RunCompleted","data":{"usage":{"input_tokens":10,"output_tokens":25,"cost":0.00015}}}\n'
                ),
            )
        )

        response = client.post(
            "/api/agno/runs",
            json={
                "entity_type": "agent",
                "entity_id": "vision",
                "message": "descreva imagem",
                "session_id": "s1",
                "model": "gpt-4o",
                "model_provider": "openai",
            },
        )

    assert response.status_code == 200
    assert route.called
    assert '"RunStarted"' in response.text
    assert '"RunContent"' in response.text
    assert '"RunFinished"' in response.text
    assert '"trace_id"' in response.text

    # Verifica persistência no SQLite
    sess = client.get("/api/agno/sessions/s1")
    assert sess.status_code == 200
    sess_data = sess.json()
    assert sess_data["session"]["session_id"] == "s1"
    assert len(sess_data["messages"]) == 2  # user + assistant
    assert sess_data["messages"][0]["content"] == "descreva imagem"
    assert "ola mundo acessivel" in sess_data["messages"][1]["content"]

    # Verifica métricas do agente
    summary = client.get("/api/agno/metrics/summary?entity_id=vision&entity_type=agent")
    assert summary.status_code == 200
    summary_data = summary.json()
    assert summary_data["total_runs"] == 1
    assert summary_data["recent_runs"][0]["trace_id"]
    assert summary_data["input_tokens_total"] == 10
    assert summary_data["output_tokens_total"] == 25
    assert summary_data["total_cost"] == 0.00015

    # Verifica comparativo
    comp = client.get("/api/agno/metrics/compare?group_by=agent")
    assert comp.status_code == 200
    assert len(comp.json()["items"]) >= 1

    # Verifica relatório
    rep = client.get("/api/agno/metrics/report")
    assert rep.status_code == 200
    assert "Relatório de Observabilidade Agno" in rep.json()["markdown"]

    # Deleta sessão
    del_res = client.delete("/api/agno/sessions/s1")
    assert del_res.status_code == 200
    assert client.get("/api/agno/sessions/s1").status_code == 404


def test_agno_run_normalizes_sse_stream(monkeypatch, tmp_path):
    db_path = tmp_path / "agno-sse.db"
    monkeypatch.setenv("OBSERVABILITY_DB_PATH", str(db_path))
    monkeypatch.setenv("AGNO_OS_URL", "http://agent-os.test")
    monkeypatch.setenv("AGNO_CONSOLE_STORE_REASONING", "false")
    app = create_app()
    client = TestClient(app)

    with respx.mock:
        respx.post("http://agent-os.test/agents/vision/runs").mock(
            return_value=httpx.Response(
                200,
                content=(
                    b'event: RunStarted\n'
                    b'data: {"session_id":"sse1","created_at":1}\n\n'
                    b'event: RunContent\n'
                    b'data: {"content":"parte um"}\n\n'
                    b'event: RunContent\n'
                    b'data: {"content":" parte dois"}\n\n'
                    b'event: ToolCallCompleted\n'
                    b'data: {"tool_name":"buscar","tool_args":{"q":"x"},"tool_result":{"ok":true}}\n\n'
                    b'event: RunReasoning\n'
                    b'data: {"content":"raciocinio sensivel"}\n\n'
                    b'event: RunCompleted\n'
                    b'data: {"usage":{"input_tokens":4,"output_tokens":5,"total_tokens":9},"model":"gpt-test","provider":"openai"}\n\n'
                ),
            )
        )

        response = client.post(
            "/api/agno/runs",
            json={
                "entity_type": "agent",
                "entity_id": "vision",
                "message": "teste sse",
                "session_id": "sse1",
            },
        )

    assert response.status_code == 200
    assert '"event": "RunContent"' in response.text
    assert '"event": "RunFinished"' in response.text
    assert "event: RunContent" not in response.text
    assert "raciocinio sensivel" not in response.text
    assert "Reasoning resumido" in response.text

    details = client.get("/api/agno/sessions/sse1").json()
    assert details["messages"][1]["content"] == "parte um parte dois"
    assert len(details["tools_by_run"][details["runs"][0]["run_id"]]) == 1
    assert details["runs"][0]["total_tokens"] == 9

    events = details["events_by_run"][details["runs"][0]["run_id"]]
    reasoning_events = [e for e in events if e["event_name"] == "RunReasoning"]
    assert reasoning_events
    assert "raciocinio sensivel" not in reasoning_events[0]["event_data_json"]
    assert "Reasoning resumido" in reasoning_events[0]["event_data_json"]


def test_agno_reasoning_redaction(monkeypatch, tmp_path):
    import sqlite3

    from observability.src.storage.sqlite import create_agno_run_event, init_db

    db_path = tmp_path / "reasoning.db"
    init_db(db_path)

    # 1. Com flag desativada (padrão)
    monkeypatch.setenv("AGNO_CONSOLE_STORE_REASONING", "false")
    ev1 = create_agno_run_event(
        run_id="r1",
        session_id="s1",
        event_name="RunReasoning",
        event_data={"content": "segredo ultra secreto de raciocinio intermediario"},
        db_path=db_path,
    )
    with sqlite3.connect(db_path) as conn:
        row1 = conn.execute("SELECT event_data_json FROM agno_run_events WHERE id = ?", (ev1["id"],)).fetchone()
        assert "segredo ultra secreto" not in row1[0]
        assert "Reasoning resumido" in row1[0]

    # 2. Com flag ativada
    monkeypatch.setenv("AGNO_CONSOLE_STORE_REASONING", "true")
    ev2 = create_agno_run_event(
        run_id="r2",
        session_id="s2",
        event_name="RunReasoning",
        event_data={"content": "raciocinio detalhado completo autorizado"},
        db_path=db_path,
    )
    with sqlite3.connect(db_path) as conn:
        row2 = conn.execute("SELECT event_data_json FROM agno_run_events WHERE id = ?", (ev2["id"],)).fetchone()
        assert "raciocinio detalhado completo autorizado" in row2[0]



def test_snapshot_degrades_when_stack_is_down(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSERVABILITY_DB_PATH", str(tmp_path / "snapshot.db"))
    monkeypatch.setenv("ACESSILIA_API_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("PROMETHEUS_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("LOKI_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("LANGFUSE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("TEMPO_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("LOCUST_URL", "http://127.0.0.1:9")
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
        "tempo": False,
        "locust": False,
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
