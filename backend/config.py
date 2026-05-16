from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Anthropic ────────────────────────────────────────────────────
    anthropic_api_key: str
    model: str = "claude-sonnet-4-6"
    max_tokens: int = 1024

    # ── Database ─────────────────────────────────────────────────────
    database_url: str = "sqlite:///./tabor_agent.db"

    # ── Admin ────────────────────────────────────────────────────────
    admin_password: str = "admin123"

    # ── Stripe ───────────────────────────────────────────────────────
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_id: str = ""          # Monthly subscription price ID

    # ── Twilio ───────────────────────────────────────────────────────
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_default_number: str = ""    # Fallback sending number

    # ── Server ───────────────────────────────────────────────────────
    allowed_origins: str = "*"
    base_url: str = "https://aifrontdesk.taborsynergy.com"   # Used for Stripe redirect URLs

    class Config:
        env_file = ".env"
        extra = "ignore"   # tolerate stale keys from previous config versions


settings = Settings()
