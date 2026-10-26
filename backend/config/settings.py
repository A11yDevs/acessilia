import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from acessilia_sdk.toolbox.capabilities import provider_default

load_dotenv()


BASE_DIR = Path(__file__).resolve().parent.parent.parent


@dataclass
class Settings:
    bot_token: str = field(default_factory=lambda: os.getenv("BOT_TOKEN", ""))
    max_file_size_mb: int = field(
        default_factory=lambda: int(os.getenv("MAX_FILE_SIZE_MB", "50"))
    )
    # Documents with more pages are refused after structural extraction,
    # before planning and the vision-model calls. The limit is always enforced,
    # so it must be positive.
    max_pages: int = field(default_factory=lambda: int(os.getenv("MAX_PAGES", "50")))
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
    request_timeout: int = field(
        default_factory=lambda: int(os.getenv("REQUEST_TIMEOUT", "3600"))
    )
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    observability_api_token: str = field(
        default_factory=lambda: os.getenv("OBSERVABILITY_API_TOKEN", "")
    )
    allowed_extensions: set[str] = field(default_factory=lambda: _default_extensions())
    pdf_split_dpi: int = field(
        default_factory=lambda: int(os.getenv("PDF_SPLIT_DPI", "150"))
    )
    ai_client: str = field(default_factory=lambda: os.getenv("AI_CLIENT", "ollama"))
    ollama_api_key: str = field(default_factory=lambda: os.getenv("OLLAMA_API_KEY", ""))
    ollama_model: str = field(
        default_factory=lambda: os.getenv(
            "OLLAMA_MODEL",
            "nvidia/nemotron-nano-12b-v2-vl:free",
        )
    )
    ollama_base_url: str = field(
        default_factory=lambda: os.getenv(
            "OLLAMA_BASE_URL",
            "http://172.16.109.33:11434/api/chat",
        )
    )
    openrouter_api_key: str = field(
        default_factory=lambda: os.getenv("OPENROUTER_API_KEY", "")
    )
    openrouter_model: str = field(
        default_factory=lambda: os.getenv(
            "OPENROUTER_MODEL",
            "nvidia/nemotron-nano-12b-v2-vl:free",
        )
    )
    openrouter_max_tokens: int = field(
        default_factory=lambda: int(os.getenv("OPENROUTER_MAX_TOKENS", "4096"))
    )
    data_agent_max_tokens: int = field(
        default_factory=lambda: int(os.getenv("DATA_AGENT_MAX_TOKENS", "8192"))
    )
    # Table transcription on a local Ollama can run long with the 8192-token
    # budget, so the DataAgent keeps the historical 1h ceiling instead of the
    # tighter MODEL_CALL_TIMEOUT_SECONDS: long but legitimate generations
    # survive there, while vision regions degrade fast.
    data_agent_timeout_seconds: int = field(
        default_factory=lambda: int(os.getenv("DATA_AGENT_TIMEOUT_SECONDS", "3600"))
    )
    vision_region_max_tokens: int = field(
        default_factory=lambda: int(os.getenv("VISION_REGION_MAX_TOKENS", "2000"))
    )
    # How many picture descriptions run concurrently inside one job. The
    # UnifiedQueue already serializes jobs, so this bounds the load on the
    # model provider: 2 is safe for rate-limited hosted APIs and for a local
    # Ollama (whose server queues anything beyond its own parallelism). The
    # formula recognition stage shares the bound because its fallback is the
    # same vision model.
    vision_concurrency: int = field(
        default_factory=lambda: int(os.getenv("VISION_CONCURRENCY", "2"))
    )
    # Minimum agreement (0-1 F1 of letters, digits and math symbols) between
    # a recognized formula and the text-layer text it replaces. Below it the
    # recognition is taken as a misread and the formula keeps its text; the
    # correct LaTeX of the reference case scores 0.87-1.0 against its text
    # layer, a formula read from the wrong crop around 0.3.
    formula_text_agreement_min: float = field(
        default_factory=lambda: float(os.getenv("FORMULA_TEXT_AGREEMENT_MIN", "0.75"))
    )
    # Per-call HTTP timeout for the model clients (OpenRouter/Ollama), far
    # below REQUEST_TIMEOUT: a normal region answer takes 45-90s and a
    # legitimate full-budget generation stays under ~7 minutes, so a call
    # still running after this bound is hung, and the region degrades instead
    # of stalling the job for up to REQUEST_TIMEOUT. Callers with longer
    # legitimate answers override it (DATA_AGENT_TIMEOUT_SECONDS for tables).
    model_call_timeout_seconds: int = field(
        default_factory=lambda: int(os.getenv("MODEL_CALL_TIMEOUT_SECONDS", "600"))
    )
    # Reuse a stored vision answer for identical region content (same image
    # bytes, prompt, model and budget), so retries and restarted jobs do not
    # pay for descriptions again. Keyed on content, so it also deduplicates
    # identical images across pages.
    vision_region_cache_enabled: bool = field(
        default_factory=lambda: (
            os.getenv("VISION_REGION_CACHE_ENABLED", "true").strip().lower()
            in {"1", "true", "yes", "on", "sim"}
        ),
    )
    openrouter_base_url: str = field(
        default_factory=lambda: os.getenv(
            "OPENROUTER_BASE_URL",
            "https://openrouter.ai/api/v1/chat/completions",
        )
    )
    openrouter_site_url: str = field(
        default_factory=lambda: os.getenv("OPENROUTER_SITE_URL", "")
    )
    openrouter_app_name: str = field(
        default_factory=lambda: os.getenv(
            "OPENROUTER_APP_NAME",
            "a11y-devs-describer",
        )
    )
    pipeline_engine: str = field(
        default_factory=lambda: os.getenv("PIPELINE_ENGINE", "pddl")
    )
    # Legacy PDF Unicode repair (phase B): "off", "detect" or "repair".
    # "detect" only records the observation and the warning; "repair" applies
    # NFC, the dotless-i rule and spacing diacritics to prose, headers/footers
    # and table cells. The default preserves the previous behavior.
    legacy_unicode_repair: str = field(
        default_factory=lambda: os.getenv("LEGACY_UNICODE_REPAIR", "off").strip().lower()
    )
    # Inline math in the prose of a PDF (#265, ADR 0011): "fonts" reads the text
    # layer's math fonts and baselines through the Toolbox's document.text.spans
    # and writes each expression as $…$; "off" leaves the text as extracted.
    inline_math_detection: str = field(
        default_factory=lambda: os.getenv("INLINE_MATH_DETECTION", "fonts").strip().lower()
    )

    # Fusão multi-provider (Fase 4 do plano docstruct)
    # "single": comportamento atual (um provider, fallback PyMuPDF).
    # "dual": extrai com dois providers e funde via docstruct.fusion.
    fusion_mode: str = field(default_factory=lambda: os.getenv("FUSION_MODE", "single"))
    fusion_secondary_provider: str = field(
        default_factory=lambda: os.getenv("FUSION_SECONDARY_PROVIDER", "mineru")
    )
    # Provider MinerU hybrid-VLM (MinerU 3.x, backend=hybrid-engine). É a fonte B
    # do melhor resultado confirmado no leaderboard do Dr.DocBench
    # (differ-v15-hyb, EvalAI 70.37). Use FUSION_SECONDARY_PROVIDER=mineru-hyb
    # para adotá-lo na fusão dual.
    fusion_hybrid_provider: str = field(
        default_factory=lambda: os.getenv("FUSION_HYBRID_PROVIDER", "mineru-hyb")
    )
    # Pages per document the VLM judge may adjudicate in dual fusion: the
    # deterministic router settles the rest, and 0 turns the judge off.
    fusion_judge_max_pages: int = field(
        default_factory=lambda: int(os.getenv("FUSION_JUDGE_MAX_PAGES", "5"))
    )
    # Take the secondary provider's page where the deterministic router prefers
    # it (tables, formulas, a nearly empty primary page); false keeps every page
    # from the primary provider, as before.
    fusion_apply_page_routes: bool = field(
        default_factory=lambda: (
            os.getenv("FUSION_APPLY_PAGE_ROUTES", "true").strip().lower()
            in {"1", "true", "yes", "on", "sim"}
        )
    )

    # Acessilia Toolbox settings
    toolbox_base_url: str = field(
        default_factory=lambda: os.getenv("TOOLBOX_BASE_URL", "http://localhost:8002")
    )
    # Comma-separated URLs of *independent* Toolbox deployments, tried in order
    # by the capability clients (docs/adr/0006). Empty means TOOLBOX_BASE_URL
    # only, which should point at the load balancer in front of the replicas.
    toolbox_base_urls: str = field(
        default_factory=lambda: os.getenv("TOOLBOX_BASE_URLS", "")
    )
    # Structural extraction keeps the historical TOOLBOX_PROVIDER variable for
    # backward compatibility. Specialized capabilities use providers bound to
    # their own contracts in the Toolbox registry. Every default comes from
    # libs/sdk/src/acessilia_sdk/toolbox/capabilities.py.
    toolbox_provider: str = field(
        default_factory=lambda: os.getenv(
            "TOOLBOX_PROVIDER", provider_default("toolbox_provider")
        )
    )
    toolbox_layout_provider: str = field(
        default_factory=lambda: os.getenv(
            "TOOLBOX_LAYOUT_PROVIDER", provider_default("toolbox_layout_provider")
        )
    )
    toolbox_pdf_provider: str = field(
        default_factory=lambda: os.getenv(
            "TOOLBOX_PDF_PROVIDER", provider_default("toolbox_pdf_provider")
        )
    )
    toolbox_math_recognize_provider: str = field(
        default_factory=lambda: os.getenv(
            "TOOLBOX_MATH_RECOGNIZE_PROVIDER",
            provider_default("toolbox_math_recognize_provider"),
        )
    )
    toolbox_math_provider: str = field(
        default_factory=lambda: os.getenv(
            "TOOLBOX_MATH_PROVIDER", provider_default("toolbox_math_provider")
        )
    )
    toolbox_ocr_provider: str = field(
        default_factory=lambda: os.getenv(
            "TOOLBOX_OCR_PROVIDER", provider_default("toolbox_ocr_provider")
        )
    )
    toolbox_page_ocr_provider: str = field(
        default_factory=lambda: os.getenv(
            "TOOLBOX_PAGE_OCR_PROVIDER", provider_default("toolbox_page_ocr_provider")
        )
    )
    toolbox_adjudicate_provider: str = field(
        default_factory=lambda: os.getenv(
            "TOOLBOX_ADJUDICATE_PROVIDER", provider_default("toolbox_adjudicate_provider")
        )
    )
    toolbox_table_provider: str = field(
        default_factory=lambda: os.getenv(
            "TOOLBOX_TABLE_PROVIDER", provider_default("toolbox_table_provider")
        )
    )
    toolbox_orientation_provider: str = field(
        default_factory=lambda: os.getenv(
            "TOOLBOX_ORIENTATION_PROVIDER", provider_default("toolbox_orientation_provider")
        )
    )
    toolbox_media_inspect_provider: str = field(
        default_factory=lambda: os.getenv(
            "TOOLBOX_MEDIA_INSPECT_PROVIDER",
            provider_default("toolbox_media_inspect_provider"),
        )
    )
    toolbox_pdf_ua_provider: str = field(
        default_factory=lambda: os.getenv(
            "TOOLBOX_PDF_UA_PROVIDER", provider_default("toolbox_pdf_ua_provider")
        )
    )
    # PDF/UA is rendered only by the Toolbox (pinned Pandoc + TeX Live); there
    # is no local fallback (docs/adr/0003). When false, the format is skipped.
    toolbox_pdf_ua_enabled: bool = field(
        default_factory=lambda: (
            os.getenv("TOOLBOX_PDF_UA_ENABLED", "true").strip().lower()
            in {"1", "true", "yes", "on", "sim"}
        ),
    )
    # Matches the capability's timeout_hint_seconds (180) with margin, so a
    # hung renderer is reported as an optional export error within minutes.
    toolbox_pdf_ua_timeout_seconds: int = field(
        default_factory=lambda: int(os.getenv("TOOLBOX_PDF_UA_TIMEOUT_SECONDS", "300"))
    )
    toolbox_pdf_validate_provider: str = field(
        default_factory=lambda: os.getenv(
            "TOOLBOX_PDF_VALIDATE_PROVIDER",
            provider_default("toolbox_pdf_validate_provider"),
        )
    )
    # The PDF/UA is audited with veraPDF on the Toolbox (pdf.validate.pdf_ua)
    # and the result e-mail summarizes it. When false, no audit is made.
    toolbox_pdf_validate_enabled: bool = field(
        default_factory=lambda: (
            os.getenv("TOOLBOX_PDF_VALIDATE_ENABLED", "true").strip().lower()
            in {"1", "true", "yes", "on", "sim"}
        ),
    )
    # Above the capability's timeout_hint_seconds (300), like the exports.
    toolbox_pdf_validate_timeout_seconds: int = field(
        default_factory=lambda: int(os.getenv("TOOLBOX_PDF_VALIDATE_TIMEOUT_SECONDS", "330"))
    )
    # Failed rules the result e-mail lists; the rest are in the report packaged
    # with the files.
    pdf_ua_audit_max_rules: int = field(
        default_factory=lambda: int(os.getenv("PDF_UA_AUDIT_MAX_RULES", "10"))
    )
    # Share of a slide its pictures must cover for a presentation slide to be
    # described by the vision model as one image instead of read as text.
    slide_visual_coverage: float = field(
        default_factory=lambda: float(os.getenv("SLIDE_VISUAL_COVERAGE", "0.5"))
    )
    # On a slide read as text, fold the short text lying on or just around a
    # picture (its labels) into that picture, whose description transcribes
    # them in place, and merge the pictures a caption row spans.
    slide_fold_figure_labels: bool = field(
        default_factory=lambda: (
            os.getenv("SLIDE_FOLD_FIGURE_LABELS", "true").strip().lower()
            in {"1", "true", "yes", "on", "sim"}
        )
    )
    toolbox_docx_provider: str = field(
        default_factory=lambda: os.getenv(
            "TOOLBOX_DOCX_PROVIDER", provider_default("toolbox_docx_provider")
        )
    )
    # DOCX is rendered only by the Toolbox (pinned Pandoc); there is no local
    # fallback (docs/adr/0003). When false, the format is skipped.
    toolbox_docx_enabled: bool = field(
        default_factory=lambda: (
            os.getenv("TOOLBOX_DOCX_ENABLED", "true").strip().lower()
            in {"1", "true", "yes", "on", "sim"}
        ),
    )
    # Same margin over the capability's timeout_hint_seconds (180) as PDF/UA.
    toolbox_docx_timeout_seconds: int = field(
        default_factory=lambda: int(os.getenv("TOOLBOX_DOCX_TIMEOUT_SECONDS", "300"))
    )
    # media.inspect runs only on the Toolbox (docs/adr/0003). When false, the
    # step is skipped; a Toolbox failure degrades the run visibly.
    toolbox_media_inspect_enabled: bool = field(
        default_factory=lambda: (
            os.getenv("TOOLBOX_MEDIA_INSPECT_ENABLED", "true").strip().lower()
            in {"1", "true", "yes", "on", "sim"}
        ),
    )
    toolbox_api_key: str = field(
        default_factory=lambda: os.getenv("TOOLBOX_API_KEY", "")
    )
    toolbox_timeout_seconds: int = field(
        default_factory=lambda: int(os.getenv("TOOLBOX_TIMEOUT_SECONDS", "3600"))
    )
    # Bounded retries after a timeout or an unavailable instance, on the same
    # endpoint, with exponential backoff and jitter (docs/adr/0006). Toolbox
    # capabilities are idempotent: pure functions of their input, or
    # content-addressed for the artifact store. 0 disables retries. A timeout
    # is retried too, so a hung call can take up to
    # TOOLBOX_TIMEOUT_SECONDS * (TOOLBOX_RETRIES + 1) per endpoint.
    toolbox_retries: int = field(
        default_factory=lambda: int(os.getenv("TOOLBOX_RETRIES", "1"))
    )
    toolbox_retry_backoff_seconds: float = field(
        default_factory=lambda: float(os.getenv("TOOLBOX_RETRY_BACKOFF_SECONDS", "0.5"))
    )
    # Availability gate for planning methods that call the Toolbox: "observe"
    # only reports what the live catalogue would rule out, "enforce" removes
    # those methods from the plan (failing closed without a catalogue), "off"
    # skips the check.
    toolbox_availability_gate: str = field(
        default_factory=lambda: os.getenv(
            "TOOLBOX_AVAILABILITY_GATE", "observe"
        ).strip().lower()
    )
    toolbox_catalog_refresh_seconds: int = field(
        default_factory=lambda: int(os.getenv("TOOLBOX_CATALOG_REFRESH_SECONDS", "60"))
    )
    toolbox_catalog_stale_seconds: int = field(
        default_factory=lambda: int(os.getenv("TOOLBOX_CATALOG_STALE_SECONDS", "900"))
    )
    toolbox_use_artifact_store: bool = field(
        default_factory=lambda: (
            os.getenv("TOOLBOX_USE_ARTIFACT_STORE", "true").strip().lower()
            in {"1", "true", "yes", "on", "sim"}
        ),
    )
    toolbox_use_remote_cache: bool = field(
        default_factory=lambda: (
            os.getenv("TOOLBOX_USE_REMOTE_CACHE", "true").strip().lower()
            in {"1", "true", "yes", "on", "sim"}
        ),
    )
    # edge-tts voice for MP3 export. Microsoft retires voices from the
    # catalogue (pt-BR-ThalitaNeural left it in 2026-10), so keep it swappable.
    tts_voice: str = field(
        default_factory=lambda: os.getenv("TTS_VOICE", "pt-BR-FranciscaNeural")
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
    pddl_max_replans: int = int(
        os.getenv("PDDL_MAX_REPLANS", os.getenv("PMV_MAX_REPLANS", "2"))
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
    enabled_interfaces: str = field(
        default_factory=lambda: os.getenv("ENABLED_INTERFACES", "api,telegram,web")
    )

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
    git_commit: str = field(default_factory=lambda: os.getenv("GIT_COMMIT", ""))
    image_tag: str = field(default_factory=lambda: os.getenv("IMAGE_TAG", ""))
    image_digest: str = field(default_factory=lambda: os.getenv("IMAGE_DIGEST", ""))

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
    smtp_server: str = field(
        default_factory=lambda: os.getenv("SMTP_SERVER", "smtp.gmail.com")
    )
    smtp_port: int = field(default_factory=lambda: int(os.getenv("SMTP_PORT", "587")))
    smtp_user: str = field(default_factory=lambda: os.getenv("SMTP_USER", ""))
    smtp_password: str = field(default_factory=lambda: os.getenv("SMTP_PASSWORD", ""))
    smtp_from: str = field(default_factory=lambda: os.getenv("SMTP_FROM", ""))
    smtp_name: str = field(default_factory=lambda: os.getenv("SMTP_NAME", "Bot Acess"))

    def __post_init__(self) -> None:
        # Fail at startup, not inside the first job that builds a Toolbox client.
        if self.max_pages < 1:
            raise ValueError(f"MAX_PAGES must be positive, got {self.max_pages}")
        if self.toolbox_retries < 0:
            raise ValueError(f"TOOLBOX_RETRIES must be zero or positive, got {self.toolbox_retries}")
        if self.toolbox_retry_backoff_seconds < 0:
            raise ValueError(
                "TOOLBOX_RETRY_BACKOFF_SECONDS must be zero or positive, "
                f"got {self.toolbox_retry_backoff_seconds}"
            )
        if self.pdf_ua_audit_max_rules < 0:
            raise ValueError(
                f"PDF_UA_AUDIT_MAX_RULES must be zero or positive, got {self.pdf_ua_audit_max_rules}"
            )
        if not 0 < self.slide_visual_coverage <= 1:
            raise ValueError(
                "SLIDE_VISUAL_COVERAGE must be greater than 0 and at most 1, "
                f"got {self.slide_visual_coverage}"
            )
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

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
