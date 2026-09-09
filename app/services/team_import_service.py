"""
Bulk team registration from a spreadsheet.

The admin console used to create teams one modal at a time. This module takes
the registration sheet the event collects anyway (a Google Form export, a
shared .xlsx, a .csv) and turns it into ready-to-play team accounts:

    team_code : B@GCEE-####  (4 random digits, unique, server-generated)
    password  : the first 4 digits of the team leader's phone number
    team_name : from the sheet
    leader_*  : name / phone / email kept on the team row so the Round 2
                winners export can actually reach the qualifying teams

Two-phase by design. `parse_upload()` only reads: it detects which column is
which, generates the codes and passwords, and reports per-row problems
(missing name, unusable phone, duplicate, over the 40-team cap) without
touching the database. The admin sees exactly what will be created, fixes the
sheet or drops the bad rows, and only then does `commit_import()` write. A
half-imported roster 20 minutes before an event is precisely the failure this
avoids.

Everything above the `commit_import` line is a pure function of its input, so
the column detection, phone normalisation and code format are unit-testable
without a database or a Redis — see tests/test_team_import.py.
"""

from __future__ import annotations

import csv
import io
import re
import secrets
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, ConflictError
from app.core.security import hash_password
from app.models.team import Team

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Team codes are ``B@GCEE-`` + 4 random digits + ``#`` — e.g. ``B@GCEE-7391#``.
TEAM_CODE_PREFIX = "B@GCEE-"
TEAM_CODE_SUFFIX = "#"
TEAM_CODE_DIGITS = 4

#: Length of the derived password: the first N digits of the leader's phone.
PASSWORD_DIGITS = 4

#: Mirrors trg_team_cap in sql/round1_schema.sql. Checked here only so the
#: preview can warn *before* the import runs; the DB trigger is still the
#: authority and will reject an over-cap insert regardless.
MAX_TEAMS = 40

#: How many leading rows to scan when looking for the header row. Registration
#: sheets often carry a title/banner row or two above the actual table.
HEADER_SCAN_ROWS = 10

MAX_UPLOAD_BYTES = 5 * 1024 * 1024


# ---------------------------------------------------------------------------
# Column detection
# ---------------------------------------------------------------------------

#: field -> header synonyms, most specific first. Matched against normalised
#: header text (lowercased, punctuation collapsed to single spaces).
COLUMN_SYNONYMS: dict[str, tuple[str, ...]] = {
    "team_name": (
        "team name",
        "name of the team",
        "name of team",
        "team title",
        "group name",
        "team",
        "group",
    ),
    "leader_name": (
        "team leader name",
        "leader name",
        "name of the leader",
        "team leader",
        "leader",
        "captain",
        "team lead",
        "representative",
    ),
    "leader_phone": (
        "leader phone number",
        "whatsapp number",
        "contact number",
        "mobile number",
        "phone number",
        "contact no",
        "mobile no",
        "phone no",
        "whatsapp",
        "mobile",
        "contact",
        "phone",
    ),
    "leader_email": (
        "email address",
        "email id",
        "e mail",
        "email",
        "mail id",
        "gmail",
        "mail",
    ),
}

#: Fields that must be resolved to a column for the import to be usable at all.
REQUIRED_FIELDS = ("team_name", "leader_phone")


def normalise_header(value: Any) -> str:
    """Lowercase, collapse every run of non-alphanumerics into one space.

    ``"Team Leader's Phone No."`` and ``"team_leader_phone_no"`` both become
    ``"team leader s phone no"``, so header matching doesn't care how the
    organiser punctuated their form.
    """
    if value is None:
        return ""
    return re.sub(r"[^a-z0-9]+", " ", str(value).strip().lower()).strip()


def _score_header(header: str, synonyms: Sequence[str]) -> int:
    """How well one header matches one field's synonym list. 0 = no match.

    An exact match always beats a substring match, and among substring matches
    the longer synonym wins — so a sheet with both "Team Name" and "Team
    Leader Name" maps each to the right field instead of both racing for
    whichever synonym happened to be checked first.
    """
    if not header:
        return 0
    best = 0
    for index, synonym in enumerate(synonyms):
        # Earlier synonyms are more specific; use position as a tie-breaker.
        specificity = len(synonyms) - index
        if header == synonym:
            best = max(best, 1000 + specificity)
        elif synonym in header:
            best = max(best, 100 + len(synonym) * 2 + specificity)
    return best


def detect_columns(headers: Sequence[Any]) -> dict[str, int]:
    """Map ``field -> column index`` for the headers of one sheet.

    Greedy best-first assignment: every (field, column) pair is scored, the
    strongest pair is locked in, and both that field and that column are taken
    out of the running. That way one column can't be claimed by two fields.
    """
    normalised = [normalise_header(h) for h in headers]
    candidates: list[tuple[int, str, int]] = []
    for field_name, synonyms in COLUMN_SYNONYMS.items():
        for col_index, header in enumerate(normalised):
            score = _score_header(header, synonyms)
            if score:
                candidates.append((score, field_name, col_index))

    candidates.sort(key=lambda c: (-c[0], c[1], c[2]))
    mapping: dict[str, int] = {}
    used_columns: set[int] = set()
    for _score, field_name, col_index in candidates:
        if field_name in mapping or col_index in used_columns:
            continue
        mapping[field_name] = col_index
        used_columns.add(col_index)
    return mapping


def _resolve_override(override: str, headers: Sequence[Any]) -> int:
    """Turn an admin-supplied column override into a column index.

    Accepts a 0-based index (``"3"``), a spreadsheet column letter (``"D"``),
    or the header text itself (``"Phone Number"``).
    """
    override = override.strip()
    if not override:
        raise AppError("Empty column override")

    if override.isdigit():
        index = int(override)
        if not 0 <= index < len(headers):
            raise AppError(f"Column index {index} is outside the sheet (0-{len(headers) - 1})")
        return index

    if re.fullmatch(r"[A-Za-z]{1,3}", override):
        index = 0
        for char in override.upper():
            index = index * 26 + (ord(char) - ord("A") + 1)
        index -= 1
        if 0 <= index < len(headers):
            return index

    target = normalise_header(override)
    for col_index, header in enumerate(headers):
        if normalise_header(header) == target:
            return col_index
    raise AppError(f"No column named '{override}' in the sheet")


def apply_overrides(
    mapping: dict[str, int], headers: Sequence[Any], overrides: dict[str, str | None]
) -> dict[str, int]:
    """Let the admin correct auto-detection for any field."""
    resolved = dict(mapping)
    for field_name, override in overrides.items():
        if override is None or not str(override).strip():
            continue
        if field_name not in COLUMN_SYNONYMS:
            raise AppError(f"Unknown column override '{field_name}'")
        resolved[field_name] = _resolve_override(str(override), headers)
    return resolved


# ---------------------------------------------------------------------------
# Value normalisation
# ---------------------------------------------------------------------------


def _cell_text(value: Any) -> str:
    """Spreadsheet cell -> trimmed text.

    Phone numbers typed into Excel come back as floats (``9876543210.0``) often
    enough that stringifying naively would put a ``.0`` in the middle of the
    password. Integral floats are rendered without the decimal tail.
    """
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def team_name_key(value: Any) -> str:
    """The key two team names are considered "the same" under.

    Case-folded *and* internally whitespace-collapsed. The database's
    UNIQUE(team_name) is an exact match, so it would happily accept both
    "Dragon Warriors" and "Dragon  Warriors" — which is precisely the problem:
    at the event an organiser calls one name out and two teams stand up. The
    import flags visually-identical names as duplicates so the sheet gets
    fixed before that happens, rather than deferring to a constraint that
    won't catch it.
    """
    return re.sub(r"\s+", " ", _cell_text(value)).strip().casefold()


def normalise_phone(raw: Any) -> str:
    """Strip a phone number down to the digits that identify the subscriber.

    Everything non-numeric goes (spaces, dashes, brackets, a leading ``+``).
    If more than 10 digits remain the number carries a country/trunk prefix
    (``+91 98765 43210`` -> ``919876543210``), so the *last* 10 are kept —
    otherwise the derived password would be the country code for every single
    team that wrote their number that way.
    """
    digits = re.sub(r"\D", "", _cell_text(raw))
    if len(digits) > 10:
        digits = digits[-10:]
    return digits


def password_from_phone(raw: Any) -> str:
    """The team's login password: the first 4 digits of the leader's phone.

    Returns "" when the cell holds no usable number — the caller turns that
    into a row-level validation error rather than inventing a password.
    """
    digits = normalise_phone(raw)
    if len(digits) < PASSWORD_DIGITS:
        return ""
    return digits[:PASSWORD_DIGITS]


def generate_team_code(taken: set[str]) -> str:
    """``B@GCEE-####`` with 4 random digits, unique against ``taken``.

    ``taken`` is mutated so consecutive calls within one import can't collide
    with each other, not just with the database.
    """
    space = 10**TEAM_CODE_DIGITS

    def code_for(number: int) -> str:
        return f"{TEAM_CODE_PREFIX}{number:0{TEAM_CODE_DIGITS}d}{TEAM_CODE_SUFFIX}"

    # Random first: codes should look unguessable, not sequential, since a
    # team code is half of a login.
    for _ in range(64):
        code = code_for(secrets.randbelow(space))
        if code not in taken:
            taken.add(code)
            return code

    # Random retry alone gets arbitrarily unlucky as the space fills, so fall
    # back to a scan from a random offset. This never matters at event scale
    # (40 teams in a 10,000-code space) but makes the function correct at any
    # fill level instead of probabilistically correct.
    start = secrets.randbelow(space)
    for offset in range(space):
        code = code_for((start + offset) % space)
        if code not in taken:
            taken.add(code)
            return code

    raise ConflictError("Could not generate a free team code — every code is already in use.")


# ---------------------------------------------------------------------------
# Sheet parsing
# ---------------------------------------------------------------------------


@dataclass
class ParsedSheet:
    headers: list[str]
    rows: list[list[Any]]
    header_row_number: int  # 1-based, as shown in Excel
    sheet_name: str | None = None


def _rows_from_csv(data: bytes) -> tuple[list[list[Any]], str | None]:
    text = data.decode("utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    return [list(row) for row in csv.reader(io.StringIO(text), dialect)], None


def _rows_from_xlsx(data: bytes) -> tuple[list[list[Any]], str | None]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise AppError(
            "Excel support is not installed on the server. Run "
            "`pip install openpyxl` (it is already declared in pyproject.toml)."
        ) from exc

    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:
        raise AppError(
            "That file could not be opened as an Excel workbook. If it is an "
            "old .xls file, open it in Excel and re-save as .xlsx."
        ) from exc

    sheet = workbook.active
    rows = [list(row) for row in sheet.iter_rows(values_only=True)]
    name = sheet.title
    workbook.close()
    return rows, name


def _find_header_row(rows: Sequence[Sequence[Any]]) -> int:
    """Index of the row that looks most like a header.

    Registration sheets frequently open with a merged title row ("GCEE 2026 —
    Team Registrations") before the real table, so row 0 is a guess, not a
    given. Score the first few rows by how many of our known fields they'd
    resolve and take the best; ties go to the earliest row.
    """
    best_index, best_score = 0, -1
    for index, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        if not any(_cell_text(cell) for cell in row):
            continue
        mapping = detect_columns(row)
        score = sum(1 for f in COLUMN_SYNONYMS if f in mapping)
        # Prefer rows that resolve the fields we actually need.
        score += sum(2 for f in REQUIRED_FIELDS if f in mapping)
        if score > best_score:
            best_index, best_score = index, score
    return best_index


def parse_sheet(data: bytes, filename: str) -> ParsedSheet:
    """Bytes of an uploaded .xlsx/.csv -> headers + data rows."""
    if not data:
        raise AppError("The uploaded file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise AppError(f"File is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")

    lower = (filename or "").lower()
    if lower.endswith(".csv") or lower.endswith(".txt"):
        rows, sheet_name = _rows_from_csv(data)
    elif lower.endswith(".xlsx") or lower.endswith(".xlsm"):
        rows, sheet_name = _rows_from_xlsx(data)
    elif lower.endswith(".xls"):
        raise AppError(
            "Legacy .xls files aren't supported. Open the file in Excel and "
            "re-save it as .xlsx, then upload again."
        )
    else:
        # No usable extension: sniff the zip magic that every .xlsx starts with.
        if data[:2] == b"PK":
            rows, sheet_name = _rows_from_xlsx(data)
        else:
            rows, sheet_name = _rows_from_csv(data)

    if not rows:
        raise AppError("The sheet has no rows.")

    header_index = _find_header_row(rows)
    headers = [_cell_text(cell) for cell in rows[header_index]]
    # Trailing all-empty columns are an artefact of how Excel sizes a sheet.
    while headers and not headers[-1]:
        headers.pop()
    if not headers:
        raise AppError("Could not find a header row in the sheet.")

    data_rows = [row for row in rows[header_index + 1 :] if any(_cell_text(c) for c in row)]
    return ParsedSheet(
        headers=headers,
        rows=data_rows,
        header_row_number=header_index + 1,
        sheet_name=sheet_name,
    )


# ---------------------------------------------------------------------------
# Row building & validation
# ---------------------------------------------------------------------------

STATUS_OK = "OK"
STATUS_MISSING_TEAM_NAME = "MISSING_TEAM_NAME"
STATUS_INVALID_PHONE = "INVALID_PHONE"
STATUS_DUPLICATE_IN_FILE = "DUPLICATE_IN_FILE"
STATUS_DUPLICATE_IN_DB = "DUPLICATE_IN_DB"
STATUS_OVER_CAPACITY = "OVER_CAPACITY"

STATUS_MESSAGES = {
    STATUS_OK: "Ready to import",
    STATUS_MISSING_TEAM_NAME: "No team name in this row",
    STATUS_INVALID_PHONE: (
        f"Leader's phone has fewer than {PASSWORD_DIGITS} digits — no password can be derived"
    ),
    STATUS_DUPLICATE_IN_FILE: "Another row in this file uses the same team name",
    STATUS_DUPLICATE_IN_DB: "A team with this name already exists",
    STATUS_OVER_CAPACITY: f"Would exceed the {MAX_TEAMS}-team limit",
}


@dataclass
class ImportRow:
    row_number: int  # 1-based row number in the original sheet
    team_name: str
    leader_name: str
    leader_phone: str
    leader_email: str
    team_code: str
    password: str
    status: str
    message: str

    @property
    def is_importable(self) -> bool:
        return self.status == STATUS_OK


@dataclass
class ImportPreview:
    rows: list[ImportRow]
    headers: list[str]
    column_map: dict[str, int]
    unmapped_required: list[str] = field(default_factory=list)
    header_row_number: int = 1
    sheet_name: str | None = None
    existing_team_count: int = 0
    capacity_remaining: int = MAX_TEAMS

    @property
    def importable(self) -> list[ImportRow]:
        return [r for r in self.rows if r.is_importable]


def build_rows(
    parsed: ParsedSheet,
    column_map: dict[str, int],
    *,
    existing_names: Iterable[str],
    existing_codes: Iterable[str],
    capacity: int,
) -> list[ImportRow]:
    """Turn parsed sheet rows into validated, code-and-password-bearing rows.

    Pure: every DB fact it needs (which names/codes are taken, how much room is
    left under the 40-team cap) is passed in.
    """
    existing_name_keys = {team_name_key(n) for n in existing_names}
    taken_codes = set(existing_codes)
    seen_in_file: set[str] = set()

    def cell(row: Sequence[Any], field_name: str) -> str:
        index = column_map.get(field_name)
        if index is None or index >= len(row):
            return ""
        return _cell_text(row[index])

    out: list[ImportRow] = []
    accepted = 0
    for offset, raw_row in enumerate(parsed.rows):
        row_number = parsed.header_row_number + 1 + offset
        team_name = cell(raw_row, "team_name")
        leader_name = cell(raw_row, "leader_name")
        leader_phone_raw = cell(raw_row, "leader_phone")
        leader_email = cell(raw_row, "leader_email")

        leader_phone = normalise_phone(leader_phone_raw)
        password = password_from_phone(leader_phone_raw)
        name_key = team_name_key(team_name)

        if not team_name:
            status = STATUS_MISSING_TEAM_NAME
        elif name_key in seen_in_file:
            status = STATUS_DUPLICATE_IN_FILE
        elif name_key in existing_name_keys:
            status = STATUS_DUPLICATE_IN_DB
        elif not password:
            status = STATUS_INVALID_PHONE
        elif accepted >= capacity:
            status = STATUS_OVER_CAPACITY
        else:
            status = STATUS_OK

        if team_name:
            seen_in_file.add(name_key)

        # Only mint a code for a row that will actually be created — otherwise
        # a sheet full of duplicates would burn through the 4-digit code space.
        code = generate_team_code(taken_codes) if status == STATUS_OK else ""
        if status == STATUS_OK:
            accepted += 1

        out.append(
            ImportRow(
                row_number=row_number,
                team_name=team_name,
                leader_name=leader_name,
                leader_phone=leader_phone or _cell_text(leader_phone_raw),
                leader_email=leader_email,
                team_code=code,
                password=password,
                status=status,
                message=STATUS_MESSAGES[status],
            )
        )
    return out


# ---------------------------------------------------------------------------
# Database-facing entry points
# ---------------------------------------------------------------------------


async def _existing_names_and_codes(db: AsyncSession) -> tuple[list[str], list[str]]:
    rows = (await db.execute(select(Team.team_name, Team.team_code))).all()
    return [r[0] for r in rows], [r[1] for r in rows]


async def parse_upload(
    db: AsyncSession,
    *,
    data: bytes,
    filename: str,
    overrides: dict[str, str | None] | None = None,
) -> ImportPreview:
    """Read-only: parse the upload and report exactly what an import would do.

    Nothing is written. The codes and passwords in the returned rows are the
    real ones — `commit_import` takes them back verbatim — so what the admin
    reviews is what the teams will actually log in with.
    """
    parsed = parse_sheet(data, filename)
    column_map = detect_columns(parsed.headers)
    if overrides:
        column_map = apply_overrides(column_map, parsed.headers, overrides)

    unmapped = [f for f in REQUIRED_FIELDS if f not in column_map]

    existing_names, existing_codes = await _existing_names_and_codes(db)
    capacity = max(0, MAX_TEAMS - len(existing_names))

    rows: list[ImportRow] = []
    if not unmapped:
        rows = build_rows(
            parsed,
            column_map,
            existing_names=existing_names,
            existing_codes=existing_codes,
            capacity=capacity,
        )

    return ImportPreview(
        rows=rows,
        headers=parsed.headers,
        column_map=column_map,
        unmapped_required=unmapped,
        header_row_number=parsed.header_row_number,
        sheet_name=parsed.sheet_name,
        existing_team_count=len(existing_names),
        capacity_remaining=capacity,
    )


async def commit_import(db: AsyncSession, *, rows: Sequence[dict]) -> list[dict]:
    """Create the reviewed teams in a single transaction.

    All-or-nothing on purpose: a partially-imported roster is worse than a
    failed import, because the admin can't tell by looking which half landed.
    The 40-team cap is still enforced underneath by trg_team_cap, whose
    RAISE EXCEPTION surfaces as a clean 409 through
    app/core/exceptions.py.
    """
    if not rows:
        raise AppError("No rows to import.")

    existing_names, existing_codes = await _existing_names_and_codes(db)
    existing_name_keys = {team_name_key(n) for n in existing_names}
    taken_codes = set(existing_codes)

    if len(existing_names) + len(rows) > MAX_TEAMS:
        raise ConflictError(
            f"Importing {len(rows)} teams would exceed the {MAX_TEAMS}-team limit "
            f"({len(existing_names)} already registered)."
        )

    created: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        team_name = str(row.get("team_name", "")).strip()
        if not team_name:
            raise AppError("A row in the confirmed list has no team name.")

        name_key = team_name_key(team_name)
        if name_key in seen or name_key in existing_name_keys:
            raise ConflictError(f"Duplicate team name in the import: '{team_name}'")
        seen.add(name_key)

        password = str(row.get("password", "")).strip()
        if not password:
            # Re-derive rather than trust a blank: the client may have edited
            # the phone number in the preview table before confirming.
            password = password_from_phone(row.get("leader_phone"))
        if not password:
            raise AppError(f"No password could be derived for team '{team_name}'.")

        code = str(row.get("team_code", "")).strip()
        if not code or code in taken_codes:
            code = generate_team_code(taken_codes)
        else:
            taken_codes.add(code)

        team = Team(
            team_id=uuid.uuid4(),
            team_code=code,
            team_name=team_name,
            password_hash=hash_password(password),
            leader_name=str(row.get("leader_name", "")).strip() or None,
            leader_phone=str(row.get("leader_phone", "")).strip() or None,
            leader_email=str(row.get("leader_email", "")).strip() or None,
        )
        db.add(team)
        created.append(
            {
                "team_id": team.team_id,
                "team_code": code,
                "team_name": team_name,
                "password": password,
                "leader_name": team.leader_name,
                "leader_phone": team.leader_phone,
                "leader_email": team.leader_email,
            }
        )

    await db.flush()
    await db.commit()
    return created
