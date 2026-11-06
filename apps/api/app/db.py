from collections.abc import Iterator

from fastapi import HTTPException
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, create_engine

from app.settings import get_settings

# SQLite database location (override with DCIM_DATABASE_URL)
DATABASE_URL = get_settings().database_url


def make_engine(url: str):
    is_sqlite = url.startswith("sqlite")
    engine = create_engine(url, connect_args={"check_same_thread": False} if is_sqlite else {})

    if is_sqlite:
        enable_sqlite_foreign_keys(engine)
    return engine


# SQLite only enforces foreign keys when asked to (per connection)
def enable_sqlite_foreign_keys(engine) -> None:
    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


engine = make_engine(DATABASE_URL)


# FastAPI dependency: one session per request
def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session


# Helper: commit and turn constraint violations into a 409
# Named DB constraints that get their own 409 code when a race slips past the Python check
# (SQLite messages list the columns, Postgres messages carry the constraint name)
NAMED_CONFLICTS = (
    (("uq_racks_hall_id_pos_x_pos_y", "racks.hall_id, racks.pos_x, racks.pos_y"),
     {"code": "floor_position_taken", "message": "That floor position in this hall is already taken by another cabinet"}),
    (("pk_device_ru_slots", "device_ru_slots.rack_id"),
     {"code": "ru_slot_taken", "message": "Another device took these rack units at the same time; reload and retry"}),
)


def conflict_detail(exc: IntegrityError, message):
    text = str(getattr(exc, "orig", exc))
    for needles, detail in NAMED_CONFLICTS:
        if any(n in text for n in needles):
            return dict(detail)
    return message


def commit_or_409(session: Session, message: str = "Conflicts with an existing record") -> None:
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=conflict_detail(exc, message))


# Helper: flush (to get ids) and turn constraint violations into a 409
def flush_or_409(session: Session, message: str = "Conflicts with an existing record") -> None:
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=conflict_detail(exc, message))
