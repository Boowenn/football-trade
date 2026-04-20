from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


DATA_MODE_ALIASES = {
    "": "auto",
    "api-football": "api_football_odds",
    "api_football": "api_football_odds",
    "betfair": "auto",
    "free": "auto",
}

LIVE_SCORE_MODE_ALIASES = {
    "": "auto",
    "api-football": "api_football",
    "betfair": "auto",
    "free": "auto",
}


class Settings(BaseSettings):
    app_name: str = "足球赔率分析可视化系统"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    database_url: str = "sqlite:///./football.db"

    data_mode: str = "auto"
    discovery_interval_seconds: int = 1800
    poll_interval_seconds: int = 300
    tracked_markets_limit: int = 12
    market_window_hours: int = 18
    history_points: int = 240
    prematch_odds_refresh_seconds: int = 1800
    live_odds_refresh_seconds: int = 300
    prematch_odds_max_pages: int = 2
    live_odds_max_pages: int = 2

    live_score_mode: str = "auto"
    live_score_interval_seconds: int = 180
    live_score_event_interval_seconds: int = 600
    live_score_match_window_minutes: int = 240
    live_score_event_history_limit: int = 10
    live_score_event_matches_limit: int = 2

    api_football_key: str = ""
    api_football_base_url: str = "https://v3.football.api-sports.io"
    api_football_timezone: str = "Asia/Tokyo"
    preferred_bookmakers: str = "Bet365,William Hill,1xBet,Pinnacle,Unibet"
    target_league_ids: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def root_dir(self) -> Path:
        return Path(__file__).resolve().parents[2]

    @property
    def static_dir(self) -> Path:
        return Path(__file__).resolve().parent / "static"

    @property
    def api_football_ready(self) -> bool:
        return bool(self.api_football_key)

    @property
    def normalized_data_mode(self) -> str:
        raw = self.data_mode.lower().strip()
        return DATA_MODE_ALIASES.get(raw, raw)

    @property
    def normalized_live_score_mode(self) -> str:
        raw = self.live_score_mode.lower().strip()
        return LIVE_SCORE_MODE_ALIASES.get(raw, raw)

    @property
    def preferred_bookmaker_names(self) -> list[str]:
        return [item.strip() for item in self.preferred_bookmakers.split(",") if item.strip()]

    @property
    def target_league_id_list(self) -> set[int]:
        values: set[int] = set()
        for raw in self.target_league_ids.split(","):
            raw = raw.strip()
            if not raw:
                continue
            try:
                values.add(int(raw))
            except ValueError:
                continue
        return values


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
