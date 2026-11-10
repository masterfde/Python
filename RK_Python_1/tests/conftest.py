import pytest

from app import config
from app.database import init_db


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Give every test its own empty database file."""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    init_db()
