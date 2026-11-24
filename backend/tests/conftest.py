import pytest

from app.database import session as db


@pytest.fixture(autouse=True)
def temp_db(tmp_path):
    """Every test gets its own throwaway database, so tests never touch devpilot.db."""
    db.configure(f"sqlite:///{tmp_path / 'test.db'}")
    yield
    db.dispose()  # release the file (matters on Windows)