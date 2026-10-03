import json

import httpx
import pytest
import respx

from scripts import check_toolbox


@pytest.mark.parametrize("capabilities", [[{"name": "document.structure.extract"}],
                                         {"capabilities": [{"name": "document.structure.extract"}]}])
def test_remote_diagnostic_uses_existing_http_contract(capabilities, capsys):
    with respx.mock(assert_all_called=True) as remote:
        remote.get("https://toolbox.test/v1/health").mock(return_value=httpx.Response(200, json={"status": "ok"}))
        remote.get("https://toolbox.test/v1/capabilities").mock(return_value=httpx.Response(200, json=capabilities))
        assert check_toolbox.main(["--base-url", "https://toolbox.test", "--provider", "docling"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"provider": "docling", "health": {"status": "ok"},
                       "capabilities": [{"name": "document.structure.extract"}]}


def test_diagnostic_reports_failure_and_closes_http_client(monkeypatch, capsys):
    from backend.tools.toolbox_client import ToolboxClient

    closed = []
    original = ToolboxClient.close

    async def close(client):
        await original(client)
        closed.append(client._client.is_closed)

    monkeypatch.setattr(ToolboxClient, "close", close)
    with respx.mock(assert_all_called=True) as remote:
        remote.get("https://toolbox.test/v1/health").mock(side_effect=httpx.ConnectError("offline"))
        assert check_toolbox.main(["--base-url", "https://toolbox.test"]) == 1
    output = capsys.readouterr()
    assert not output.out
    assert "ToolboxProviderUnavailable" in output.err
    assert closed == [True]
