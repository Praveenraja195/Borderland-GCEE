import logging
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("round1.startup")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://round1:round1@localhost:5432/round1"
    sync_database_url: str = "postgresql+psycopg2://round1:round1@localhost:5432/round1"

    # Redis (scheduler job store + websocket pub/sub)
    redis_url: str = "redis://localhost:6379/0"

    # JWT
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 720

    # MindMaze board constraints (Fix §1.1)
    mindmaze_max_tiles: int = 20
    mindmaze_min_seconds_per_tile: float = 0.5

    # MindMaze sub-round pacing (bug-fix batch, Aug 2026): MindMaze's client
    # is a fixed memorize -> input mini-game (see frontend
    # team-app/js/screens/games/mindmaze.js MEMORIZE_DURATION/INPUT_DURATION),
    # NOT an admin-configurable countdown like King of Diamonds / Jack of
    # Hearts. Previously the admin's arbitrary "duration_minutes" was used
    # to space every MindMaze sub-round back-to-back, which desynced the
    # server-side deadline (often minutes) from the client's real ~60s
    # playtime: a team that finished early sat on a "submitted, waiting"
    # screen until the admin's full (much longer) duration elapsed, and a
    # reload during that gap replayed the same still-open sub-round,
    # attempting a second submit against it (see mindmaze_service.submit_result).
    # These three settings are now the single source of truth for MindMaze
    # sub-round timing, on both server and client — the admin is no longer
    # asked for a duration when starting MindMaze.
    mindmaze_memorize_seconds: int = 30
    mindmaze_input_seconds: int = 30

    @property
    def mindmaze_round_seconds(self) -> int:
        """Total active playtime for one MindMaze sub-round (memorize + input)."""
        return self.mindmaze_memorize_seconds + self.mindmaze_input_seconds

    # Ace of Spades board constraints, mirroring MindMaze's Fix §1.1 bound:
    # only 8 cards are ever memorised in one sub-round (plus 2 decoys mixed
    # in for the recall phase), so correct_picks can never legitimately
    # exceed that.
    ace_spade_max_cards: int = 8

    # Ace of Spades sub-round pacing: like MindMaze, a fixed memorize ->
    # select mini-game (see frontend
    # team-app/js/screens/games/ace-spade.js MEMORIZE_DURATION/SELECT_DURATION),
    # not an admin-configurable countdown. These are the single source of
    # truth for Ace of Spades sub-round timing, on both server and client.
    ace_spade_memorize_seconds: int = 30
    ace_spade_select_seconds: int = 40
    # Each of the two phases is preceded by a shuffle-and-deal animation on
    # the client (pile → shuffle → deal). It gets its own slot so the
    # memorize/select clocks only run once the cards are in place. MUST
    # match DEAL_DURATION in ace-spade.js.
    ace_spade_deal_seconds: int = 8

    @property
    def ace_spade_round_seconds(self) -> int:
        """Total length of one Ace of Spades sub-round: deal + memorize + deal + select."""
        return (
            self.ace_spade_memorize_seconds
            + self.ace_spade_select_seconds
            + 2 * self.ace_spade_deal_seconds
        )

    # King of Diamonds sub-round pacing (Aug 2026 update): like MindMaze,
    # King of Diamonds now auto-submits and runs a fixed-length sub-round
    # instead of using the admin's arbitrary "duration_minutes" — the
    # submit button is gone from the client, so the round MUST end itself.
    # This is the single source of truth for King of Diamonds sub-round
    # timing, used everywhere a sub-round's start_time/deadline is set
    # (session_service.start_session / start_next_subround /
    # start_subround_by_number).
    king_diamond_round_seconds: int = 45

    # King of Diamonds scoring (Aug 2026 update): each sub-round, every team
    # starts with this many points; the team nearest the target loses none,
    # each next-nearest team loses one more point than the team ahead of it
    # (2nd nearest -1, 3rd nearest -2, ...), floored at 0. See
    # king_diamond_service.close_round.
    king_diamond_base_points: int = 20
    king_diamond_reveal_seconds: int = 15

    # CORS (Audit Issue 11): comma-separated list of allowed origins.
    cors_origins: str = "*"

    # Misc
    environment: str = "development"

    # Fix §3.3: set RUN_SCHEDULER=1 in only ONE process (or the dedicated
    # scheduler worker) so APScheduler never runs concurrently across workers.
    run_scheduler: bool = False

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()


def validate_production_settings() -> None:
    """Fix §3.4: refuse to start in non-dev mode with a placeholder JWT secret."""
    if settings.environment != "development" and settings.jwt_secret in ("change-me", ""):
        raise RuntimeError(
            "JWT_SECRET must be set to a real random value in non-development environments. "
            "Set the JWT_SECRET environment variable before starting the server."
        )
    if settings.environment != "development" and settings.jwt_secret == "change-me-to-a-long-random-string":
        raise RuntimeError(
            "JWT_SECRET is still the placeholder value from .env.example. "
            "Replace it with a real secret before deploying."
        )
    if settings.environment != "development":
        logger.info("Production mode: JWT_SECRET validated OK.")
