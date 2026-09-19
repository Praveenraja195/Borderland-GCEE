from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base — import point for Alembic autogen.

    NOTE: this schema is triggers/functions/constraints-heavy and was
    authored as raw SQL first (see sql/round1_schema.sql). The ORM models
    under app/models mirror that SQL closely so autogenerate diffs stay
    sane, but the actual DDL for triggers/functions/views is applied via
    `op.execute(...)` in the initial Alembic revision, not by the ORM.
    """


# Import all models here so Base.metadata is fully populated for Alembic
# autogenerate and for `Base.metadata.create_all` in tests.
from app.models import (  # noqa: E402,F401
    admin,
    game,
    jack_heart,
    king_diamond,
    mindmaze,
    results,
    round,
    selection,
    team,
    tiebreak,
)
