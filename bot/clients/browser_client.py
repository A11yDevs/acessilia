import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Optional

from bot.utils.logger import logger
from config.settings import settings

COOKIE_FILE = settings.data_dir / "gemini_cookies.json"


class GeminiBrowserClient:
    """Cliente que usa Playwright para interagir com gemini.google.com."""

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._gemini_url = settings.gemini_url
        self._headless = settings.browser_headless
        self._timeout = settings.request_timeout * 1000
        self._conversation_started = False

    async def health_check(self) -> dict:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return {"status": "error", "detail": "playwright not installed"}

        try:
            pw = await async_playwright().start()
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
            )
            page = await context.new_page()
            await page.goto(self._gemini_url, timeout=30000)
            title = await page.title()
            await browser.close()
            await pw.stop()
            return {"status": "ok", "title": title, "url": self._gemini_url}
        except Exception as e:
            return {"status": "error", "detail": str(e)}

    async def send_message(
        self,
        text: str,
        images: Optional[list[bytes]] = None,
        max_empty_retries: int = 2,
    ) -> str:
        if images is None:
            images = []
        for attempt in range(max_empty_retries + 1):
            try:
                result = await self._send_inner(text, images)
                if result.strip():
                    return result
                logger.warning("Gemini respondeu vazio (tentativa {})", attempt + 1)
                await self._start_new_conversation()
            except Exception as e:
                logger.error("Gemini error (tentativa {}): {}", attempt + 1, e)
                if attempt < max_empty_retries:
                    await self._start_new_conversation()
                else:
                    raise
        return "[Erro: Gemini retornou vazio após todas as tentativas]"

    async def _send_inner(self, text: str, images: list[bytes]) -> str:
        await self._ensure_browser()

        if not self._conversation_started:
            await self._start_new_conversation()

        for img_bytes in images:
            await self._upload_image(img_bytes)

        await self._type_prompt(text)
        response = await self._wait_for_response()
        return response

    async def _ensure_browser(self):
        if self._page and self._context and self._browser:
            try:
                await self._page.evaluate("1")
                return
            except Exception:
                logger.info("Pagina do browser morreu, recriando...")

        try:
            from playwright.async_api import async_playwright
        except ImportError as e:
            raise RuntimeError(
                "Playwright nao instalado. Execute: pip install playwright && playwright install chromium"
            ) from e

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self._headless,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
        )

        user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        )

        self._context = await self._browser.new_context(
            user_agent=user_agent,
            viewport={"width": 1280, "height": 800},
            locale="pt-BR",
        )

        await self._load_cookies()

        self._page = await self._context.new_page()
        self._page.set_default_timeout(self._timeout)

        await self._page.goto(self._gemini_url, wait_until="domcontentloaded")
        await self._page.wait_for_timeout(3000)

        await self._handle_dismissibles()
        self._conversation_started = False

    async def _start_new_conversation(self):
        self._conversation_started = False
        if self._page:
            try:
                await self._page.goto(self._gemini_url, wait_until="domcontentloaded")
                await self._page.wait_for_timeout(3000)
                await self._handle_dismissibles()
            except Exception as e:
                logger.warning("Erro ao navegar para nova conversa: {}", e)

            try:
                escrever_btn = self._page.locator(
                    "button:has-text('Escrever'), "
                    "button[aria-label*='Escrever'], "
                    "button:has-text('New chat'), "
                    "button:has-text('Nova conversa')"
                ).first
                if await escrever_btn.is_visible(timeout=3000):
                    await escrever_btn.click()
                    await self._page.wait_for_timeout(2000)
                    self._conversation_started = True
                    return
            except Exception:
                pass

        if self._page is None:
            await self._ensure_browser()

        self._conversation_started = True

    async def _handle_dismissibles(self):
        dismiss_selectors = [
            "button:has-text('Aceitar')",
            "button:has-text('Accept')",
            "button:has-text('Concordo')",
            "button:has-text('I agree')",
            "button:has-text('Recusar')",
            "button:has-text('Decline')",
            "button[aria-label*='close']",
            "button[aria-label*='fechar']",
            ".consent-button",
            "button:has-text('Continuar')",
            "button:has-text('Continue')",
            "button:has-text('Fechar')",
        ]
        for selector in dismiss_selectors:
            try:
                btn = self._page.locator(selector).first
                if await btn.is_visible(timeout=2000):
                    await btn.click(timeout=3000)
                    await self._page.wait_for_timeout(1000)
                    logger.debug("Dismissed: {}", selector)
            except Exception:
                pass

    async def _upload_image(self, img_bytes: bytes):
        file_input_selectors = [
            "input[type='file']",
            "input[accept*='image']",
            "input[accept*='png']",
            "input[accept*='jpeg']",
            ".hidden-local-upload-button",
            ".hidden-local-file-upload-button",
        ]

        upload_button_selectors = [
            "button[aria-label*='Abrir o menu de envio de arquivo']",
            "button[aria-label*='upload']",
            "button[aria-label*='Upload']",
            "button[aria-label*='anexar']",
            "button[aria-label*='Anexar']",
            "button[aria-label*='attach']",
            "button[aria-label*='Attach']",
            "button[aria-label*='imagem']",
            "button[aria-label*='Imagem']",
            "button[aria-label*='image']",
            "button[aria-label*='Image']",
            "[data-test-id='file-upload-button']",
            "button:has-text('📷')",
            "button:has-text('🖼️')",
        ]

        tmp_file = None
        try:
            fd, tmp_path = tempfile.mkstemp(suffix=".jpg")
            os.close(fd)
            tmp_file = tmp_path
            with open(tmp_path, "wb") as f:
                f.write(img_bytes)

            for selector in file_input_selectors:
                try:
                    file_input = self._page.locator(selector).first
                    if await file_input.is_visible(timeout=2000):
                        await file_input.set_input_files(tmp_path)
                        await self._page.wait_for_timeout(2000)
                        return
                except Exception:
                    pass

            for selector in upload_button_selectors:
                try:
                    btn = self._page.locator(selector).first
                    if await btn.is_visible(timeout=2000):
                        async with self._page.expect_file_chooser() as fc_info:
                            await btn.click()
                        file_chooser = await fc_info.value
                        await file_chooser.set_files(tmp_path)
                        await self._page.wait_for_timeout(2000)
                        return
                except Exception:
                    pass

            try:
                async with self._page.expect_file_chooser() as fc_info:
                    await self._page.keyboard.press("Control+Shift+U")
                file_chooser = await fc_info.value
                await file_chooser.set_files(tmp_path)
                await self._page.wait_for_timeout(2000)
                return
            except Exception:
                pass

            try:
                file_input = self._page.locator("input[type='file']").first
                await file_input.set_input_files(tmp_path)
                await self._page.wait_for_timeout(2000)
                return
            except Exception:
                pass

            raise RuntimeError(
                "Nao foi possivel fazer upload da imagem. "
                "Verifique se o seletor de upload do Gemini mudou. "
                "Tente definir BROWSER_HEADLESS=false para depuracao visual."
            )

        finally:
            if tmp_file and os.path.exists(tmp_file):
                os.unlink(tmp_file)

    async def _type_prompt(self, text: str):
        prompt_selectors = [
            "rich-textarea",
            "div[contenteditable='true']",
            "#prompt-textarea",
            "textarea",
            "[role='textbox']",
            ".input-area textarea",
            "div.text-input-container div[contenteditable]",
            "div:has(> rich-textarea)",
        ]

        for selector in prompt_selectors:
            try:
                input_elem = self._page.locator(selector).first
                if await input_elem.is_visible(timeout=3000):
                    await input_elem.click()
                    await self._page.wait_for_timeout(500)
                    await self._page.keyboard.type(text, delay=5)
                    await self._page.wait_for_timeout(500)
                    break
            except Exception:
                continue
        else:
            try:
                await self._page.keyboard.press("Tab")
                await self._page.wait_for_timeout(500)
                await self._page.keyboard.type(text, delay=5)
                await self._page.wait_for_timeout(500)
            except Exception as e:
                raise RuntimeError(
                    "Nao foi possivel digitar o prompt no Gemini. "
                    "O seletor do campo de texto pode ter mudado."
                ) from e

        send_selectors = [
            "button[aria-label*='Enviar mensagem']",
            "button.send-button",
            "button[aria-label*='send']",
            "button[aria-label*='Send']",
            "button[aria-label*='enviar']",
            "button[aria-label*='Enviar']",
            "button[data-test-id='send-button']",
            "button:has(> svg[data-icon='send'])",
        ]

        for selector in send_selectors:
            try:
                send_btn = self._page.locator(selector).first
                if await send_btn.is_visible(timeout=2000):
                    await send_btn.click()
                    break
            except Exception:
                continue
        else:
            await self._page.keyboard.press("Enter")

    async def _wait_for_response(self) -> str:
        stop_selectors = [
            "button:has-text('Stop')",
            "button:has-text('Parar')",
            "button[aria-label*='stop']",
            "button[aria-label*='Stop']",
            "[data-test-id='stop-generation-button']",
            "button.stop-button",
        ]

        for selector in stop_selectors:
            try:
                stop_btn = self._page.locator(selector).first
                if await stop_btn.is_visible(timeout=5000):
                    await stop_btn.wait_for_element_state("hidden", timeout=120000)
                    break
            except Exception:
                continue

        await self._page.wait_for_timeout(2000)

        response_selectors = [
            ".response-content",
            "[data-message-type='response']",
            ".model-response-text",
            ".message-content",
            ".conversation-turn:last-child .response-text",
            ".gemini-response",
            "[data-test-id='response-text']",
            ".response-text",
            ".message:last-child",
            ".turn:last-child .text",
            "div[data-test-id*='response']",
            "div[class*='response']",
            "div[class*='message']:last-child",
            "div[class*='conversation-turn']:last-child .text",
        ]

        for selector in response_selectors:
            try:
                resp_elem = self._page.locator(selector).last
                if await resp_elem.is_visible(timeout=5000):
                    text = await resp_elem.inner_text()
                    if text.strip():
                        return text.strip()
            except Exception:
                continue

        try:
            text = await self._page.evaluate("""
                () => {
                    const turns = document.querySelectorAll('[class*="turn"], [class*="message"], [class*="conversation"]');
                    const last = turns[turns.length - 1];
                    if (last) return last.innerText;
                    return document.body.innerText;
                }
            """)
            return text.strip()
        except Exception:
            pass

        return ""

    async def _load_cookies(self):
        if COOKIE_FILE.exists():
            try:
                cookies = json.loads(COOKIE_FILE.read_text(encoding="utf-8"))
                await self._context.add_cookies(cookies)
                logger.info("Cookies carregados: {}", COOKIE_FILE)
            except Exception as e:
                logger.warning("Erro ao carregar cookies: {}", e)

    async def _save_cookies(self):
        if self._context:
            try:
                COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
                cookies = await self._context.cookies()
                COOKIE_FILE.write_text(
                    json.dumps(cookies, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                logger.info("Cookies salvos: {} ({} cookies)", COOKIE_FILE, len(cookies))
            except Exception as e:
                logger.warning("Erro ao salvar cookies: {}", e)

    def reset_session(self):
        self._conversation_started = False

    async def close(self):
        try:
            await self._save_cookies()
        except Exception as e:
            logger.warning("Erro ao salvar cookies no fechamento: {}", e)

        for thing in [self._page, self._context, self._browser, self._playwright]:
            if thing is not None:
                try:
                    await thing.close()
                except Exception:
                    pass
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
        self._conversation_started = False


client = GeminiBrowserClient()
