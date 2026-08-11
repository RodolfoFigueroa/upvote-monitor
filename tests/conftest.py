from collections.abc import Iterator

import pytest
from sqlalchemy.engine import Engine
from sqlmodel import SQLModel

from upvote_monitor.db.engine import create_sqlite_engine, run_migrations


def build_test_engine(*, migrated: bool) -> Engine:
    """Build all test databases through the production SQLite configuration."""
    db_engine = create_sqlite_engine("sqlite://", in_memory=True)
    if migrated:
        run_migrations(db_engine)
    else:
        SQLModel.metadata.create_all(db_engine)
    return db_engine


@pytest.fixture
def engine() -> Iterator[Engine]:
    db_engine = build_test_engine(migrated=False)
    yield db_engine
    db_engine.dispose()


@pytest.fixture
def migrated_engine() -> Iterator[Engine]:
    db_engine = build_test_engine(migrated=True)
    yield db_engine
    db_engine.dispose()
