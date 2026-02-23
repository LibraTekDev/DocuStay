"""Application configuration from environment."""
from pathlib import Path

from dotenv import load_dotenv
from pydantic import field_validator
from pydantic_settings import BaseSettings
from functools import lru_cache

# Load .env from project root (parent of app/) so env vars are available everywhere
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=_env_path)


class Settings(BaseSettings):
    app_name: str = "DocuStay Demo"
    app_env: str = "development"
    debug: bool = True
    secret_key: str = "change-me"

    database_url: str = "postgresql://postgres:postgres@localhost:5432/docustay_demo"

    jwt_secret_key: str = "jwt-secret-change-me"
    jwt_algorithm: str = "HS256"

    @field_validator("jwt_secret_key")
    @classmethod
    def strip_jwt_secret(cls, v: str) -> str:
        return (v or "").strip()

    jwt_access_token_expire_minutes: int = 60
    # Pending-owner signup flow (email verified → identity → POA) can take a while; use longer expiry
    jwt_pending_owner_expire_minutes: int = 60 * 24  # 24 hours

    sendgrid_api_key: str = ""
    sendgrid_from_email: str = "noreply@docustay.demo"
    sendgrid_from_name: str = "DocuStay"

    mailgun_api_key: str = ""
    mailgun_domain: str = ""
    mailgun_base_url: str = "https://api.mailgun.net"
    mailgun_from_email: str = "noreply@docustay.demo"
    mailgun_from_name: str = "DocuStay"

    @field_validator("mailgun_api_key", "mailgun_domain", "mailgun_base_url", "mailgun_from_email", mode="before")
    @classmethod
    def strip_mailgun(cls, v: str) -> str:
        return (v or "").strip()

    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_phone_number: str = ""

    dropbox_sign_api_key: str = ""
    dropbox_sign_client_id: str = ""

    stripe_secret_key: str = ""
    stripe_publishable_key: str = ""
    stripe_identity_flow_id: str = ""
    stripe_identity_return_url: str = ""

    notification_days_before_limit: int = 5
    notification_cron_enabled: bool = True

    class Config:
        env_file = str(_env_path)
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
