"""entrypoint.sh / scripts/backup.sh run pg_dump with a libpq-compatible URL."""
import os
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
URL = "postgresql+psycopg2://u:p@db:5432/expenses"


def _stub(bin_dir: Path, name: str, body: str) -> None:
    f = bin_dir / name
    f.write_text("#!/bin/sh\n" + body + "\n")
    f.chmod(f.stat().st_mode | stat.S_IEXEC)


@pytest.fixture()
def stubs(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "pg_dump.args"
    # pg_dump (libpq) rejects "postgresql+psycopg2://" URLs; so does the stub.
    _stub(bin_dir, "pg_dump", f'echo "$@" > "{log}"\n'
                              'case "$1" in *+*) echo "invalid URI" >&2; exit 1;; esac\n'
                              'echo "-- dump"')
    _stub(bin_dir, "alembic", "exit 0")
    _stub(bin_dir, "uvicorn", "exit 0")
    backups = tmp_path / "backups"
    backups.mkdir()
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}",
           "DATABASE_URL": URL, "BACKUP_DIR": str(backups),
           "UPLOADS_PARENT": str(tmp_path / "nouploads")}
    return env, log, backups


def test_backup_script_strips_sqlalchemy_driver(stubs):
    env, log, backups = stubs
    r = subprocess.run(["sh", str(ROOT / "scripts/backup.sh")], env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert log.read_text().strip() == "postgresql://u:p@db:5432/expenses"
    assert list(backups.glob("db-*.sql.gz"))


def test_entrypoint_premigrate_dump_strips_sqlalchemy_driver(stubs):
    env, log, backups = stubs
    r = subprocess.run(["sh", str(ROOT / "entrypoint.sh")], env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert log.read_text().strip() == "postgresql://u:p@db:5432/expenses"
    assert list(backups.glob("pre-migrate-*.sql.gz"))
