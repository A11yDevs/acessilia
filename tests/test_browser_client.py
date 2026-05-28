import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from bot.clients.browser_client import GeminiBrowserClient


@pytest.fixture
def sample_jpg_bytes():
    img = Image.new("RGB", (100, 50), color="red")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def mock_page():
    page = MagicMock()
    page.evaluate = AsyncMock(return_value="1")
    page.locator = MagicMock()
    page.keyboard = MagicMock()
    page.keyboard.type = AsyncMock()
    page.keyboard.press = AsyncMock()
    page.set_default_timeout = MagicMock()
    page.goto = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    page.title = AsyncMock(return_value="Gemini")
    return page


@pytest.fixture
def mock_context(mock_page):
    context = MagicMock()
    context.new_page = AsyncMock(return_value=mock_page)
    context.add_cookies = AsyncMock()
    context.cookies = AsyncMock(return_value=[])
    return context


@pytest.fixture
def mock_browser(mock_context):
    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=mock_context)
    browser.close = AsyncMock()
    return browser


@pytest.fixture
def mock_playwright(mock_browser):
    pw = MagicMock()
    pw.chromium = MagicMock()
    pw.chromium.launch = AsyncMock(return_value=mock_browser)
    pw.stop = AsyncMock()
    return pw


@patch("playwright.async_api.async_playwright")
def test_health_check_success(mock_async_pw, mock_playwright, mock_page):
    mock_async_pw.return_value.start = AsyncMock(return_value=mock_playwright)
    mock_page.title = AsyncMock(return_value="Gemini - Google")

    client = GeminiBrowserClient()
    result = client.health_check()

    import asyncio
    result = asyncio.run(result)

    assert result["status"] == "ok"
    assert "Gemini" in result["title"]


@patch("playwright.async_api.async_playwright")
def test_health_check_error(mock_async_pw):
    mock_async_pw.side_effect = ImportError("playwright not installed")

    client = GeminiBrowserClient()
    import asyncio
    result = asyncio.run(client.health_check())

    assert result["status"] == "error"
    assert "not installed" in result["detail"]


@patch("playwright.async_api.async_playwright")
def test_send_message_basic(mock_async_pw, mock_playwright, mock_page, mock_context):
    mock_async_pw.return_value.start = AsyncMock(return_value=mock_playwright)

    mock_locator_visible = MagicMock()
    mock_locator_visible.first = mock_locator_visible
    mock_locator_visible.last = mock_locator_visible
    mock_locator_visible.is_visible = AsyncMock(return_value=True)
    mock_locator_visible.click = AsyncMock()
    mock_locator_visible.inner_text = AsyncMock(return_value="Resposta gerada")
    mock_locator_visible.wait_for_element_state = AsyncMock()

    mock_page.locator = MagicMock(return_value=mock_locator_visible)
    mock_page.wait_for_timeout = AsyncMock()
    mock_page.goto = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)

    client = GeminiBrowserClient()
    import asyncio
    result = asyncio.run(client.send_message(text="Descreva esta imagem"))

    assert "Resposta" in result


@patch("playwright.async_api.async_playwright")
def test_send_message_with_image(mock_async_pw, mock_playwright, mock_page, sample_jpg_bytes):
    mock_async_pw.return_value.start = AsyncMock(return_value=mock_playwright)

    mock_locator = MagicMock()
    mock_locator.first = mock_locator
    mock_locator.last = mock_locator
    mock_locator.is_visible = AsyncMock(return_value=True)
    mock_locator.click = AsyncMock()
    mock_locator.inner_text = AsyncMock(return_value="Imagem processada")
    mock_locator.wait_for_element_state = AsyncMock()
    mock_locator.set_input_files = AsyncMock()

    mock_page.locator = MagicMock(return_value=mock_locator)
    mock_page.wait_for_timeout = AsyncMock()
    mock_page.goto = AsyncMock()

    client = GeminiBrowserClient()
    import asyncio
    result = asyncio.run(
        client.send_message(text="Analise", images=[sample_jpg_bytes])
    )

    assert result


@patch("playwright.async_api.async_playwright")
def test_send_message_empty_response_retry(mock_async_pw, mock_playwright, mock_page):
    mock_async_pw.return_value.start = AsyncMock(return_value=mock_playwright)

    mock_locator = MagicMock()
    mock_locator.first = mock_locator
    mock_locator.last = mock_locator
    mock_locator.is_visible = AsyncMock(return_value=True)
    mock_locator.click = AsyncMock()
    mock_locator.inner_text = AsyncMock(return_value="")
    mock_locator.wait_for_element_state = AsyncMock()
    mock_locator.set_input_files = AsyncMock()

    mock_page.locator = MagicMock(return_value=mock_locator)

    mock_page.evaluate = AsyncMock(return_value="")
    mock_page.wait_for_timeout = AsyncMock()
    mock_page.goto = AsyncMock()

    client = GeminiBrowserClient()
    import asyncio
    result = asyncio.run(
        client.send_message(text="teste", max_empty_retries=1)
    )

    assert "[Erro" in result


def test_reset_session():
    client = GeminiBrowserClient()
    client._conversation_started = True
    client.reset_session()
    assert client._conversation_started is False


@patch("playwright.async_api.async_playwright")
def test_close_cleanup(mock_async_pw):
    mock_instance = MagicMock()
    mock_async_pw.return_value.start = AsyncMock(return_value=mock_instance)

    client = GeminiBrowserClient()
    client._playwright = mock_instance
    client._playwright.close = AsyncMock()
    client._browser = MagicMock()
    client._browser.close = AsyncMock()
    client._context = MagicMock()
    client._context.close = AsyncMock()
    client._page = MagicMock()
    client._page.close = AsyncMock()

    import asyncio
    asyncio.run(client.close())

    assert client._page is None
    assert client._browser is None


@patch("playwright.async_api.async_playwright")
def test_import_error_raised(mock_async_pw):
    mock_async_pw.side_effect = ImportError("no module")

    client = GeminiBrowserClient()
    import asyncio

    with pytest.raises(ImportError):
        asyncio.run(client.send_message(text="teste"))
