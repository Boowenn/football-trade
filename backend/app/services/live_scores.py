from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from ..config import Settings

LIVE_STATUS_CODES = {"1H", "HT", "2H", "ET", "P", "BT", "INT", "LIVE"}


@dataclass
class ScriptedEvent:
    minute: int
    team_side: str
    event_type: str
    detail: str
    player: str
    assist: str = ""


class LiveScoreProvider:
    provider_name = "unavailable"

    async def refresh(self, markets: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        return {}

    async def close(self) -> None:
        return None

    def status(self) -> dict[str, Any]:
        return {
            "active_provider": self.provider_name,
            "fallback_active": False,
            "last_error": None,
            "ready": False,
        }


class UnavailableLiveScoreProvider(LiveScoreProvider):
    def __init__(self, provider_name: str, message: str) -> None:
        self.provider_name = provider_name
        self.message = message

    async def refresh(self, markets: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        states: dict[str, dict[str, Any]] = {}
        for market in markets:
            states[market["market_id"]] = empty_live_score(
                market=market,
                provider=self.provider_name,
                message=self.message,
            )
        return states

    def status(self) -> dict[str, Any]:
        return {
            "active_provider": self.provider_name,
            "fallback_active": False,
            "last_error": self.message,
            "ready": False,
        }


class NullLiveScoreProvider(LiveScoreProvider):
    provider_name = "off"


class DemoLiveScoreProvider(LiveScoreProvider):
    provider_name = "demo-live"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.script_cache: dict[str, list[ScriptedEvent]] = {}

    async def refresh(self, markets: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        now = datetime.now(UTC)
        states: dict[str, dict[str, Any]] = {}

        for market in markets:
            market_id = market["market_id"]
            script = self.script_cache.setdefault(market_id, self._build_script(market))
            minute, status_short, status_long = _minute_and_status(market["start_time"], now)
            visible_events = [event for event in script if minute is not None and event.minute <= minute]
            teams = {
                "home": market.get("home_name") or "Home",
                "away": market.get("away_name") or "Away",
            }
            states[market_id] = _build_live_state(
                market=market,
                provider=self.provider_name,
                status_short=status_short,
                status_long=status_long,
                minute=minute,
                events=_serialise_scripted_events(visible_events, teams),
                updated_at=now,
                matched=True,
            )

        return states

    def status(self) -> dict[str, Any]:
        return {
            "active_provider": self.provider_name,
            "fallback_active": False,
            "last_error": None,
            "ready": True,
        }

    def _build_script(self, market: dict[str, Any]) -> list[ScriptedEvent]:
        seed = random.Random(market["market_id"])
        home_label = market.get("home_name") or "Home"
        away_label = market.get("away_name") or "Away"

        events: list[ScriptedEvent] = []
        for minute in sorted({seed.randint(8, 84) for _ in range(seed.randint(3, 7))}):
            event_type = seed.choice(["Goal", "Card", "subst"])
            team_side = seed.choice(["home", "away"])
            player = f"{home_label if team_side == 'home' else away_label} #{seed.randint(7, 15)}"
            if event_type == "Goal":
                detail = seed.choice(["Normal Goal", "Penalty"])
                assist = f"{home_label if team_side == 'home' else away_label} #{seed.randint(2, 10)}"
            elif event_type == "Card":
                detail = seed.choice(["Yellow Card", "Yellow Card", "Red Card"])
                assist = ""
            else:
                detail = "Substitution"
                assist = ""
            events.append(
                ScriptedEvent(
                    minute=minute,
                    team_side=team_side,
                    event_type=event_type,
                    detail=detail,
                    player=player,
                    assist=assist,
                )
            )
        events.sort(key=lambda item: item.minute)
        return events


class ApiFootballLiveScoreProvider(LiveScoreProvider):
    provider_name = "api_football"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = httpx.AsyncClient(
            base_url=self.settings.api_football_base_url,
            timeout=20,
            headers={"x-apisports-key": self.settings.api_football_key},
        )
        self.last_error: str | None = None
        self.event_cache: dict[str, dict[str, Any]] = {}

    async def refresh(self, markets: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        if not markets:
            return {}

        try:
            market_to_fixture = {
                market["market_id"]: _resolve_fixture_id(market)
                for market in markets
                if _resolve_fixture_id(market)
            }
            fixture_ids = sorted({fixture_id for fixture_id in market_to_fixture.values() if fixture_id})
            if not fixture_ids:
                return {}

            payload = await self._get(
                "/fixtures",
                {
                    "ids": "-".join(fixture_ids),
                    "timezone": self.settings.api_football_timezone,
                },
            )
            fixtures = payload.get("response", [])
            fixture_map = {
                str(item.get("fixture", {}).get("id")): self._parse_fixture(item)
                for item in fixtures
                if item.get("fixture", {}).get("id") is not None
            }

            now = datetime.now(UTC)
            live_fixture_ids = [
                fixture_id
                for fixture_id, state in fixture_map.items()
                if state["status_short"] in LIVE_STATUS_CODES
            ][: self.settings.live_score_event_matches_limit]

            for fixture_id in live_fixture_ids:
                if self._event_cache_expired(fixture_id, now):
                    base_state = fixture_map[fixture_id]
                    self.event_cache[fixture_id] = await self._fetch_events(
                        fixture_id=fixture_id,
                        home_name=base_state["home_name"],
                        away_name=base_state["away_name"],
                        now=now,
                    )

            result: dict[str, dict[str, Any]] = {}
            for market in markets:
                market_id = market["market_id"]
                fixture_id = market_to_fixture.get(market_id)
                if not fixture_id:
                    result[market_id] = empty_live_score(
                        market=market,
                        provider=self.provider_name,
                        message="当前比赛还没有对应的实时比分数据。",
                    )
                    continue

                base_state = fixture_map.get(fixture_id)
                if not base_state:
                    result[market_id] = empty_live_score(
                        market=market,
                        provider=self.provider_name,
                        message="实时比分接口当前没有返回这场比赛。",
                    )
                    continue

                event_bundle = self.event_cache.get(fixture_id, {"events": []})
                result[market_id] = _build_live_state(
                    market=market,
                    provider=self.provider_name,
                    status_short=base_state["status_short"],
                    status_long=base_state["status_long"],
                    minute=base_state["minute"],
                    stoppage=base_state["stoppage"],
                    fixture_id=fixture_id,
                    home_name=base_state["home_name"],
                    away_name=base_state["away_name"],
                    home_score=base_state["home_score"],
                    away_score=base_state["away_score"],
                    events=event_bundle.get("events", []),
                    updated_at=now,
                    matched=True,
                )

            self.last_error = None
            return result
        except Exception as exc:
            self.last_error = str(exc)
            raise

    async def close(self) -> None:
        await self.client.aclose()

    def status(self) -> dict[str, Any]:
        return {
            "active_provider": self.provider_name,
            "fallback_active": False,
            "last_error": self.last_error,
            "ready": self.settings.api_football_ready,
        }

    async def _fetch_events(
        self,
        fixture_id: str,
        home_name: str,
        away_name: str,
        now: datetime,
    ) -> dict[str, Any]:
        payload = await self._get("/fixtures/events", {"fixture": fixture_id})
        events = []
        for item in payload.get("response", []):
            elapsed = item.get("time", {}).get("elapsed")
            extra = item.get("time", {}).get("extra")
            team_name = item.get("team", {}).get("name", "")
            team_side = _resolve_team_side(team_name, home_name, away_name)
            events.append(
                {
                    "minute": elapsed,
                    "stoppage": extra,
                    "minute_label": _format_minute_label(elapsed, extra),
                    "team": team_name,
                    "team_side": team_side,
                    "type": item.get("type", ""),
                    "detail": item.get("detail", ""),
                    "player": item.get("player", {}).get("name", ""),
                    "assist": item.get("assist", {}).get("name", ""),
                }
            )

        return {
            "updated_at": now,
            "events": events[-self.settings.live_score_event_history_limit :],
        }

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        response = await self.client.get(path, params=params)
        response.raise_for_status()
        payload = response.json()
        errors = payload.get("errors") or {}
        if isinstance(errors, dict) and any(errors.values()):
            raise RuntimeError(f"API-Football error: {errors}")
        return payload

    def _parse_fixture(self, item: dict[str, Any]) -> dict[str, Any]:
        fixture = item.get("fixture", {})
        status = fixture.get("status", {})
        teams = item.get("teams", {})
        goals = item.get("goals", {})
        return {
            "fixture_id": str(fixture.get("id")),
            "status_short": status.get("short", "NS"),
            "status_long": status.get("long", "未开始"),
            "minute": status.get("elapsed"),
            "stoppage": status.get("extra"),
            "home_name": teams.get("home", {}).get("name", ""),
            "away_name": teams.get("away", {}).get("name", ""),
            "home_score": goals.get("home"),
            "away_score": goals.get("away"),
        }

    def _event_cache_expired(self, fixture_id: str, now: datetime) -> bool:
        cached = self.event_cache.get(fixture_id)
        if not cached:
            return True
        updated_at = cached.get("updated_at")
        if not isinstance(updated_at, datetime):
            return True
        return (now - updated_at).total_seconds() >= self.settings.live_score_event_interval_seconds


class AutoLiveScoreProvider(LiveScoreProvider):
    provider_name = "auto-live"

    def __init__(self, primary: LiveScoreProvider | None, fallback: LiveScoreProvider) -> None:
        self.primary = primary
        self.fallback = fallback
        self.using_fallback = primary is None
        self.last_error: str | None = None

    async def refresh(self, markets: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        if self.primary and not self.using_fallback:
            try:
                return await self.primary.refresh(markets)
            except Exception as exc:
                self.last_error = str(exc)
                self.using_fallback = True
        return await self.fallback.refresh(markets)

    async def close(self) -> None:
        if self.primary:
            await self.primary.close()
        await self.fallback.close()

    def status(self) -> dict[str, Any]:
        if self.using_fallback:
            fallback_status = self.fallback.status()
            return {
                "active_provider": fallback_status["active_provider"],
                "fallback_active": True,
                "last_error": self.last_error,
                "ready": True,
            }

        primary_status = self.primary.status() if self.primary else self.fallback.status()
        return {
            "active_provider": primary_status.get("active_provider", "demo-live"),
            "fallback_active": False,
            "last_error": self.last_error,
            "ready": primary_status.get("ready", False),
        }


def build_live_score_provider(settings: Settings) -> LiveScoreProvider:
    mode = settings.normalized_live_score_mode
    demo = DemoLiveScoreProvider(settings)

    if mode == "off":
        return NullLiveScoreProvider()
    if mode == "demo":
        return demo
    if mode == "api_football":
        if settings.api_football_ready:
            return ApiFootballLiveScoreProvider(settings)
        return UnavailableLiveScoreProvider(
            provider_name="api_football",
            message="当前是免费真实比分模式，但还没有配置 API_FOOTBALL_KEY。",
        )
    if mode == "auto":
        primary = ApiFootballLiveScoreProvider(settings) if settings.api_football_ready else None
        return AutoLiveScoreProvider(primary=primary, fallback=demo)
    return demo


def empty_live_score(
    market: dict[str, Any] | None = None,
    provider: str = "unavailable",
    message: str = "当前没有实时比分数据。",
) -> dict[str, Any]:
    return {
        "provider": provider,
        "matched": False,
        "fixture_id": None,
        "status_short": "NA",
        "status_long": message,
        "minute": None,
        "stoppage": None,
        "minute_label": "--",
        "home_name": (market or {}).get("home_name", ""),
        "away_name": (market or {}).get("away_name", ""),
        "home_score": None,
        "away_score": None,
        "home_yellow": 0,
        "away_yellow": 0,
        "home_red": 0,
        "away_red": 0,
        "events": [],
        "updated_at": datetime.now(UTC),
    }


def _build_live_state(
    market: dict[str, Any],
    provider: str,
    status_short: str,
    status_long: str,
    minute: int | None,
    events: list[dict[str, Any]],
    updated_at: datetime,
    matched: bool,
    stoppage: int | None = None,
    fixture_id: str | None = None,
    home_name: str | None = None,
    away_name: str | None = None,
    home_score: int | None = None,
    away_score: int | None = None,
) -> dict[str, Any]:
    home = home_name or market.get("home_name", "")
    away = away_name or market.get("away_name", "")

    home_yellow = 0
    away_yellow = 0
    home_red = 0
    away_red = 0
    scored_home = 0
    scored_away = 0

    for event in events:
        event_type = str(event.get("type", "")).lower()
        detail = str(event.get("detail", "")).lower()
        side = event.get("team_side")

        if event_type == "card":
            if "yellow" in detail and "red" not in detail:
                if side == "home":
                    home_yellow += 1
                elif side == "away":
                    away_yellow += 1
            elif "red" in detail:
                if side == "home":
                    home_red += 1
                elif side == "away":
                    away_red += 1

        if event_type == "goal":
            if side == "home":
                scored_home += 1
            elif side == "away":
                scored_away += 1

    return {
        "provider": provider,
        "matched": matched,
        "fixture_id": fixture_id,
        "status_short": status_short,
        "status_long": status_long,
        "minute": minute,
        "stoppage": stoppage,
        "minute_label": _format_status_label(status_short, minute, stoppage),
        "home_name": home,
        "away_name": away,
        "home_score": home_score if home_score is not None else scored_home,
        "away_score": away_score if away_score is not None else scored_away,
        "home_yellow": home_yellow,
        "away_yellow": away_yellow,
        "home_red": home_red,
        "away_red": away_red,
        "events": events[-10:],
        "updated_at": updated_at,
    }


def _serialise_scripted_events(events: list[ScriptedEvent], teams: dict[str, str]) -> list[dict[str, Any]]:
    serialised = []
    for event in events:
        serialised.append(
            {
                "minute": event.minute,
                "stoppage": None,
                "minute_label": _format_minute_label(event.minute, None),
                "team": teams[event.team_side],
                "team_side": event.team_side,
                "type": event.event_type,
                "detail": event.detail,
                "player": event.player,
                "assist": event.assist,
            }
        )
    return serialised


def _minute_and_status(start_time: datetime, now: datetime) -> tuple[int | None, str, str]:
    elapsed = int((now - start_time).total_seconds() // 60)
    if elapsed < 0:
        return None, "NS", "未开始"
    if elapsed < 45:
        return elapsed + 1, "1H", "上半场"
    if elapsed < 60:
        return 45, "HT", "中场休息"
    if elapsed < 105:
        return min(90, elapsed - 14), "2H", "下半场"
    return 90, "FT", "已结束"


def _resolve_fixture_id(market: dict[str, Any]) -> str | None:
    extra = market.get("extra") or {}
    fixture_id = extra.get("fixture_id")
    if fixture_id:
        return str(fixture_id)
    event_id = market.get("event_id")
    if event_id:
        return str(event_id)
    market_id = str(market.get("market_id", ""))
    if market_id.startswith("fixture-"):
        return market_id.removeprefix("fixture-")
    return None


def _resolve_team_side(team_name: str, home_name: str, away_name: str) -> str:
    normalized_team = team_name.strip().lower()
    if normalized_team == home_name.strip().lower():
        return "home"
    if normalized_team == away_name.strip().lower():
        return "away"
    if home_name.strip().lower() in normalized_team:
        return "home"
    if away_name.strip().lower() in normalized_team:
        return "away"
    return "neutral"


def _format_minute_label(minute: int | None, stoppage: int | None) -> str:
    if minute is None:
        return "--"
    if stoppage:
        return f"{minute}+{stoppage}'"
    return f"{minute}'"


def _format_status_label(status_short: str, minute: int | None, stoppage: int | None) -> str:
    if status_short in LIVE_STATUS_CODES and minute is not None:
        return _format_minute_label(minute, stoppage)
    mapping = {
        "NS": "未开始",
        "HT": "中场",
        "FT": "完场",
        "AET": "加时完场",
        "PEN": "点球完场",
        "PST": "延期",
        "CANC": "取消",
        "SUSP": "暂停",
    }
    return mapping.get(status_short, status_short or "--")
