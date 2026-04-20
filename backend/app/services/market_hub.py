from __future__ import annotations

import asyncio
import json
from collections import defaultdict, deque
from datetime import UTC, datetime
from typing import Any

from fastapi import WebSocket

from ..config import Settings
from ..database import init_db, session_scope
from ..models import MarketSignal, MarketTick, MatchInfo, Recommendation
from .analyzer import build_recommendation
from .live_scores import build_live_score_provider, empty_live_score
from .providers import build_provider, quote_to_dict


class MarketHub:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.provider = build_provider(settings)
        self.live_score_provider = build_live_score_provider(settings)

        self.markets: dict[str, dict[str, Any]] = {}
        self.recommendations: dict[str, dict[str, Any]] = {}
        self.live_states: dict[str, dict[str, Any]] = {}
        self.history: dict[str, deque[dict[str, Any]]] = defaultdict(
            lambda: deque(maxlen=self.settings.history_points)
        )

        self.tasks: list[asyncio.Task] = []
        self.clients: set[WebSocket] = set()
        self.signal_signatures: dict[str, str] = {}
        self.recommendation_signatures: dict[str, str] = {}
        self.updated_at = datetime.now(UTC)

        self.runtime_error: str | None = None
        self.live_score_error: str | None = None
        self.lock = asyncio.Lock()

    async def start(self) -> None:
        init_db()
        await self.refresh_discovery()
        await self.refresh_live_scores()
        self.tasks = [
            asyncio.create_task(self._discovery_loop(), name="market-discovery"),
            asyncio.create_task(self._poll_loop(), name="market-poll"),
            asyncio.create_task(self._live_score_loop(), name="live-score-poll"),
        ]

    async def stop(self) -> None:
        for task in self.tasks:
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.provider.close()
        await self.live_score_provider.close()

    async def _discovery_loop(self) -> None:
        while True:
            try:
                await self.refresh_discovery()
                self.runtime_error = None
            except Exception as exc:
                self.runtime_error = str(exc)
            await asyncio.sleep(self.settings.discovery_interval_seconds)

    async def _poll_loop(self) -> None:
        while True:
            try:
                await self.refresh_quotes()
                self.runtime_error = None
            except Exception as exc:
                self.runtime_error = str(exc)
            await asyncio.sleep(self.settings.poll_interval_seconds)

    async def _live_score_loop(self) -> None:
        while True:
            try:
                await self.refresh_live_scores()
                self.live_score_error = None
            except Exception as exc:
                self.live_score_error = str(exc)
            await asyncio.sleep(self.settings.live_score_interval_seconds)

    async def refresh_discovery(self) -> None:
        quotes = await self.provider.discover_markets()
        if not quotes:
            return

        async with self.lock:
            for quote in quotes:
                await self._ingest_quote(quote_to_dict(quote))
            self.updated_at = datetime.now(UTC)
        await self.broadcast_matches()

    async def refresh_quotes(self) -> None:
        market_ids = list(self.markets.keys())[: self.settings.tracked_markets_limit]
        if not market_ids:
            await self.refresh_discovery()
            return

        quotes = await self.provider.fetch_market_books(market_ids)
        if not quotes:
            return

        async with self.lock:
            for quote in quotes:
                await self._ingest_quote(quote_to_dict(quote))
            self.updated_at = datetime.now(UTC)
        await self.broadcast_matches()

    async def refresh_live_scores(self) -> None:
        if not self.markets:
            return

        states = await self.live_score_provider.refresh(list(self.markets.values()))
        async with self.lock:
            for market_id, state in states.items():
                self.live_states[market_id] = state
                if market_id in self.markets:
                    snapshot = self.markets[market_id]
                    snapshot["live_score"] = state
                    await self._rebuild_recommendation(snapshot)
            for market_id, snapshot in self.markets.items():
                if "live_score" not in snapshot:
                    snapshot["live_score"] = self._default_live_score(snapshot)
            self.updated_at = datetime.now(UTC)
        await self.broadcast_matches()

    async def _ingest_quote(self, snapshot: dict[str, Any]) -> None:
        market_id = snapshot["market_id"]
        snapshot["live_score"] = self.live_states.get(market_id) or self._default_live_score(snapshot)
        self.markets[market_id] = snapshot
        await self._rebuild_recommendation(snapshot)
        self.history[market_id].append(self._to_timepoint(snapshot))

        for runner in snapshot["runners"]:
            runner["momentum"] = self._runner_momentum(market_id, runner["selection_id"])

    async def _rebuild_recommendation(self, snapshot: dict[str, Any]) -> None:
        market_id = snapshot["market_id"]
        existing_history = list(self.history[market_id])
        recommendation = build_recommendation(snapshot, existing_history)
        snapshot["signals"] = recommendation.pop("signals", [])
        self.recommendations[market_id] = recommendation
        self._persist_market(snapshot, recommendation)

    def _default_live_score(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        provider_status = self.live_score_provider.status()
        return empty_live_score(
            market=snapshot,
            provider=provider_status.get("active_provider", "unavailable"),
        )

    def _persist_market(self, snapshot: dict[str, Any], recommendation: dict[str, Any]) -> None:
        primary_runner = snapshot["runners"][0] if snapshot["runners"] else {}
        signal_signature = json.dumps(snapshot.get("signals", []), ensure_ascii=False, sort_keys=True)
        recommendation_signature = json.dumps(
            {
                "recommendation": recommendation["recommendation"],
                "selection_name": recommendation["selection_name"],
                "score": recommendation["score"],
                "risk_level": recommendation["risk_level"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )

        with session_scope() as session:
            match = session.get(MatchInfo, snapshot["market_id"])
            if not match:
                match = MatchInfo(
                    market_id=snapshot["market_id"],
                    event_id=snapshot["event_id"],
                    event_name=snapshot["event_name"],
                    market_name=snapshot["market_name"],
                    home_name=snapshot["home_name"],
                    away_name=snapshot["away_name"],
                    start_time=snapshot["start_time"],
                    provider=snapshot["provider"],
                    status=snapshot["status"],
                    in_play=snapshot["in_play"],
                    updated_at=snapshot["updated_at"],
                )
                session.add(match)
            else:
                match.status = snapshot["status"]
                match.in_play = snapshot["in_play"]
                match.provider = snapshot["provider"]
                match.updated_at = snapshot["updated_at"]

            tick = MarketTick(
                market_id=snapshot["market_id"],
                timestamp=snapshot["updated_at"],
                in_play=snapshot["in_play"],
                total_matched=snapshot.get("total_matched") or 0.0,
                primary_back_price=primary_runner.get("best_price") or primary_runner.get("price") or 0.0,
                primary_lay_price=primary_runner.get("worst_price") or primary_runner.get("price") or 0.0,
                primary_spread=primary_runner.get("market_width") or primary_runner.get("spread") or 0.0,
                snapshot_json=json.dumps(snapshot, ensure_ascii=False, default=_json_default),
            )
            session.add(tick)

            if self.signal_signatures.get(snapshot["market_id"]) != signal_signature:
                for signal in snapshot.get("signals", []):
                    session.add(
                        MarketSignal(
                            market_id=snapshot["market_id"],
                            signal_type=signal.get("type", "neutral"),
                            severity=signal.get("severity", "info"),
                            payload_json=json.dumps(signal, ensure_ascii=False),
                            created_at=snapshot["updated_at"],
                        )
                    )
                self.signal_signatures[snapshot["market_id"]] = signal_signature

            if self.recommendation_signatures.get(snapshot["market_id"]) != recommendation_signature:
                session.add(
                    Recommendation(
                        market_id=snapshot["market_id"],
                        recommendation=recommendation["recommendation"],
                        selection_name=recommendation["selection_name"],
                        score=recommendation["score"],
                        risk_level=recommendation["risk_level"],
                        payload_json=json.dumps(recommendation, ensure_ascii=False, default=_json_default),
                        created_at=recommendation["generated_at"],
                    )
                )
                self.recommendation_signatures[snapshot["market_id"]] = recommendation_signature

    def _runner_momentum(self, market_id: str, selection_id: int) -> float:
        history = list(self.history[market_id])[-12:]
        series = []
        for point in history:
            runner = next((item for item in point["runners"] if item["selection_id"] == selection_id), None)
            if runner and runner.get("price") is not None:
                series.append(runner["price"])
        if len(series) < 2:
            return 0.0
        return round(series[-1] - series[0], 4)

    def _to_timepoint(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        live_score = snapshot.get("live_score") or {}
        return {
            "timestamp": snapshot["updated_at"],
            "in_play": snapshot["in_play"],
            "total_matched": snapshot.get("total_matched"),
            "minute": live_score.get("minute"),
            "home_score": live_score.get("home_score"),
            "away_score": live_score.get("away_score"),
            "runners": [
                {
                    "selection_id": runner["selection_id"],
                    "name": runner["name"],
                    "price": runner.get("price"),
                    "mid_price": runner.get("mid_price"),
                    "probability": runner.get("implied_probability"),
                    "market_width": runner.get("market_width") or runner.get("spread"),
                    "bookmaker_count": runner.get("bookmaker_count"),
                    "outcome_key": runner.get("outcome_key"),
                }
                for runner in snapshot["runners"]
            ],
        }

    async def register(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.clients.add(websocket)
        await websocket.send_json(
            {
                "type": "matches",
                "matches": self.get_matches(),
                "system": self.get_system_status(),
            }
        )

    async def unregister(self, websocket: WebSocket) -> None:
        self.clients.discard(websocket)

    async def broadcast_matches(self) -> None:
        if not self.clients:
            return

        payload = {
            "type": "matches",
            "matches": self.get_matches(),
            "system": self.get_system_status(),
        }
        stale_clients: list[WebSocket] = []
        for client in self.clients:
            try:
                await client.send_json(payload)
            except Exception:
                stale_clients.append(client)
        for client in stale_clients:
            self.clients.discard(client)

    def get_matches(self) -> list[dict[str, Any]]:
        rows = []
        for snapshot in self.markets.values():
            recommendation = self.recommendations.get(snapshot["market_id"], {})
            primary_runner = snapshot["runners"][0] if snapshot["runners"] else {}
            live_score = snapshot.get("live_score") or self._default_live_score(snapshot)
            extra = snapshot.get("extra") or {}
            rows.append(
                {
                    "market_id": snapshot["market_id"],
                    "event_id": snapshot["event_id"],
                    "event_name": snapshot["event_name"],
                    "home_name": snapshot["home_name"],
                    "away_name": snapshot["away_name"],
                    "market_name": snapshot["market_name"],
                    "provider": snapshot["provider"],
                    "start_time": snapshot["start_time"],
                    "in_play": snapshot["in_play"],
                    "status": snapshot["status"],
                    "bookmaker_count": extra.get("bookmaker_count"),
                    "overround": extra.get("overround"),
                    "spread": primary_runner.get("market_width") or primary_runner.get("spread"),
                    "signal": recommendation.get("signal", "neutral"),
                    "confidence": recommendation.get("score", 0.0),
                    "updated_at": snapshot["updated_at"],
                    "live_score": live_score,
                }
            )
        rows.sort(key=lambda item: (not item["in_play"], item["start_time"]))
        return rows

    def get_snapshot(self, market_id: str) -> dict[str, Any] | None:
        snapshot = self.markets.get(market_id)
        if not snapshot:
            return None

        payload = dict(snapshot)
        payload["recommendation"] = self.recommendations.get(market_id)
        payload["live_score"] = snapshot.get("live_score") or self._default_live_score(snapshot)
        payload["extra"] = {
            **(snapshot.get("extra") or {}),
            "system": self.get_system_status(),
        }
        return payload

    def get_timeseries(self, market_id: str, limit: int = 120) -> list[dict[str, Any]]:
        history = list(self.history.get(market_id, []))
        return history[-limit:]

    def get_recommendation(self, market_id: str) -> dict[str, Any] | None:
        return self.recommendations.get(market_id)

    def get_system_status(self) -> dict[str, Any]:
        provider_status = self.provider.status()
        live_score_status = self.live_score_provider.status()
        return {
            "app_name": self.settings.app_name,
            "configured_mode": self.settings.normalized_data_mode,
            "active_provider": provider_status["active_provider"],
            "fallback_active": provider_status.get("fallback_active", False),
            "data_ready": provider_status.get("ready", False),
            "api_football_ready": self.settings.api_football_ready,
            "last_error": provider_status.get("last_error") or self.runtime_error,
            "live_score_configured_mode": self.settings.normalized_live_score_mode,
            "active_live_score_provider": live_score_status.get("active_provider", "unavailable"),
            "live_score_fallback_active": live_score_status.get("fallback_active", False),
            "live_score_ready": live_score_status.get("ready", False),
            "live_score_last_error": live_score_status.get("last_error") or self.live_score_error,
            "updated_at": self.updated_at,
        }


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value
