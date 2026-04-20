from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RunnerState(BaseModel):
    selection_id: int
    name: str
    price: float | None = None
    best_price: float | None = None
    worst_price: float | None = None
    implied_probability: float | None = None
    bookmaker_count: int = 0
    market_width: float | None = None
    mid_price: float | None = None
    spread: float | None = None
    momentum: float = 0.0
    outcome_key: str = "draw"
    bookmakers: list[dict[str, Any]] = Field(default_factory=list)


class MatchSummary(BaseModel):
    market_id: str
    event_id: str
    event_name: str
    home_name: str
    away_name: str
    market_name: str
    provider: str
    start_time: datetime
    in_play: bool
    status: str
    bookmaker_count: int | None = None
    overround: float | None = None
    spread: float | None = None
    signal: str = "neutral"
    confidence: float = 0.0
    updated_at: datetime
    live_score: dict[str, Any] = Field(default_factory=dict)


class RecommendationPayload(BaseModel):
    market_id: str
    recommendation: str
    selection_name: str = ""
    market_label: str = "胜平负"
    score: float = 0.0
    confidence_label: str = "不下注"
    risk_level: str = "Medium"
    reasons: list[str] = Field(default_factory=list)
    breakdown: dict[str, float] = Field(default_factory=dict)
    signal: str = "neutral"
    generated_at: datetime


class MarketSnapshot(BaseModel):
    market_id: str
    event_id: str
    event_name: str
    home_name: str
    away_name: str
    market_name: str
    provider: str
    start_time: datetime
    status: str
    in_play: bool
    total_matched: float | None = None
    updated_at: datetime
    runners: list[RunnerState]
    recommendation: RecommendationPayload | None = None
    signals: list[dict[str, Any]] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)
    live_score: dict[str, Any] = Field(default_factory=dict)


class TimePoint(BaseModel):
    timestamp: datetime
    in_play: bool
    total_matched: float | None = None
    minute: int | None = None
    home_score: int | None = None
    away_score: int | None = None
    runners: list[dict[str, Any]]


class SystemStatus(BaseModel):
    app_name: str
    configured_mode: str
    active_provider: str
    fallback_active: bool = False
    data_ready: bool = False
    api_football_ready: bool = False
    last_error: str | None = None
    live_score_configured_mode: str
    active_live_score_provider: str
    live_score_fallback_active: bool = False
    live_score_ready: bool = False
    live_score_last_error: str | None = None
    updated_at: datetime
