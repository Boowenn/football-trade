from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class MatchInfo(Base):
    __tablename__ = "match_info"

    market_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(64), index=True)
    event_name: Mapped[str] = mapped_column(String(255), index=True)
    market_name: Mapped[str] = mapped_column(String(64), default="Match Winner")
    home_name: Mapped[str] = mapped_column(String(255), default="")
    away_name: Mapped[str] = mapped_column(String(255), default="")
    start_time: Mapped[DateTime] = mapped_column(DateTime(timezone=True), index=True)
    provider: Mapped[str] = mapped_column(String(32), default="demo")
    status: Mapped[str] = mapped_column(String(32), default="OPEN")
    in_play: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), index=True)


class MarketTick(Base):
    __tablename__ = "market_ticks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(String(64), index=True)
    timestamp: Mapped[DateTime] = mapped_column(DateTime(timezone=True), index=True)
    in_play: Mapped[bool] = mapped_column(Boolean, default=False)
    total_matched: Mapped[float] = mapped_column(Float, default=0.0)
    primary_back_price: Mapped[float] = mapped_column(Float, default=0.0)
    primary_lay_price: Mapped[float] = mapped_column(Float, default=0.0)
    primary_spread: Mapped[float] = mapped_column(Float, default=0.0)
    snapshot_json: Mapped[str] = mapped_column(Text)


class MarketSignal(Base):
    __tablename__ = "market_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(String(64), index=True)
    signal_type: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(32), default="info")
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), index=True)


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(String(64), index=True)
    recommendation: Mapped[str] = mapped_column(String(32), index=True)
    selection_name: Mapped[str] = mapped_column(String(255), default="")
    score: Mapped[float] = mapped_column(Float, default=0.0)
    risk_level: Mapped[str] = mapped_column(String(32), default="Medium")
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), index=True)
