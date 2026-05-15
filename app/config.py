from pydantic_settings import BaseSettings
from pydantic import model_validator
from typing import List


class Settings(BaseSettings):
    app_secret_key: str = "dev-secret-change-me"
    database_url: str = "sqlite:///./expenses.db"
    debug: bool = True
    app_name: str = "Expenses"
    allow_registration: bool = False

    # Supported currencies — single source of truth used across all routes
    currencies: List[str] = [
        "EUR", "USD", "GBP", "CHF", "JPY", "AUD", "CAD", "SEK", "NOK", "DKK"
    ]

    # AADE (Greek tax portal) receipt lookup
    aade_host: str = "www1.aade.gr"
    aade_path_prefix: str = "/tameiakes/myweb/q1.php"
    aade_timeout_seconds: float = 8.0

    # Invitation links
    invite_expiry_days: int = 7

    # Bills dashboard — how many days ahead to show upcoming bills
    upcoming_bills_days: int = 60

    # Web Push (VAPID) — set via environment variables in production
    # Generate with: vapid --gen  (after installing pywebpush)
    vapid_private_key: str = ""
    vapid_public_key: str  = ""
    vapid_claims_email: str = "admin@localhost"

    @model_validator(mode="after")
    def _guard_production_defaults(self) -> "Settings":
        if not self.debug and self.app_secret_key == "dev-secret-change-me":
            raise RuntimeError(
                "APP_SECRET_KEY must be changed from the default value before running in production. "
                "Set the APP_SECRET_KEY environment variable."
            )
        return self

    class Config:
        env_file = ".env"


settings = Settings()
