"""docker-compose.yml keeps existing receipts and passes every documented variable."""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
SERVICES = COMPOSE["services"]


def _env_names(service: dict) -> set[str]:
    env = service.get("environment", [])
    if isinstance(env, dict):
        return set(env)
    return {e.split("=", 1)[0] for e in env}


def test_uploads_stay_on_the_original_bind_mount():
    """Receipts already live in ./uploads on the host: a new named volume would
    hide them (every receipt 404s) and back up an empty directory."""
    assert "./uploads:/app/uploads" in SERVICES["app"]["volumes"]
    assert "./uploads:/app/uploads:ro" in SERVICES["backup"]["volumes"]
    assert "uploads_data" not in (COMPOSE.get("volumes") or {})
    for svc in SERVICES.values():
        assert not any("uploads_data" in v for v in svc.get("volumes", []))


def test_backup_runs_from_the_app_image_with_a_freshness_healthcheck():
    backup = SERVICES["backup"]
    # Same pg_dump as the app (v17, dumps 16/17 servers); no relative
    # ./scripts bind that may be missing on Coolify.
    assert backup.get("build") == "."
    assert "image" not in backup
    assert not any(v.startswith("./scripts") for v in backup["volumes"])
    assert "backups:/backups" in backup["volumes"]
    cmd = " ".join(backup["entrypoint"] if "entrypoint" in backup else backup["command"])
    assert "/app/scripts/backup.sh" in cmd
    assert "BACKUP FAILED" in cmd
    assert str(backup.get("user")) == "10001"
    test = " ".join(backup["healthcheck"]["test"])
    assert "db-*.sql.gz" in test and "-mmin" in test


def test_every_documented_variable_reaches_the_app():
    doc = (ROOT / "docs/DEPLOY-COOLIFY.md").read_text()
    table = doc.split("## 1. Environment variables", 1)[1].split("## 2.", 1)[0]
    documented = set(re.findall(r"^\| `([A-Z_]+)`", table, re.M))
    documented |= set(
        re.findall(
            r"`([A-Z][A-Z_]+)`",
            "\n".join(line for line in table.splitlines() if line.startswith("| `VAPID")),
        )
    )
    # Only meaningful to the db / backup services.
    documented -= {"POSTGRES_PASSWORD", "BACKUP_KEEP_DAYS"}
    missing = documented - _env_names(SERVICES["app"])
    assert not missing, f"documented but not passed to the app container: {sorted(missing)}"
    for name in (
        "ALLOW_REGISTRATION",
        "CORS_ALLOWED_ORIGINS",
        "POSOKANEI_BASE_URL",
        "JWT_SECRET_KEY",
        "BACKUP_BEFORE_MIGRATE",
    ):
        assert name in documented, f"{name} missing from the DEPLOY-COOLIFY.md table"


def test_database_url_is_hardcoded_to_the_bundled_db():
    """A stray DATABASE_URL (.env.example's localhost, a sqlite URL) must not
    silently replace the bundled db for the app or backup service."""
    for name in ("app", "backup"):
        env = SERVICES[name]["environment"]
        url = next(e for e in env if e.startswith("DATABASE_URL="))
        assert "${DATABASE_URL" not in url
        assert re.search(r"@db:5432/", url), url
