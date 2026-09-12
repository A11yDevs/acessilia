import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


BASE_DIR = Path(__file__).resolve().parent.parent.parent


@dataclass
class Settings:
    bot_token: str = field(default_factory=lambda: os.getenv("BOT_TOKEN", ""))
    max_file_size_mb: int = 50
    max_pages: int = int(os.getenv("MAX_PAGES", "50"))
    temp_dir: Path = field(
        default_factory=lambda: _path_from_env(
            "TEMP_DIR",
            Path(tempfile.gettempdir()) / "a11y-devs-describer" / "temp",
        )
    )
    data_dir: Path = field(
        default_factory=lambda: _path_from_env("DATA_DIR", BASE_DIR / "var" / "data")
    )
    logs_dir: Path = field(
        default_factory=lambda: _path_from_env("LOGS_DIR", BASE_DIR / "var" / "logs")
    )
    rapidocr_cache_dir: Path = field(
        default_factory=lambda: _path_from_env(
            "RAPIDOCR_CACHE_DIR",
            BASE_DIR / "var" / "cache" / "rapidocr",
        )
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
    structurer: str = os.getenv("STRUCTURER", "toolbox")
    docling_formula_enrichment: bool = field(
        default_factory=lambda: _bool_from_env_alias(
            ("DOCLING_FORMULA_ENRICHMENT",),
            True,
        )
    )
    formula_image_cascade: bool = field(
        default_factory=lambda: _bool_from_env_alias(
            ("FORMULA_IMAGE_CASCADE",),
            True,
        )
    )
    pipeline_engine: str = os.getenv("PIPELINE_ENGINE", "legacy")

    # Acessilia Toolbox settings
    toolbox_base_url: str = os.getenv("TOOLBOX_BASE_URL", "http://localhost:8002")
    toolbox_provider: str = os.getenv("TOOLBOX_PROVIDER", "docling")
    toolbox_api_key: str = os.getenv("TOOLBOX_API_KEY", "")
    toolbox_timeout_seconds: int = int(os.getenv("TOOLBOX_TIMEOUT_SECONDS", "3600"))
    toolbox_use_artifact_store: bool = field(
        default_factory=lambda: os.getenv("TOOLBOX_USE_ARTIFACT_STORE", "true").strip().lower()
        in {"1", "true", "yes", "on", "sim"},
    )
    toolbox_use_remote_cache: bool = field(
        default_factory=lambda: os.getenv("TOOLBOX_USE_REMOTE_CACHE", "true").strip().lower()
        in {"1", "true", "yes", "on", "sim"},
    )
    pddl_execute_dry_run: bool = field(
        default_factory=lambda: _bool_from_env_alias(
            ("PDDL_EXECUTE_DRY_RUN", "PMV_EXECUTE_DRY_RUN"),
            True,
        )
    )
    pddl_planner_backend: str = field(
        default_factory=lambda: _str_from_env_alias(
            ("PDDL_PLANNER_BACKEND", "PMV_PLANNER_BACKEND"),
            "internal",
        )
    )
    pddl_preferred_plan: str = field(
        default_factory=lambda: _str_from_env_alias(
            ("PDDL_PREFERRED_PLAN", "PMV_PREFERRED_PLAN"),
            "internal",
        )
    )
    pddl_fast_downward: str = field(
        default_factory=lambda: _str_from_env_alias(
            ("PDDL_FAST_DOWNWARD", "PMV_FAST_DOWNWARD"),
            "",
        )
    )
    pddl_fast_downward_alias: str = field(
        default_factory=lambda: _str_from_env_alias(
            ("PDDL_FAST_DOWNWARD_ALIAS", "PMV_FAST_DOWNWARD_ALIAS"),
            "",
        )
    )
    pddl_fast_downward_search: str = field(
        default_factory=lambda: _str_from_env_alias(
            ("PDDL_FAST_DOWNWARD_SEARCH", "PMV_FAST_DOWNWARD_SEARCH"),
            "astar(blind())",
        )
    )

    # Interface Settings
    enabled_interfaces: str = os.getenv("ENABLED_INTERFACES", "api,telegram,web")

    # API Settings (lazy defaults: environment state at instantiation, not import time)
    api_host: str = field(
        default_factory=lambda: os.getenv("API_HOST", "0.0.0.0"),
    )
    api_port: int = field(
        default_factory=lambda: int(os.getenv("API_PORT", "8000")),
    )
    api_base_url: str = field(
        default_factory=lambda: os.getenv("API_BASE_URL", "http://localhost:8000"),
    )
    web_base_url: str = field(
        default_factory=lambda: os.getenv("WEB_BASE_URL", "http://localhost:8001"),
    )
    web_port: int = field(
        default_factory=lambda: int(os.getenv("WEB_PORT", "8001")),
    )

    # Build info (injected via Docker build --build-arg or environment variables)
    git_commit: str = os.getenv("GIT_COMMIT", "")
    image_tag: str = os.getenv("IMAGE_TAG", "")
    image_digest: str = os.getenv("IMAGE_DIGEST", "")

    # I18N Settings
    # Preferred runtime locale. Blank means "negotiate from the process
    # environment (LOCALE/LANGUAGE) and, failing that, fall back to the
    # default en_US locale."
    locale: str = field(default_factory=lambda: os.getenv("LOCALE", "").strip())
    # Comma-separated list of locales the software makes available to remote
    # users. Anything outside this list is not offered as a bot-facing locale.
    i18n_locales_active: tuple[str, ...] = field(
        default_factory=lambda: _locales_from_env(
            os.getenv("I18N_LOCALES_ACTIVE", "en_US,pt_BR")
        )
    )

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
        self.rapidocr_cache_dir.mkdir(parents=True, exist_ok=True)

    # Backward-compatible aliases for the old PMV-prefixed configuration.
    @property
    def pmv_execute_dry_run(self) -> bool:
        return self.pddl_execute_dry_run

    @property
    def pmv_planner_backend(self) -> str:
        return self.pddl_planner_backend

    @property
    def pmv_preferred_plan(self) -> str:
        return self.pddl_preferred_plan

    @property
    def pmv_fast_downward(self) -> str:
        return self.pddl_fast_downward

    @property
    def pmv_fast_downward_alias(self) -> str:
        return self.pddl_fast_downward_alias

    @property
    def pmv_fast_downward_search(self) -> str:
        return self.pddl_fast_downward_search

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




def _str_from_env_alias(env_vars: tuple[str, ...], default: str) -> str:
    for env_var in env_vars:
        raw_value = os.getenv(env_var)
        if raw_value is not None:
            return raw_value
    return default


def _locales_from_env(raw_value: str) -> tuple[str, ...]:
    """Parse a comma-separated locale list from an environment string.

    Args:
        raw_value (str): Comma-separated locale identifiers read from I18N_LOCALES_ACTIVE; blank entries are dropped and the result keeps first-seen order with duplicates removed.

    Returns:
        tuple: Locally supported locale identifiers in declared order; an empty tuple when the input lists no usable entry.
    """
    seen: list[str] = []
    for entry in raw_value.split(","):
        locale = entry.strip()
        if locale and locale not in seen:
            seen.append(locale)
    return tuple(seen)


def _bool_from_env_alias(env_vars: tuple[str, ...], default: bool) -> bool:
    for env_var in env_vars:
        raw_value = os.getenv(env_var)
        if raw_value is not None:
            return raw_value.strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
                "sim",
            }
    return default


settings = Settings()
