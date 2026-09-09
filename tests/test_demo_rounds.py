"""
Demo (practice) round tests.

Unlike the rest of the suite these need no Postgres: the whole point of
`app/services/demo_service.py` is that a practice round lives entirely in
Redis, so the only database access to stub out is a handful of read-only
lookups (which rooms are in the round, who is in the room, the card deck).
Everything else — the Redis state machine, lazy closing, scoring, restart,
pause/resume, teardown — runs for real against `fakeredis`.

The scoring assertions are deliberately spelled out in full rather than
recomputed from the service's own helpers: they are what pins a practice
round to the same rules as a real one, so they should fail loudly if either
side's scoring changes.
"""

import uuid
from datetime import timedelta

import pytest

from app.services import demo_service as ds

fakeredis = pytest.importorskip("fakeredis", reason="fakeredis is needed for the demo-round tests")
import fakeredis.aioredis  # noqa: E402

ROUND_ID = uuid.uuid4()
ROOM_ID = uuid.uuid4()

TEAMS = [
    {"team_id": str(uuid.uuid4()), "team_code": "T01", "team_name": "Alpha", "suit_code": "SPADE", "suit_symbol": "♠"},
    {"team_id": str(uuid.uuid4()), "team_code": "T02", "team_name": "Bravo", "suit_code": "HEART", "suit_symbol": "♥"},
    {"team_id": str(uuid.uuid4()), "team_code": "T03", "team_name": "Chi", "suit_code": "CLUB", "suit_symbol": "♣"},
    {"team_id": str(uuid.uuid4()), "team_code": "T04", "team_name": "Delta", "suit_code": "DIAMOND", "suit_symbol": "♦"},
]

_SUIT_ORDER = ["SPADE", "HEART", "DIAMOND", "CLUB"]
_RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10"]
# Mirrors the jh_symbols seed in sql/round1_schema.sql: ids 1-40, ten per
# suit, in spade / heart / diamond / club order.
DECK = [
    {
        "symbol_id": suit_index * 10 + rank_index + 1,
        "code": f"{_SUIT_ORDER[suit_index]}_{_RANKS[rank_index]}",
        "label": f"{_SUIT_ORDER[suit_index]} {_RANKS[rank_index]}",
        "suit": _SUIT_ORDER[suit_index],
        "rank": _RANKS[rank_index],
    }
    for suit_index in range(4)
    for rank_index in range(10)
]


class _FakeRoom:
    round_id = ROUND_ID


class _FakeDB:
    """Stands in for the AsyncSession. `Room` is the only entity the demo
    service loads by primary key."""

    async def get(self, model, pk):
        return _FakeRoom()


@pytest.fixture
def db():
    return _FakeDB()


@pytest.fixture(autouse=True)
def demo_env(monkeypatch):
    """Point the service at an in-memory Redis and stub its three read-only
    DB lookups."""
    monkeypatch.setattr(ds, "_client", fakeredis.aioredis.FakeRedis(decode_responses=True))

    async def rooms_with_game(db, *, round_id, game_code):
        return [(ROOM_ID, "R01")]

    async def roster(db, room_id):
        return [dict(t) for t in TEAMS]

    async def symbol_deck(db):
        return [dict(c) for c in DECK]

    async def assert_team_in_room(db, *, team_id, room_id):
        return None

    monkeypatch.setattr(ds, "_rooms_with_game", rooms_with_game)
    monkeypatch.setattr(ds, "_roster", roster)
    monkeypatch.setattr(ds, "_symbol_deck", symbol_deck)
    monkeypatch.setattr(ds, "_assert_team_in_room", assert_team_in_room)
    yield


async def _expire_subround(game_code, sub_index=0):
    """Backdate a sub-round's deadline so the lazy close fires on next read.

    Demo sub-rounds have no scheduler job by design — they close when
    someone next looks at them, or when the whole room has submitted.
    """
    key = ds._session_key(ROUND_ID, game_code, ROOM_ID)
    blob = await ds._read_session(key)
    blob["rounds"][sub_index]["deadline"] = ds._iso(
        ds._now() - timedelta(seconds=ds.CLOSE_GRACE_SECONDS + 5)
    )
    await ds._write_session(blob)


async def _team_session(db, team_index=0):
    sessions = await ds.list_team_demo_sessions(
        db, room_id=ROOM_ID, team_id=TEAMS[team_index]["team_id"]
    )
    return sessions[0]


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


async def test_start_deals_subrounds_and_arms_only_the_first(db):
    results = await ds.start_demo(
        db, round_id=ROUND_ID, game_code="MINDMAZE", duration_minutes=1, num_rounds=2
    )
    assert results[0]["ok"] is True

    session = await _team_session(db)
    assert session["is_demo"] is True
    assert session["game_code"] == "MINDMAZE"
    assert len(session["rounds"]) == 2
    # Sub-round 1 starts on its own countdown; the rest wait for the admin,
    # exactly like a real session.
    assert session["rounds"][0]["start_time"] is not None
    assert session["rounds"][1]["start_time"] is None


async def test_start_is_refused_while_a_demo_is_live(db):
    await ds.start_demo(db, round_id=ROUND_ID, game_code="MINDMAZE", duration_minutes=1, num_rounds=1)
    results = await ds.start_demo(
        db, round_id=ROUND_ID, game_code="MINDMAZE", duration_minutes=1, num_rounds=1
    )
    assert results[0]["ok"] is False
    assert "already running" in results[0]["reason"]


async def test_restart_deals_a_fresh_attempt_and_wipes_the_previous_one(db):
    """The practice-again path: a room can rehearse as many times as it
    wants, and nothing carries over between attempts."""
    await ds.start_demo(db, round_id=ROUND_ID, game_code="MINDMAZE", duration_minutes=1, num_rounds=1)
    session = await _team_session(db)
    first_round_id = session["rounds"][0]["round_id"]

    await ds.submit_mindmaze(
        db, demo_round_id=first_round_id, team_id=TEAMS[0]["team_id"],
        moves=14, mistakes=3, correct_tiles=11, completion_time_seconds=20.0,
    )
    await _expire_subround("MINDMAZE")

    await ds.restart_demo(db, round_id=ROUND_ID, game_code="MINDMAZE")
    after = (await ds.list_demo_for_round(db, round_id=ROUND_ID, game_code="MINDMAZE"))[0]

    assert after["attempt"] == 2
    assert after["status"] == "IN_PROGRESS"
    assert after["rounds"][0]["round_id"] != first_round_id
    assert after["rounds"][0]["submitted_teams"] == []
    # The previous attempt's submissions are gone from Redis entirely.
    assert await ds._redis().exists(ds._subs_key(first_round_id)) == 0

    board = await ds.demo_leaderboard(
        db, room_id=ROOM_ID, game_code="MINDMAZE", team_id=TEAMS[0]["team_id"]
    )
    assert all(row["total_score"] == 0.0 for row in board)


async def test_end_demo_removes_every_trace(db):
    await ds.start_demo(db, round_id=ROUND_ID, game_code="MINDMAZE", duration_minutes=1, num_rounds=2)
    await ds.end_demo(db, round_id=ROUND_ID, game_code="MINDMAZE")

    # Team screens fall straight back to the real session.
    assert await ds.list_team_demo_sessions(db, room_id=ROOM_ID, team_id=TEAMS[0]["team_id"]) == []
    assert await ds._redis().keys("*") == []


async def test_pause_gives_back_the_time_it_took(db):
    await ds.start_demo(db, round_id=ROUND_ID, game_code="MINDMAZE", duration_minutes=1, num_rounds=1)
    key = ds._session_key(ROUND_ID, "MINDMAZE", ROOM_ID)
    before = ds._parse((await ds._read_session(key))["rounds"][0]["deadline"])

    await ds.pause_demo(db, round_id=ROUND_ID, game_code="MINDMAZE")
    blob = await ds._read_session(key)
    assert blob["status"] == "PAUSED"

    # Backdate the pause so the resume shift is measurable.
    blob["paused_at"] = ds._iso(ds._now() - timedelta(seconds=30))
    await ds._write_session(blob)

    await ds.resume_demo(db, round_id=ROUND_ID, game_code="MINDMAZE")
    resumed = await ds._read_session(key)
    after = ds._parse(resumed["rounds"][0]["deadline"])

    assert resumed["status"] == "IN_PROGRESS"
    assert 28 <= (after - before).total_seconds() <= 32


async def test_paused_demo_rejects_submissions(db):
    await ds.start_demo(db, round_id=ROUND_ID, game_code="MINDMAZE", duration_minutes=1, num_rounds=1)
    session = await _team_session(db)
    await ds.pause_demo(db, round_id=ROUND_ID, game_code="MINDMAZE")

    with pytest.raises(Exception, match="paused"):
        await ds.submit_mindmaze(
            db, demo_round_id=session["rounds"][0]["round_id"], team_id=TEAMS[0]["team_id"],
            moves=1, mistakes=0, correct_tiles=1, completion_time_seconds=1.0,
        )


async def test_subround_can_be_replayed_on_its_own(db):
    await ds.start_demo(db, round_id=ROUND_ID, game_code="MINDMAZE", duration_minutes=1, num_rounds=1)
    session = await _team_session(db)
    round_id = session["rounds"][0]["round_id"]

    await ds.submit_mindmaze(
        db, demo_round_id=round_id, team_id=TEAMS[0]["team_id"],
        moves=5, mistakes=0, correct_tiles=5, completion_time_seconds=10.0,
    )
    await _expire_subround("MINDMAZE")
    assert (await _team_session(db))["rounds"][0]["is_closed"] is True

    await ds.restart_demo_subround(db, round_id=ROUND_ID, game_code="MINDMAZE", subround_number=1)
    replayed = await _team_session(db)
    assert replayed["rounds"][0]["is_closed"] is False
    assert replayed["rounds"][0]["submitted"] is False
    assert replayed["status"] == "IN_PROGRESS"


async def test_demo_completes_once_every_subround_closes(db):
    await ds.start_demo(db, round_id=ROUND_ID, game_code="MINDMAZE", duration_minutes=1, num_rounds=2)
    await _expire_subround("MINDMAZE", 0)
    assert (await ds.list_demo_for_round(db, round_id=ROUND_ID, game_code="MINDMAZE"))[0]["status"] == "IN_PROGRESS"

    await ds.start_demo_subround(db, round_id=ROUND_ID, game_code="MINDMAZE", subround_number=2)
    await _expire_subround("MINDMAZE", 1)
    assert (await ds.list_demo_for_round(db, round_id=ROUND_ID, game_code="MINDMAZE"))[0]["status"] == "COMPLETED"


# ---------------------------------------------------------------------------
# Play state visible before a sub-round closes
# ---------------------------------------------------------------------------


async def test_submission_is_visible_before_the_subround_closes(db):
    """The team app decides between "show the board" and "show the waiting
    screen" from `submitted`. If that only flipped at close, a team that had
    already played would be handed the board again on the next poll."""
    await ds.start_demo(db, round_id=ROUND_ID, game_code="MINDMAZE", duration_minutes=1, num_rounds=1)
    session = await _team_session(db)
    round_id = session["rounds"][0]["round_id"]

    await ds.submit_mindmaze(
        db, demo_round_id=round_id, team_id=TEAMS[0]["team_id"],
        moves=14, mistakes=3, correct_tiles=11, completion_time_seconds=22.5,
    )

    mine = await _team_session(db, team_index=0)
    assert mine["rounds"][0]["is_closed"] is False
    assert mine["rounds"][0]["submitted"] is True
    # MindMaze is scored from a team's own board alone, so its score is
    # already final at submit time.
    assert mine["rounds"][0]["score"] == 9.5

    theirs = await _team_session(db, team_index=1)
    assert theirs["rounds"][0]["submitted"] is False

    admin = (await ds.list_demo_for_round(db, round_id=ROUND_ID, game_code="MINDMAZE"))[0]
    assert admin["rounds"][0]["submitted_teams"] == ["T01"]


# ---------------------------------------------------------------------------
# Scoring parity with the real games
# ---------------------------------------------------------------------------


async def test_mindmaze_scores_one_per_tile_minus_half_per_mistake(db):
    await ds.start_demo(db, round_id=ROUND_ID, game_code="MINDMAZE", duration_minutes=1, num_rounds=1)
    session = await _team_session(db)
    round_id = session["rounds"][0]["round_id"]

    result = await ds.submit_mindmaze(
        db, demo_round_id=round_id, team_id=TEAMS[0]["team_id"],
        moves=14, mistakes=3, correct_tiles=11, completion_time_seconds=22.5,
    )
    assert result["round_score"] == 9.5  # 11 - (3 * 0.5)

    await _expire_subround("MINDMAZE")
    board = await ds.demo_leaderboard(
        db, room_id=ROOM_ID, game_code="MINDMAZE", team_id=TEAMS[0]["team_id"]
    )
    assert board[0]["team_code"] == "T01"
    assert board[0]["total_score"] == 9.5
    assert [row["rank"] for row in board] == [1, 2, 3, 4]
    # Teams that never played still appear, on zero.
    assert all(row["total_score"] == 0.0 for row in board[1:])


async def test_ace_spade_scores_two_per_correct_pick_minus_half_per_wrong_pick(db):
    await ds.start_demo(db, round_id=ROUND_ID, game_code="ACE_SPADE", duration_minutes=1, num_rounds=1)
    session = await _team_session(db)
    round_id = session["rounds"][0]["round_id"]

    # 5 correct picks, 2 wrong picks -> (5 * 2.0) - (2 * 0.5) = 9.0 pts
    result = await ds.submit_ace_spade(
        db, demo_round_id=round_id, team_id=TEAMS[0]["team_id"],
        moves=7, wrong_picks=2, correct_picks=5, completion_time_seconds=18.0,
    )
    assert result["round_score"] == 9.0

    # 1 correct pick, 6 wrong picks -> (1 * 2.0) - (6 * 0.5) = -1.0 -> floored at 0.0
    result_floored = await ds.submit_ace_spade(
        db, demo_round_id=round_id, team_id=TEAMS[1]["team_id"],
        moves=7, wrong_picks=6, correct_picks=1, completion_time_seconds=25.0,
    )
    assert result_floored["round_score"] == 0.0

    # Full 8 correct picks, 0 wrong -> 8 * 2.0 = 16.0 pts
    result_perfect = await ds.submit_ace_spade(
        db, demo_round_id=round_id, team_id=TEAMS[2]["team_id"],
        moves=8, wrong_picks=0, correct_picks=8, completion_time_seconds=12.0,
    )
    assert result_perfect["round_score"] == 16.0

    await _expire_subround("ACE_SPADE")
    board = await ds.demo_leaderboard(
        db, room_id=ROOM_ID, game_code="ACE_SPADE", team_id=TEAMS[0]["team_id"]
    )
    scores = {row["team_code"]: row["total_score"] for row in board}
    assert scores["T03"] == 16.0
    assert scores["T01"] == 9.0
    assert scores["T02"] == 0.0
    assert scores["T04"] == 0.0


async def test_king_diamond_target_ranking_and_penalty_ladder(db):
    """avg(40, 52, 80, 70) = 60.5 -> target 48.4. Distances 8.4 / 3.6 / 31.6
    / 21.6 put the nearness order at T02, T01, T04, T03, and the ladder
    (0, 1, 2.5, 4.5) is king_diamond_service's 0.25*(r-1)*(r+2)."""
    await ds.start_demo(db, round_id=ROUND_ID, game_code="KING_DIAMOND", duration_minutes=1, num_rounds=1)
    session = await _team_session(db)
    round_id = session["rounds"][0]["round_id"]

    for team_index, number in {0: 40, 1: 52, 2: 80, 3: 70}.items():
        await ds.submit_king_diamond(
            db, demo_round_id=round_id, team_id=TEAMS[team_index]["team_id"], submitted_number=number
        )

    # The whole room is in, so the sub-round closes without waiting for the
    # timer — same early close the real game does.
    winner = await ds.king_diamond_result(db, demo_round_id=round_id, team_id=TEAMS[1]["team_id"])
    assert winner["is_closed"] is True
    assert winner["average_value"] == 60.5
    assert winner["target_value"] == 48.4
    assert winner["rank"] == 1
    assert winner["penalty"] == 0.0
    assert winner["round_score"] == 20.0  # keeps the full base (1 round * 20)

    assert [s["team_code"] for s in winner["all_submissions"]] == ["T02", "T01", "T04", "T03"]
    assert [s["penalty"] for s in winner["all_submissions"]] == [0.0, 1.0, 2.5, 4.5]

    third = await ds.king_diamond_result(db, demo_round_id=round_id, team_id=TEAMS[3]["team_id"])
    assert third["round_score"] == 17.5  # 20 - 2.5

    board = await ds.demo_leaderboard(
        db, room_id=ROOM_ID, game_code="KING_DIAMOND", team_id=TEAMS[0]["team_id"]
    )
    assert [row["team_code"] for row in board] == ["T02", "T01", "T04", "T03"]


async def test_king_diamond_non_submitter_forfeits_the_base(db):
    await ds.start_demo(db, round_id=ROUND_ID, game_code="KING_DIAMOND", duration_minutes=1, num_rounds=1)
    session = await _team_session(db)
    round_id = session["rounds"][0]["round_id"]

    await ds.submit_king_diamond(
        db, demo_round_id=round_id, team_id=TEAMS[0]["team_id"], submitted_number=50
    )
    await _expire_subround("KING_DIAMOND")

    absent = await ds.king_diamond_result(db, demo_round_id=round_id, team_id=TEAMS[1]["team_id"])
    assert absent["is_valid"] is False
    assert absent["penalty"] == 20.0
    assert absent["round_score"] == 0.0  # 20 - 20


async def test_jack_heart_deals_from_each_team_own_suit(db):
    await ds.start_demo(db, round_id=ROUND_ID, game_code="JACK_HEART", duration_minutes=1, num_rounds=1)
    session = await _team_session(db)
    assignments = await ds._read_assignments(session["rounds"][0]["round_id"])

    card_by_id = {card["symbol_id"]: card for card in DECK}
    assert len(assignments) == len(TEAMS)
    for team in TEAMS:
        assert card_by_id[assignments[team["team_id"]]]["suit"] == team["suit_code"]


async def test_jack_heart_never_reveals_your_own_card(db):
    """The same guarantee jack_heart_service.get_visible_symbols makes — and
    the whole game, so it is worth asserting on the practice path too."""
    await ds.start_demo(db, round_id=ROUND_ID, game_code="JACK_HEART", duration_minutes=1, num_rounds=1)
    session = await _team_session(db)
    round_id = session["rounds"][0]["round_id"]

    visible = await ds.jack_heart_visible_symbols(
        db, demo_round_id=round_id, team_id=TEAMS[0]["team_id"]
    )
    assert len(visible) == len(TEAMS) - 1
    assert all(entry["team_id"] != TEAMS[0]["team_id"] for entry in visible)

    mine = await ds.jack_heart_my_suit(db, demo_round_id=round_id, team_id=TEAMS[0]["team_id"])
    assert mine["suit_code"] == "SPADE"
    # You may only name a card from your own suit.
    assert len(mine["symbols"]) == 10
    assert all(symbol["suit"] == "SPADE" for symbol in mine["symbols"])


async def test_jack_heart_scores_ten_for_a_correct_guess(db):
    await ds.start_demo(db, round_id=ROUND_ID, game_code="JACK_HEART", duration_minutes=1, num_rounds=1)
    session = await _team_session(db)
    round_id = session["rounds"][0]["round_id"]
    assignments = await ds._read_assignments(round_id)

    await ds.submit_jack_heart(
        db, demo_round_id=round_id, team_id=TEAMS[0]["team_id"],
        submitted_symbol_id=assignments[TEAMS[0]["team_id"]],
    )
    actual_for_t02 = assignments[TEAMS[1]["team_id"]]
    await ds.submit_jack_heart(
        db, demo_round_id=round_id, team_id=TEAMS[1]["team_id"],
        submitted_symbol_id=11 if actual_for_t02 != 11 else 12,
    )
    await _expire_subround("JACK_HEART")

    scores = {
        row["team_code"]: row["total_score"]
        for row in await ds.demo_leaderboard(
            db, room_id=ROOM_ID, game_code="JACK_HEART", team_id=TEAMS[0]["team_id"]
        )
    }
    assert scores["T01"] == 10.0
    assert scores["T02"] == 0.0
    assert scores["T03"] == 0.0 and scores["T04"] == 0.0


# ---------------------------------------------------------------------------
# Isolation — the reason this whole surface exists
# ---------------------------------------------------------------------------


async def test_all_demo_state_is_namespaced_and_disposable(db):
    await ds.start_demo(db, round_id=ROUND_ID, game_code="MINDMAZE", duration_minutes=1, num_rounds=1)
    session = await _team_session(db)
    await ds.submit_mindmaze(
        db, demo_round_id=session["rounds"][0]["round_id"], team_id=TEAMS[0]["team_id"],
        moves=5, mistakes=1, correct_tiles=4, completion_time_seconds=10.0,
    )

    keys = await ds._redis().keys("*")
    assert keys, "a running demo should have state"
    assert all(key.startswith("demo:") for key in keys)


async def test_a_team_outside_the_room_cannot_play(db):
    await ds.start_demo(db, round_id=ROUND_ID, game_code="MINDMAZE", duration_minutes=1, num_rounds=1)
    session = await _team_session(db)

    with pytest.raises(Exception, match="not in this demo"):
        await ds.submit_mindmaze(
            db, demo_round_id=session["rounds"][0]["round_id"], team_id=str(uuid.uuid4()),
            moves=1, mistakes=0, correct_tiles=1, completion_time_seconds=1.0,
        )


async def test_demo_service_never_writes_to_the_database():
    """The load-bearing invariant, asserted against the source itself.

    A practice round must not be able to reach game_scores, the per-game
    result tables, room_results, or any leaderboard. Every one of those
    would require a write through the SQLAlchemy session, so the cheapest
    durable guard is that this module contains no write at all — only
    `select(...)` reads.
    """
    import pathlib
    import re

    source = pathlib.Path(ds.__file__).read_text(encoding="utf-8")
    # Strip the module docstring, which names these calls to explain the rule.
    body = source.split('"""', 2)[-1]

    forbidden = [
        r"\bdb\.add\b",
        r"\bdb\.add_all\b",
        r"\bdb\.commit\b",
        r"\bdb\.flush\b",
        r"\bdb\.delete\b",
        r"\bdb\.merge\b",
        r"\bdb\.execute\(\s*text\(",
        # SQLAlchemy's DML constructs, as bare calls. The negative lookbehind
        # keeps Redis' own `.delete(...)` — which is how a demo cleans up
        # after itself — from tripping this.
        r"(?<![.\w])(insert|update|delete)\(",
    ]
    offenders = [pattern for pattern in forbidden if re.search(pattern, body)]
    assert not offenders, f"demo_service must stay read-only; found: {offenders}"
