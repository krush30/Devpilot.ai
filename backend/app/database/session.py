"""Engine and sessions. SQLite by default (zero setup); set DB_URL to a PostgreSQL URL for Postgres."""
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, delete, event, update
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.tables import Base, ProposalRow, Run

DEFAULT_URL = "sqlite:///./devpilot.db"
RETENTION_DAYS = 90

_lock = threading.RLock()
_engine = None
_Session = None
_ready = False


def _make_engine(url: str):
    if not url.startswith("sqlite"):
        return create_engine(url, pool_pre_ping=True)
    engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _pragmas(conn, _):  # WAL + busy timeout: the API serves requests from several threads
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()

    return engine


def configure(url: str | None = None) -> None:
    global _engine, _Session, _ready
    with _lock:
        if _engine is not None:
            _engine.dispose()
        _engine = _make_engine(url or getattr(settings, "db_url", "") or DEFAULT_URL)
        _Session = sessionmaker(_engine, expire_on_commit=False)
        _ready = False


def dispose() -> None:
    global _engine, _Session, _ready
    with _lock:
        if _engine is not None:
            _engine.dispose()
        _engine, _Session, _ready = None, None, False


def _ensure() -> None:
    global _ready
    with _lock:
        if _engine is None:
            configure()
        if _ready:
            return
        Base.metadata.create_all(_engine)
        cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
        with _Session() as s:
            # A run still "running" at startup belonged to a process that died.
            s.execute(update(Run).where(Run.status == "running").values(status="interrupted"))
            s.execute(delete(Run).where(Run.created_at < cutoff))
            s.execute(delete(ProposalRow).where(ProposalRow.created_at < cutoff))
            s.commit()
        _ready = True


@contextmanager
def session():
    _ensure()
    s = _Session()
    try:
        yield s
        s.commit()
    except BaseException:
        s.rollback()
        raise
    finally:
        s.close()