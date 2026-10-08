"""Pocket ID (OIDC) client. Authlib does the protocol: discovery, PKCE, state,
nonce and ID-token verification against the provider's JWKS."""

from functools import lru_cache

from authlib.integrations.starlette_client import OAuth

from app.core.config import settings


@lru_cache(maxsize=1)
def _registry() -> OAuth:
    oauth = OAuth()
    oauth.register(
        name="pocketid",
        server_metadata_url=f"{settings.oidc_issuer.rstrip('/')}/.well-known/openid-configuration",
        client_id=settings.oidc_client_id,
        client_secret=settings.oidc_client_secret,
        client_kwargs={"scope": "openid email profile", "code_challenge_method": "S256"},
    )
    return oauth


def oidc_client():
    return _registry().pocketid
