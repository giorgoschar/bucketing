import ipaddress
import re
from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_HOSTNAME = re.compile(r"^[A-Za-z0-9.-]+$")


@lru_cache(maxsize=8)
def issuer_origin(issuer: str | None) -> str | None:
    """The scheme://host[:port] origin of an OIDC issuer URL, or None if it isn't a clean
    http(s) URL. Safe to put in a CSP header: no userinfo, path, query or stray characters."""
    if not issuer or any(c.isspace() or c in ";,'\"" for c in issuer):
        return None
    try:
        parts = urlsplit(issuer)
        port = parts.port
    except ValueError:
        return None
    host = parts.hostname
    if parts.scheme not in ("http", "https") or not host:
        return None
    if ":" in host:
        try:
            host = f"[{ipaddress.IPv6Address(host).compressed}]"
        except ValueError:
            return None
    elif not _HOSTNAME.match(host):
        return None
    return f"{parts.scheme}://{host}" + (f":{port}" if port is not None else "")


class Settings(BaseSettings):
    # Required: no default, so the app refuses to start without APP_SECRET_KEY.
    app_secret_key: str
    # Fernet key for encrypting TOTP secrets at rest. When unset it is derived
    # from app_secret_key (and rotating APP_SECRET_KEY then breaks stored secrets).
    field_encryption_key: str | None = None
    database_url: str = "sqlite:///./expenses.db"
    debug: bool = False
    # App log level (root logger → stderr → `docker logs` / Coolify).
    # uvicorn has its own level; this one covers everything the app logs,
    # including the ingest diagnostics in app/services/ingest.py.
    log_level: str = "INFO"
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
    currencies: list[str] = ["EUR", "USD", "GBP", "CHF", "JPY", "AUD", "CAD", "SEK", "NOK", "DKK"]

    # AADE (Greek tax portal) receipt lookup
    aade_host: str = "www1.aade.gr"
    aade_path_prefix: str = "/tameiakes/myweb/q1.php"
    aade_timeout_seconds: float = 8.0
    # AADE's myDATA receipt page, linked from newer receipts' QR codes and
    # from e-invoicing providers' receipt pages.
    mydata_qr_host: str = "mydatapi.aade.gr"
    mydata_qr_path: str = "/myDATA/TimologioQR/QRInfo"
    # Cap on a provider receipt page fetched to find its AADE link.
    receipt_page_max_bytes: int = 1_000_000

    # Session lifetime, enforced server-side by the signed timestamp in the
    # cookie (not only by the browser's cookie expiry).
    session_max_age_seconds: int = 60 * 60 * 24 * 30
    # Hard cap on a rolling session, counted from the original sign-in ("iat").
    session_absolute_max_seconds: int = 60 * 60 * 24 * 90

    # Invitation links
    invite_expiry_days: int = 7

    # Bills dashboard — how many days ahead to show upcoming bills
    upcoming_bills_days: int = 60

    # Calendar timezone for scheduled work. Bill due dates are plain calendar
    # dates entered in the household's local time, so "is this due today?" must
    # be answered in that timezone — using UTC meant a bill due today was not
    # seen as due until UTC caught up, and reminders could land a day out.
    # e.g. "Europe/Athens". Defaults to UTC.
    app_timezone: str = "UTC"

    # Background scheduler (auto-pay + bill reminders).
    # Each uvicorn worker runs its own scheduler, so with `--workers N` the job
    # fires N times. The job is idempotent, but set this to false on all but one
    # worker to avoid the redundant work.
    enable_scheduler: bool = True

    # Trust X-Forwarded-For for client IPs. Only enable when the app sits behind
    # a reverse proxy that overwrites the header — otherwise clients can spoof
    # their IP in security logs and in rate-limit buckets.
    trust_proxy_headers: bool = False

    # Rate-limit counter storage. Empty = per-process memory, which means limits
    # are enforced per uvicorn worker. Set to e.g. "redis://localhost:6379" to
    # share counters across workers.
    rate_limit_storage_uri: str = ""

    # Public base URL used in invite links, e.g. "https://expenses.example.com".
    # Required in production: building links from the request Host header lets a
    # forged Host poison the link an owner shares.
    app_base_url: str | None = None

    # New app (/app). Off until cutover; when off, /app/* is a 404.
    new_app_enabled: bool = False
    # Pocket ID (OIDC). All three are needed for passkey sign-in.
    oidc_issuer: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: str | None = None

    # PosoKanei (unofficial Greek supermarket price API, see docs/POSOKANEI.md).
    # Set POSOKANEI_ENABLED=false to stop all outbound price lookups; stock
    # pages keep working and show "prices unavailable".
    posokanei_enabled: bool = True
    posokanei_base_url: str = "https://api.posokanei.gov.gr"

    # Web Push (VAPID) — set via environment variables in production
    # Generate with: vapid --gen  (after installing pywebpush)
    vapid_private_key: str = ""
    vapid_public_key: str = ""
    vapid_claims_email: str = "admin@localhost"

    @model_validator(mode="after")
    def _guard_production_defaults(self) -> "Settings":
        if self.field_encryption_key:
            # A malformed key would otherwise only surface inside verify_totp,
            # turning every 2FA login into a 500. Fail at startup instead.
            from cryptography.fernet import Fernet

            try:
                Fernet(self.field_encryption_key.encode())
            except (ValueError, TypeError) as exc:
                raise RuntimeError(
                    "FIELD_ENCRYPTION_KEY is not a valid Fernet key (32 url-safe base64-encoded "
                    'bytes). Generate one with: python -c "from cryptography.fernet import '
                    'Fernet; print(Fernet.generate_key().decode())"'
                ) from exc
        if not self.debug:
            if "change-me" in (self.app_secret_key or "").lower():
                raise RuntimeError(
                    "APP_SECRET_KEY is still the .env.example placeholder. "
                    'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
                )
            if not self.app_secret_key:
                raise RuntimeError(
                    "APP_SECRET_KEY must be set to a cryptographically random value in production. "
                    'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
                )
            if len(self.app_secret_key) < 32:
                raise RuntimeError(
                    "APP_SECRET_KEY is too short (minimum 32 characters). "
                    'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
                )
            if not self.app_base_url:
                raise RuntimeError(
                    "APP_BASE_URL must be set in production (e.g. https://expenses.example.com); "
                    "invite links are built from it, never from the Host header."
                )
            if self.new_app_enabled and not self.oidc_enabled:
                raise RuntimeError(
                    "NEW_APP_ENABLED needs OIDC_ISSUER, OIDC_CLIENT_ID and OIDC_CLIENT_SECRET."
                )
            if self.new_app_enabled and not issuer_origin(self.oidc_issuer):
                raise RuntimeError(
                    "OIDC_ISSUER must be a plain http(s) URL such as https://id.example.com."
                )
        return self

    @property
    def effective_jwt_secret(self) -> str:
        """JWT secret — uses JWT_SECRET_KEY if set, otherwise falls back to APP_SECRET_KEY."""
        return self.jwt_secret_key or self.app_secret_key

    @property
    def oidc_enabled(self) -> bool:
        return bool(self.oidc_issuer and self.oidc_client_id and self.oidc_client_secret)

    @property
    def oidc_issuer_origin(self) -> str | None:
        """Validated origin of OIDC_ISSUER (see issuer_origin); None when unusable."""
        return issuer_origin(self.oidc_issuer)

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse space-separated CORS origins into a list."""
        return [o.strip() for o in self.cors_allowed_origins.split() if o.strip()]

    # ConfigDict rather than the class-based Config, which Pydantic deprecated
    # in v2 and removes in v3.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
