from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── LLM — Anthropic direct or OpenRouter proxy ───────────────────
    anthropic_api_key: str = "dummy-api-key"
    model: str = "claude-sonnet-4-6"
    max_tokens: int = 1024
    # When set, all LLM calls route through OpenRouter instead of Anthropic directly.
    # Model name must use OpenRouter format, e.g. "anthropic/claude-sonnet-4-5"
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "anthropic/claude-sonnet-4-5"

    # ── Database ─────────────────────────────────────────────────────
    database_url: str = "sqlite:///./tabor_agent.db"

    # ── Admin ────────────────────────────────────────────────────────
    admin_password: str
    admin_panel_path: str = "/ts-mgmt"   # Secret URL — change via ADMIN_PANEL_PATH env var

    # ── Clinic user JWT auth ─────────────────────────────────────────
    # Signing key for clinic-user JWT tokens. Falls back to admin_password
    # in auth.py if left blank, so no new env var is strictly required.
    jwt_secret_key: str = ""

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

    # ── Transactional email via HTTP API (works on hosts that block SMTP, e.g. Render free) ──
    # If SENDGRID_API_KEY is set, email is sent over HTTPS via SendGrid instead of SMTP.
    sendgrid_api_key: str = ""
    email_from: str = ""                 # Verified sender address; falls back to smtp_user/notify_email

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
    # Run the in-app APScheduler. When scaling the web service to multiple workers,
    # set ENABLE_SCHEDULER=false on the web dynos so jobs don't fire once per worker;
    # run the schedule from ONE place (a dedicated worker or the GitHub Actions cron).
    enable_scheduler: bool = True

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
