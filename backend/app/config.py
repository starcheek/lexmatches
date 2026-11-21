"""Runtime configuration, read once from environment variables."""
import os
from dataclasses import dataclass, field


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


DEV_JWT_SECRET = "dev-insecure-jwt-secret-change-me-0123456789"


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL", "postgresql://lexmatches:lexmatches@localhost:5544/lexmatches"))
    jwt_secret: str = field(default_factory=lambda: _env("JWT_SECRET", DEV_JWT_SECRET))
    jwt_ttl_hours: int = field(default_factory=lambda: int(_env("JWT_TTL_HOURS", "168")))
    # Set on the server (deploy/server-setup.sh). Its presence marks production: insecure defaults are refused.
    site_domain: str = field(default_factory=lambda: _env("SITE_DOMAIN"))

    s3_endpoint: str = field(default_factory=lambda: _env("S3_ENDPOINT", "http://localhost:9200"))
    s3_access_key: str = field(default_factory=lambda: _env("S3_ACCESS_KEY", "lexmatches"))
    s3_secret_key: str = field(default_factory=lambda: _env("S3_SECRET_KEY", "lexmatches-secret"))
    s3_bucket: str = field(default_factory=lambda: _env("S3_BUCKET", "books"))

    # Translation: "auto" = Claude when ANTHROPIC_API_KEY is set, otherwise mock.
    translator: str = field(default_factory=lambda: _env("TRANSLATOR", "auto"))
    anthropic_api_key: str = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))
    anthropic_model: str = field(default_factory=lambda: _env("ANTHROPIC_MODEL", "claude-opus-5-5"))
    anthropic_effort: str = field(default_factory=lambda: _env("ANTHROPIC_EFFORT", "low"))
    # "default" enables server-side refusal fallbacks on models that support them; "off" disables.
    anthropic_fallbacks: str = field(default_factory=lambda: _env("ANTHROPIC_FALLBACKS", "default"))

    # TTS
    tts_provider: str = field(default_factory=lambda: _env("TTS_PROVIDER", "piper"))
    piper_voices_dir: str = field(default_factory=lambda: _env("PIPER_VOICES_DIR", "/data/piper"))
    piper_voices: str = field(default_factory=lambda: _env("PIPER_VOICES"))  # "fr=fr_FR-tom-medium,en=..."
    piper_length_scale: float = field(default_factory=lambda: float(_env("PIPER_LENGTH_SCALE", "1.1")))
    # Voices downloaded in the background at startup: "all" (configured languages), "none", or "fr,en"
    piper_preload: str = field(default_factory=lambda: _env("PIPER_PRELOAD", "all"))
    piper_threads: int = field(default_factory=lambda: int(_env("PIPER_THREADS", "2")))  # onnxruntime threads per synthesis
    tts_workers: int = field(default_factory=lambda: int(_env("TTS_WORKERS", "2")))  # concurrent syntheses
    tts_rate_per_min: int = field(default_factory=lambda: int(_env("TTS_RATE_PER_MIN", "120")))  # per user
    tts_cache_days: int = field(default_factory=lambda: int(_env("TTS_CACHE_DAYS", "30")))  # bucket lifecycle on tts/
    xai_api_key: str = field(default_factory=lambda: _env("XAI_API_KEY"))  # TTS_PROVIDER=xai (Grok voices)
    xai_voice: str = field(default_factory=lambda: _env("XAI_VOICE", "eve"))

    # Billing (off unless STRIPE_SECRET_KEY is set)
    stripe_secret_key: str = field(default_factory=lambda: _env("STRIPE_SECRET_KEY"))
    stripe_price_id: str = field(default_factory=lambda: _env("STRIPE_PRICE_ID", "price_1SZqBJKB40NOyEkPeUH1dv8i"))

    # Bearer token for /api/admin/analytics/* (those endpoints answer 404 while it is empty)
    admin_token: str = field(default_factory=lambda: _env("ADMIN_TOKEN"))

    # New accounts start with the sample books in backend/seed (app/seed.py); "0" turns that off.
    seed_books: bool = field(default_factory=lambda: _env("SEED_BOOKS", "1") != "0")

    # Cloudflare Turnstile on sign-up (off while TURNSTILE_SECRET_KEY is empty)
    turnstile_site_key: str = field(default_factory=lambda: _env("TURNSTILE_SITE_KEY"))
    turnstile_secret_key: str = field(default_factory=lambda: _env("TURNSTILE_SECRET_KEY"))

    # Cost limits per day: pages started for translation and newly synthesized speech characters per user,
    # pages for the whole site (0 = no limit)
    daily_page_limit: int = field(default_factory=lambda: int(_env("DAILY_PAGE_LIMIT", "50")))
    global_daily_page_limit: int = field(default_factory=lambda: int(_env("GLOBAL_DAILY_PAGE_LIMIT", "1000")))
    daily_tts_chars: int = field(default_factory=lambda: int(_env("DAILY_TTS_CHARS", "200000")))
    # Analytics events/sessions and logged server errors older than this are deleted daily
    retention_days: int = field(default_factory=lambda: int(_env("RETENTION_DAYS", "90")))

    max_upload_mb: int = field(default_factory=lambda: int(_env("MAX_UPLOAD_MB", "25")))
    job_workers: int = field(default_factory=lambda: int(_env("JOB_WORKERS", "4")))  # page translations at once
    book_workers: int = field(default_factory=lambda: int(_env("BOOK_WORKERS", "1")))  # uploaded books split at once

    @property
    def billing_enabled(self) -> bool:
        return bool(self.stripe_secret_key)

    @property
    def translator_kind(self) -> str:
        if self.translator in ("claude", "mock"):
            return self.translator
        return "claude" if self.anthropic_api_key else "mock"

    @property
    def public_origin(self) -> str | None:
        return f"https://{self.site_domain}" if self.site_domain else None


def insecure_defaults(s: Settings) -> list[str]:
    """Settings still at a value published in this repository (or too weak to sign tokens with)."""
    problems = []
    if s.jwt_secret == DEV_JWT_SECRET or len(s.jwt_secret) < 32:
        problems.append("JWT_SECRET (default or shorter than 32 characters)")
    if s.s3_secret_key == "lexmatches-secret":
        problems.append("S3_SECRET_KEY (default)")
    if ":lexmatches@" in s.database_url:
        problems.append("POSTGRES_PASSWORD (default)")
    return problems


settings = Settings()
