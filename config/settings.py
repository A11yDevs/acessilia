import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


BASE_DIR = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    bot_token: str = field(default_factory=lambda: os.getenv("BOT_TOKEN", ""))
    max_file_size_mb: int = int(os.getenv("MAX_FILE_SIZE_MB", "50"))
    max_pages: int = int(os.getenv("MAX_PAGES", "50"))
    temp_dir: Path = field(
        default_factory=lambda: _path_from_env(
            "TEMP_DIR",
            Path(tempfile.gettempdir()) / "a11y-devs-describer" / "temp",
        )
    )
    data_dir: Path = field(
        default_factory=lambda: _path_from_env("DATA_DIR", BASE_DIR / "data")
    )
    logs_dir: Path = field(
        default_factory=lambda: _path_from_env("LOGS_DIR", BASE_DIR / "logs")
    )
    request_timeout: int = int(os.getenv("REQUEST_TIMEOUT", "3600"))
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    allowed_extensions: set[str] = field(default_factory=lambda: _default_extensions())
    tesseract_cmd: str = os.getenv("TESSERACT_CMD", "tesseract")
    max_page_width: int = int(os.getenv("MAX_PAGE_WIDTH", "1600"))
    jpg_quality: int = int(os.getenv("JPG_QUALITY", "85"))
    pdf_split_dpi: int = int(os.getenv("PDF_SPLIT_DPI", "150"))
    ai_client: str = os.getenv("AI_CLIENT", "ollama")
    ollama_api_key: str = os.getenv("OLLAMA_API_KEY", "")
    ollama_model: str = os.getenv(
        "OLLAMA_MODEL",
        "nvidia/nemotron-nano-12b-v2-vl:free",
    )
    ollama_base_url: str = os.getenv(
        "OLLAMA_BASE_URL",
        "http://172.16.109.33:11434/api/chat",
    )
    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
    openrouter_model: str = os.getenv(
        "OPENROUTER_MODEL",
        "nvidia/nemotron-nano-12b-v2-vl:free",
    )
    openrouter_base_url: str = os.getenv(
        "OPENROUTER_BASE_URL",
        "https://openrouter.ai/api/v1/chat/completions",
    )
    openrouter_site_url: str = os.getenv("OPENROUTER_SITE_URL", "")
    openrouter_app_name: str = os.getenv(
        "OPENROUTER_APP_NAME",
        "a11y-devs-describer",
    )
    pymupdf_text_threshold: int = int(os.getenv("PYMUPDF_TEXT_THRESHOLD", "100"))
    structurer: str = os.getenv("STRUCTURER", "pymupdf")

    # Interface Settings
    enabled_interfaces: str = os.getenv("ENABLED_INTERFACES", "telegram,web")

    # Web URL (for download links in emails)
    web_url: str = os.getenv("WEB_URL", "http://localhost:8000")

    # SMTP Settings
    smtp_server: str = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_user: str = os.getenv("SMTP_USER", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_from: str = os.getenv("SMTP_FROM", "")
    smtp_name: str = os.getenv("SMTP_NAME", "Bot Acess")

    def __post_init__(self) -> None:
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    @property
    def bot_token_valid(self) -> bool:
        return bool(self.bot_token)

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    @property
    def db_path(self) -> Path:
        return self.data_dir / "history.db"


def _default_extensions() -> set[str]:
    return {
        ".pdf",
        ".png",
        ".jpg",
        ".jpeg",
        ".tiff",
        ".tif",
        ".bmp",
        ".gif",
        ".webp",
        ".docx",
        ".html",
    }


def _path_from_env(env_var: str, default: Path) -> Path:
    raw_value = os.getenv(env_var)
    path = Path(raw_value).expanduser() if raw_value else default
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


settings = Settings()
