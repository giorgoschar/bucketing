from pydantic_settings import BaseSettings
from pydantic import model_validator
from typing import List


class Settings(BaseSettings):
    app_secret_key: str = "dev-secret-change-me"
    database_url: str = "sqlite:///./expenses.db"
    debug: bool = True
    app_name: str = "Expenses"
    allow_registration: bool = False

    # JWT — API (mobile / external clients)
    # Defaults to app_secret_key; set JWT_SECRET_KEY in production for isolation.
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60
    jwt_refresh_token_expire_days: int = 30

    # CORS — space-separated list of allowed origins, e.g. "https://myapp.com capacitor://localhost"
    # Empty = no cross-origin requests allowed (safe default).
    cors_allowed_origins: str = ""

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
        if not self.debug:
            if not self.app_secret_key or self.app_secret_key == "dev-secret-change-me":
                raise RuntimeError(
                    "APP_SECRET_KEY must be set to a cryptographically random value in production. "
                    "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
                )
            if len(self.app_secret_key) < 32:
                raise RuntimeError(
                    "APP_SECRET_KEY is too short (minimum 32 characters). "
                    "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
                )
        return self

    @property
    def effective_jwt_secret(self) -> str:
        """JWT secret — uses JWT_SECRET_KEY if set, otherwise falls back to APP_SECRET_KEY."""
        return self.jwt_secret_key or self.app_secret_key

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse space-separated CORS origins into a list."""
        return [o.strip() for o in self.cors_allowed_origins.split() if o.strip()]

    class Config:
        env_file = ".env"


settings = Settings()
