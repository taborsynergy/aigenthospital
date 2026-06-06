from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── Anthropic ────────────────────────────────────────────────────
    anthropic_api_key: str = "dummy-api-key"
    model: str = "claude-sonnet-4-6"
    max_tokens: int = 1024

    # ── Database ─────────────────────────────────────────────────────
    database_url: str = "sqlite:///./tabor_agent.db"

    # ── Admin ────────────────────────────────────────────────────────
    admin_password: str
    admin_panel_path: str = "/ts-mgmt"   # Secret URL — change via ADMIN_PANEL_PATH env var

    # ── PayPal ───────────────────────────────────────────────────────
    paypal_me_url: str = "https://www.paypal.com/paypalme/write2dinakar"

    # ── Twilio ───────────────────────────────────────────────────────
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_default_number: str = ""    # Fallback sending number

    # ── Email (SMTP) — for quote request notifications ───────────────
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""                  # Your sending Gmail / email address
    smtp_pass: str = ""                  # App password (not your login password)
    notify_email: str = "admin@tabor.taborsynergy.com"   # Where quote emails are delivered

    # ── Mock PMS defaults (used by pms.py when real EHR is not connected) ──
    providers: str = "Dr. Provider"
    clinic_name: str = "Tabor Synergy"
    address: str = ""
    cancellation_policy: str = "Please cancel at least 24 hours in advance to avoid a cancellation fee."

    # ── Server ───────────────────────────────────────────────────────
    allowed_origins: str = "https://aifrontdesk.taborsynergy.com,https://taborsynergy-agent.onrender.com"
    base_url: str = "https://aifrontdesk.taborsynergy.com"
    debug_mode: bool = False   # Set DEBUG_MODE=true locally to enable /docs and /openapi.json
    sentry_dsn: str = ""       # Set SENTRY_DSN in Render env vars to enable error tracking

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
