from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine, select

from upvote_monitor.db.models import AppSettings, RefreshRun, ReviewItem
from upvote_monitor.services.preview_cache import (
    cleanup_stale_preview_cache,
    ensure_preview_cache_dir,
)
from upvote_monitor.services.source_settings import ensure_default_source_settings

DATA_DIR = Path("/data")
DATABASE_URL = f"sqlite:///{(DATA_DIR / 'upvote_monitor.db').as_posix()}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


def _has_existing_activity(session: Session) -> bool:
    has_items = session.exec(select(ReviewItem.id).limit(1)).first() is not None
    has_refresh_runs = session.exec(select(RefreshRun.id).limit(1)).first() is not None
    return has_items or has_refresh_runs


def _ensure_download_dir(download_base_dir: str) -> None:
    Path(download_base_dir).mkdir(parents=True, exist_ok=True)


def init_db() -> bool:
    database_path = DATA_DIR / "upvote_monitor.db"
    created_database = not database_path.exists()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ensure_preview_cache_dir()
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        settings = session.get(AppSettings, 1)
        created_settings = settings is None
        if settings is None:
            settings = AppSettings(id=1)
            session.add(settings)
            session.commit()
            session.refresh(settings)

        ensure_default_source_settings(session)
        _ensure_download_dir(settings.download_base_dir)
        cleanup_stale_preview_cache(session)

        return created_database or (
            created_settings and not _has_existing_activity(session)
        )


def get_session() -> Session:
    return Session(engine)
