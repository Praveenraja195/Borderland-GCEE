"""
Spreadsheet in, spreadsheet out.

  * §2.1b  Bulk team registration — upload the event's registration sheet,
           review what it would create, then commit it.
  * §2.7b  Round 2 qualifier export — the winners list as a shareable .xlsx.

The import is deliberately two calls. `/import/preview` parses and validates
without writing anything; `/import` takes the reviewed rows back and creates
them in one transaction. Doing it in a single upload-and-create call would
mean discovering a mis-detected phone column only after 40 accounts already
exist with the wrong passwords.

All of these are SUPER_ADMIN-only: they create login credentials and export
every team's contact details.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_role
from app.core.exceptions import AppError
from app.db.session import get_db
from app.models.admin import AdminRole
from app.schemas.team import (
    ImportCommitIn,
    ImportCommitOut,
    ImportPreviewOut,
    ImportRowOut,
    ImportedTeamOut,
)
from app.services import export_service, team_import_service

router = APIRouter(prefix="/admin", tags=["admin-data"])

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _xlsx_response(content: bytes, filename: str) -> Response:
    return Response(
        content=content,
        media_type=XLSX_MEDIA_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            # The browser fetches this with XHR to attach the auth header, so
            # the filename has to be readable from JS to name the download.
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


async def _read_upload(file: UploadFile) -> bytes:
    data = await file.read()
    if not data:
        raise AppError("The uploaded file is empty.")
    if len(data) > team_import_service.MAX_UPLOAD_BYTES:
        raise AppError(
            f"File is larger than {team_import_service.MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
        )
    return data


# ---------------------------------------------------------------------------
# §2.1b Bulk team registration
# ---------------------------------------------------------------------------


@router.get("/teams/import/template", response_class=Response)
async def download_import_template(
    _admin=Depends(require_role(AdminRole.SUPER_ADMIN)),
):
    """A blank registration sheet in the exact shape the importer expects."""
    return _xlsx_response(export_service.build_import_template(), "team-import-template.xlsx")


@router.post("/teams/import/preview", response_model=ImportPreviewOut)
async def preview_team_import(
    file: UploadFile = File(..., description="Registration sheet (.xlsx or .csv)"),
    team_name_column: str | None = Form(None),
    leader_name_column: str | None = Form(None),
    leader_phone_column: str | None = Form(None),
    leader_email_column: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.SUPER_ADMIN)),
):
    """Parse the sheet and report exactly what an import would create.

    Writes nothing. Columns are matched by header name; the four optional
    `*_column` fields override that per field, accepting a header name, a
    column letter ("D") or a 0-based index.
    """
    data = await _read_upload(file)
    preview = await team_import_service.parse_upload(
        db,
        data=data,
        filename=file.filename or "",
        overrides={
            "team_name": team_name_column,
            "leader_name": leader_name_column,
            "leader_phone": leader_phone_column,
            "leader_email": leader_email_column,
        },
    )
    rows = [ImportRowOut(**vars(row)) for row in preview.rows]
    importable = sum(1 for row in preview.rows if row.is_importable)
    return ImportPreviewOut(
        headers=preview.headers,
        column_map=preview.column_map,
        unmapped_required=preview.unmapped_required,
        header_row_number=preview.header_row_number,
        sheet_name=preview.sheet_name,
        existing_team_count=preview.existing_team_count,
        capacity_remaining=preview.capacity_remaining,
        rows=rows,
        importable_count=importable,
        skipped_count=len(rows) - importable,
    )


@router.post("/teams/import", response_model=ImportCommitOut, status_code=status.HTTP_201_CREATED)
async def commit_team_import(
    payload: ImportCommitIn,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.SUPER_ADMIN)),
):
    """Create the reviewed teams. All-or-nothing.

    Returns each team's cleartext password once, so the console can hand the
    organiser a credentials sheet — it is unreadable from the database
    afterwards.
    """
    created = await team_import_service.commit_import(
        db, rows=[row.model_dump() for row in payload.rows]
    )
    return ImportCommitOut(
        created_count=len(created),
        teams=[ImportedTeamOut(**team) for team in created],
    )


@router.post("/teams/credentials-export", response_class=Response)
async def export_credentials(
    payload: ImportCommitOut,
    _admin=Depends(require_role(AdminRole.SUPER_ADMIN)),
):
    """Turn the result of an import into the .xlsx an organiser hands out.

    Takes the teams back from the client rather than re-reading the database
    because passwords are hashed on write — this is the only moment they
    exist in the clear.
    """
    from datetime import datetime, timezone

    content = export_service.build_credentials_workbook(
        teams=[team.model_dump() for team in payload.teams],
        generated_at=datetime.now(timezone.utc),
    )
    return _xlsx_response(content, "team-logins.xlsx")


# ---------------------------------------------------------------------------
# §2.7b Round 2 qualifier export
# ---------------------------------------------------------------------------


@router.get("/rounds/{round_id}/winners", response_model=list[dict])
async def list_round_winners(
    round_id: uuid.UUID,
    recompute: bool = Query(True, description="Re-run fn_compute_room_results first"),
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.ROOM_ADMIN)),
):
    """Final standings for a round, qualifiers flagged — the export's data,
    as JSON, so the console can preview it before downloading."""
    return await export_service.collect_round_results(
        db, round_id=round_id, recompute=recompute
    )


@router.get("/rounds/{round_id}/winners/export", response_class=Response)
async def export_round_winners(
    round_id: uuid.UUID,
    recompute: bool = Query(True, description="Re-run fn_compute_room_results first"),
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.SUPER_ADMIN)),
):
    """The Round 2 qualifier list as a shareable .xlsx.

    Sheet 1 is the qualifiers, seeded by total score across every room —
    the order Round 2 needs. Sheet 2 is the full standings, so the file
    answers "why isn't my team on the list?" on its own.
    """
    content, filename = await export_service.build_winners_export(
        db, round_id=round_id, recompute=recompute
    )
    return _xlsx_response(content, filename)
