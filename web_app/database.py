from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker


ALEMBIC_CONFIG = Path(__file__).resolve().parent / "alembic.ini"


def migrate_database(database_path: Path) -> None:
    """Bring the persistent database to the packaged Alembic revision."""
    database_path.parent.mkdir(parents=True, exist_ok=True)
    config = Config(str(ALEMBIC_CONFIG))
    config.attributes["database_path"] = database_path.resolve()
    config.attributes["configure_logger"] = False
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.resolve().as_posix()}")
    command.upgrade(config, "head")


def create_database(database_path: Path) -> tuple[Engine, sessionmaker[Session]]:
    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 30},
        future=True,
    )

    @event.listens_for(engine, "connect")
    def _configure_sqlite(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False, future=True)
    return engine, factory
