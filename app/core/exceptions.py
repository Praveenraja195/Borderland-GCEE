"""
Central place for turning low-level failures (DB constraint violations,
PL/pgSQL RAISE EXCEPTIONs) into clean, predictable HTTP responses.

The schema (round1_schema.sql) intentionally enforces the rules that must
never be bypassed at the DB layer (UNIQUE constraints, triggers that raise
exceptions). The API's job here is purely translation: catch the low-level
error, map it to a sensible HTTP status + message, never leak raw SQL/driver
text to the client.
"""

from __future__ import annotations

import re

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, IntegrityError


class AppError(Exception):
    """Base class for explicit, service-layer-raised application errors."""

    status_code = status.HTTP_400_BAD_REQUEST

    def __init__(self, detail: str, status_code: int | None = None):
        self.detail = detail
        if status_code is not None:
            self.status_code = status_code
        super().__init__(detail)


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT


class ForbiddenError(AppError):
    status_code = status.HTTP_403_FORBIDDEN


class UnauthorizedError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED


# ---------------------------------------------------------------------------
# Constraint-name -> friendly-message table.
# Extend this as new UNIQUE / CHECK constraints are added to the schema.
# ---------------------------------------------------------------------------
_CONSTRAINT_MESSAGES: dict[str, tuple[int, str]] = {
    "round1_selections_round_id_team_id_key": (
        status.HTTP_409_CONFLICT,
        "This team has already made a selection for this round.",
    ),
    "uq_suit_number_per_round": (
        status.HTTP_409_CONFLICT,
        "Another team in your group has already chosen that number.",
    ),
    "mindmaze_results_round_id_team_id_key": (
        status.HTTP_409_CONFLICT,
        "This team has already submitted for this MindMaze round.",
    ),
    "king_diamond_submissions_round_id_team_id_key": (
        status.HTTP_409_CONFLICT,
        "This team has already submitted for this King of Diamonds round.",
    ),
    "jack_heart_answers_round_id_team_id_key": (
        status.HTTP_409_CONFLICT,
        "This team has already submitted for this Jack of Hearts round.",
    ),
    "jack_heart_assignments_round_id_symbol_id_key": (
        status.HTTP_409_CONFLICT,
        "Symbol assignment conflict for this round.",
    ),
    "teams_team_code_key": (status.HTTP_409_CONFLICT, "Team code already in use."),
    "teams_team_name_key": (status.HTTP_409_CONFLICT, "Team name already in use."),
    "trg_team_cap": (
        status.HTTP_409_CONFLICT,
        "Maximum of 40 teams already registered.",
    ),
}

# Explicit RAISE EXCEPTION messages from PL/pgSQL functions/triggers.
_MESSAGE_SUBSTRING_MAP: list[tuple[str, int, str]] = [
    ("No room configured for number", status.HTTP_400_BAD_REQUEST, "Invalid room/number selection."),
    ("No symbol assignment found", status.HTTP_400_BAD_REQUEST, "No hidden symbol assigned for this team/round yet."),
    ("is locked and cannot be modified", status.HTTP_409_CONFLICT, "This selection is locked and cannot be changed."),
    ("Maximum of 40 teams", status.HTTP_409_CONFLICT, "Maximum of 40 teams already registered."),
]


def _extract_constraint_name(exc: IntegrityError) -> str | None:
    orig = getattr(exc, "orig", None)
    text = str(orig) if orig else str(exc)
    match = re.search(r'"([a-zA-Z0-9_]+)"', text)
    return match.group(1) if match else None


def _map_integrity_error(exc: IntegrityError) -> tuple[int, str]:
    constraint = _extract_constraint_name(exc)
    if constraint and constraint in _CONSTRAINT_MESSAGES:
        return _CONSTRAINT_MESSAGES[constraint]

    text = str(getattr(exc, "orig", exc))
    for needle, code, message in _MESSAGE_SUBSTRING_MAP:
        if needle in text:
            return code, message

    if "unique" in text.lower():
        return status.HTTP_409_CONFLICT, "This action conflicts with an existing record."
    return status.HTTP_400_BAD_REQUEST, "The request violates a database constraint."


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(IntegrityError)
    async def integrity_error_handler(request: Request, exc: IntegrityError):
        status_code, message = _map_integrity_error(exc)
        return JSONResponse(status_code=status_code, content={"detail": message})

    @app.exception_handler(DBAPIError)
    async def dbapi_error_handler(request: Request, exc: DBAPIError):
        text = str(getattr(exc, "orig", exc))
        for needle, code, message in _MESSAGE_SUBSTRING_MAP:
            if needle in text:
                return JSONResponse(status_code=code, content={"detail": message})
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": "The database rejected this request."},
        )
