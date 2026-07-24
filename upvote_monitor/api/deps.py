from collections.abc import Generator

from sqlmodel import Session

from upvote_monitor.db.engine import engine


def get_db_session() -> Generator[Session]:
    with Session(engine) as session:
        yield session
