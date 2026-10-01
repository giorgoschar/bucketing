"""The CI Postgres job only means something if tests really run on Postgres."""
import os

import pytest


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="SQLite run")
def test_engine_uses_test_database_url(engine):
    assert engine.dialect.name == "postgresql"


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="SQLite run")
def test_migration_db_url_uses_test_database_url(tmp_path):
    from tests.test_migrations import _db_url

    assert _db_url(tmp_path, "x").startswith("postgresql")
