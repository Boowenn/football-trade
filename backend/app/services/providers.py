from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from statistics import mean
from typing import Any
from urllib.parse import urljoin
from zoneinfo import ZoneInfo
from zoneinfo import ZoneInfoNotFoundError

import httpx
from bs4 import BeautifulSoup

from ..config import Settings

ACTIVE_STATUSES = {"NS", "TBD", "1H", "HT", "2H", "ET", "P", "BT", "INT", "LIVE", "SUSP"}
LIVE_STATUSES = {"1H", "HT", "2H", "ET", "P", "BT", "INT", "LIVE"}
FINISHED_STATUSES = {"FT", "AET", "PEN", "AWD", "CANC", "ABD", "WO"}


@dataclass
class RunnerQuote:
    selection_id: int
    name: str
    price: float | None
    implied_probability: float | None
    bookmaker_count: int
    best_price: float | None
    worst_price: float | None
    market_width: float
    bookmakers: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class MarketQuote:
    market_id: str
    event_id: str
    event_name: str
    market_name: str
    home_name: str
    away_name: str
    provider: str
    start_time: datetime
    status: str
    in_play: bool
    total_matched: float | None
    updated_at: datetime
    runners: list[RunnerQuote]
    extra: dict[str, Any] = field(default_factory=dict)


class MarketProvider:
    provider_name = "unknown"

    async def discover_markets(self) -> list[MarketQuote]:
        raise NotImplementedError

    async def fetch_market_books(self, market_ids: list[str]) -> list[MarketQuote]:
        raise NotImplementedError

    async def close(self) -> None:
        return None

    def status(self) -> dict[str, Any]:
        return {
            "active_provider": self.provider_name,
            "fallback_active": False,
            "last_error": None,
            "ready": False,
        }


class UnavailableMarketProvider(MarketProvider):
    def __init__(self, provider_name: str, message: str) -> None:
        self.provider_name = provider_name
        self.message = message

    async def discover_markets(self) -> list[MarketQuote]:
        return []

    async def fetch_market_books(self, market_ids: list[str]) -> list[MarketQuote]:
        return []

    def status(self) -> dict[str, Any]:
        return {
            "active_provider": self.provider_name,
            "fallback_active": False,
            "last_error": self.message,
            "ready": False,
        }


class DemoMarketProvider(MarketProvider):
    provider_name = "demo"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.random = random.Random(7)
        self._markets: dict[str, dict[str, Any]] = {}
        self._seed_markets()

    def _seed_markets(self) -> None:
        now = datetime.now(UTC).replace(second=0, microsecond=0)
        fixtures = [
            ("demo-1001", "Arsenal vs Liverpool", "Arsenal", "Liverpool", now - timedelta(minutes=22)),
            ("demo-1002", "Real Madrid vs Barcelona", "Real Madrid", "Barcelona", now - timedelta(minutes=9)),
            ("demo-1003", "Inter vs Juventus", "Inter", "Juventus", now + timedelta(minutes=16)),
            ("demo-1004", "Bayern Munich vs Dortmund", "Bayern Munich", "Dortmund", now + timedelta(minutes=43)),
            ("demo-1005", "PSG vs Marseille", "PSG", "Marseille", now + timedelta(hours=1, minutes=10)),
            ("demo-1006", "Manchester City vs Chelsea", "Manchester City", "Chelsea", now + timedelta(hours=2)),
            ("demo-1007", "Atletico Madrid vs Sevilla", "Atletico Madrid", "Sevilla", now + timedelta(hours=3)),
            ("demo-1008", "Milan vs Napoli", "Milan", "Napoli", now + timedelta(hours=4)),
        ]

        for index, (market_id, event_name, home, away, start_time) in enumerate(fixtures, start=1):
            self._markets[market_id] = {
                "market_id": market_id,
                "event_id": f"fixture-{index}",
                "event_name": event_name,
                "home_name": home,
                "away_name": away,
                "start_time": start_time,
                "status": "OPEN",
                "outcomes": {
                    "home": 1.7 + self.random.random() * 1.2,
                    "draw": 2.9 + self.random.random() * 1.0,
                    "away": 2.0 + self.random.random() * 1.8,
                },
            }

    def _update_market(self, market: dict[str, Any]) -> MarketQuote:
        now = datetime.now(UTC)
        in_play = market["start_time"] <= now <= market["start_time"] + timedelta(hours=2)
        if now > market["start_time"] + timedelta(hours=2, minutes=15):
            market["status"] = "FT"

        for outcome in ("home", "draw", "away"):
            drift = self.random.uniform(-0.05, 0.05 if in_play else 0.03)
            market["outcomes"][outcome] = round(max(1.2, min(12.0, market["outcomes"][outcome] + drift)), 3)

        rows = []
        bookmaker_names = ["Bet365", "William Hill", "Pinnacle", "Unibet"]
        for name in bookmaker_names:
            rows.append(
                {
                    "name": name,
                    "home": round(market["outcomes"]["home"] + self.random.uniform(-0.06, 0.06), 2),
                    "draw": round(market["outcomes"]["draw"] + self.random.uniform(-0.08, 0.08), 2),
                    "away": round(market["outcomes"]["away"] + self.random.uniform(-0.07, 0.07), 2),
                }
            )

        runners = [
            _runner_from_bookmakers(1, market["home_name"], "home", rows),
            _runner_from_bookmakers(2, "Draw", "draw", rows),
            _runner_from_bookmakers(3, market["away_name"], "away", rows),
        ]
        overround = round(sum((1 / runner.price) for runner in runners if runner.price), 4)

        return MarketQuote(
            market_id=market["market_id"],
            event_id=market["event_id"],
            event_name=market["event_name"],
            market_name="Match Winner",
            home_name=market["home_name"],
            away_name=market["away_name"],
            provider=self.provider_name,
            start_time=market["start_time"],
            status=market["status"],
            in_play=in_play,
            total_matched=float(len(rows)),
            updated_at=now,
            runners=runners,
            extra={
                "fixture_id": market["event_id"],
                "bookmaker_count": len(rows),
                "bookmakers": rows,
                "overround": overround,
                "market_type": "胜平负",
                "odds_scope": "demo",
            },
        )

    async def discover_markets(self) -> list[MarketQuote]:
        await asyncio.sleep(0)
        quotes = [self._update_market(item) for item in self._markets.values()]
        quotes.sort(key=lambda item: (item.status == "FT", not item.in_play, item.start_time))
        active_quotes = [item for item in quotes if item.status != "FT"]
        if active_quotes:
            return active_quotes[: self.settings.tracked_markets_limit]
        return quotes[: self.settings.tracked_markets_limit]

    async def fetch_market_books(self, market_ids: list[str]) -> list[MarketQuote]:
        await asyncio.sleep(0)
        quotes = [self._update_market(self._markets[market_id]) for market_id in market_ids if market_id in self._markets]
        quotes.sort(key=lambda item: (not item.in_play, item.start_time))
        return quotes

    def status(self) -> dict[str, Any]:
        return {
            "active_provider": self.provider_name,
            "fallback_active": False,
            "last_error": None,
            "ready": True,
        }


class BetExplorerScrapeProvider(MarketProvider):
    provider_name = "betexplorer_scrape"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = httpx.AsyncClient(
            base_url="https://www.betexplorer.com",
            timeout=20,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/135.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            },
            follow_redirects=True,
        )
        self.last_error: str | None = None
        try:
            self.local_timezone = ZoneInfo(self.settings.api_football_timezone)
        except ZoneInfoNotFoundError:
            self.local_timezone = timezone(timedelta(hours=9))

    async def discover_markets(self) -> list[MarketQuote]:
        try:
            quotes = await self._fetch_market_quotes()
            self.last_error = None
            return quotes
        except Exception as exc:
            self.last_error = str(exc)
            raise

    async def fetch_market_books(self, market_ids: list[str]) -> list[MarketQuote]:
        try:
            quotes = await self._fetch_market_quotes()
            if not market_ids:
                self.last_error = None
                return quotes

            wanted = set(market_ids)
            filtered = [quote for quote in quotes if quote.market_id in wanted]
            self.last_error = None
            return filtered or quotes
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
            "ready": True,
        }

    async def _fetch_market_quotes(self) -> list[MarketQuote]:
        quotes = await self._fetch_listing_quotes("/football/results/")
        if not quotes:
            quotes = await self._fetch_listing_quotes("/football/")
        if not quotes:
            return []
        return await self._enrich_quotes_with_comparison_markets(quotes)

    async def _fetch_listing_quotes(self, path: str) -> list[MarketQuote]:
        response = await self.client.get(path)
        response.raise_for_status()
        return self._parse_listing_page(response.text, path)

    async def _enrich_quotes_with_comparison_markets(self, quotes: list[MarketQuote]) -> list[MarketQuote]:
        tasks = [self._fetch_comparison_markets(quote.event_id) for quote in quotes]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        enriched: list[MarketQuote] = []
        for quote, result in zip(quotes, results, strict=False):
            if isinstance(result, Exception):
                enriched.append(quote)
                continue
            enriched.append(self._merge_comparison_markets(quote, result))
        return enriched

    async def _fetch_comparison_markets(self, event_id: str) -> dict[str, Any]:
        tasks = {
            "match_winner": self._fetch_best_odds(event_id, "1x2"),
            "over_under": self._fetch_best_odds(event_id, "ou"),
            "asian_handicap": self._fetch_best_odds(event_id, "ah"),
        }
        names = list(tasks)
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)

        markets: dict[str, Any] = {}
        for name, result in zip(names, results, strict=False):
            if isinstance(result, Exception) or not result:
                continue
            markets[name] = result
        return markets

    async def _fetch_best_odds(self, event_id: str, bet_type: str) -> dict[str, Any] | None:
        response = await self.client.get(f"/match-odds/{event_id}/0/{bet_type}/bestOdds/", params={"lang": "en"})
        response.raise_for_status()
        payload = response.json()
        html = payload.get("odds")
        if not html:
            return None
        return self._parse_best_odds_html(str(html), bet_type)

    def _parse_best_odds_html(self, html: str, bet_type: str) -> dict[str, Any] | None:
        soup = BeautifulSoup(html, "lxml")
        if bet_type == "1x2":
            table = soup.select_one("table.table-main[data-handicap]") or soup.select_one("table.table-main")
            if table is None:
                return None
            rows = self._parse_1x2_rows(table)
            if not rows:
                return None
            return {
                "market_type": "match_winner",
                "active_line": 0.0,
                "available_lines": [0.0],
                "line_count": 1,
                "bookmaker_count": len(rows),
                "rows": rows,
                "summary": _aggregate_match_winner_rows(rows),
            }

        available_lines = _extract_available_lines(soup)
        active_line = self._extract_active_line(soup, available_lines)
        active_table = None
        if active_line is not None:
            active_table = soup.select_one(f'table[data-handicap="{active_line:.2f}"]')
        if active_table is None and available_lines:
            active_table = soup.select_one(f'table[data-handicap="{available_lines[0]:.2f}"]')
        if active_table is None:
            active_table = soup.select_one("table.table-main[data-handicap]")
        if active_table is None:
            return None

        if bet_type == "ou":
            rows = self._parse_two_way_rows(active_table, "over", "under")
            if not rows:
                return None
            primary_line = active_line if active_line is not None else _safe_float(active_table.get("data-handicap"))
            return {
                "market_type": "over_under",
                "active_line": primary_line,
                "available_lines": available_lines,
                "line_count": len(available_lines),
                "bookmaker_count": len(rows),
                "rows": rows,
                "summary": _aggregate_two_way_rows(rows, "over", "under"),
            }

        if bet_type == "ah":
            rows = self._parse_two_way_rows(active_table, "home", "away")
            if not rows:
                return None
            primary_line = active_line if active_line is not None else _safe_float(active_table.get("data-handicap"))
            summary = _aggregate_two_way_rows(rows, "home", "away")
            if primary_line is not None:
                summary["line_favored_side"] = _handicap_favored_side(primary_line)
                summary["line_strength"] = round(abs(primary_line), 2)
            else:
                summary["line_favored_side"] = "balanced"
                summary["line_strength"] = 0.0
            return {
                "market_type": "asian_handicap",
                "active_line": primary_line,
                "available_lines": available_lines,
                "line_count": len(available_lines),
                "bookmaker_count": len(rows),
                "rows": rows,
                "summary": summary,
            }

        return None

    def _extract_active_line(self, soup: BeautifulSoup, available_lines: list[float]) -> float | None:
        active = soup.select_one(".bestOddsComparison .oddsComparison__activeSubLi")
        active_line = _safe_float(active.get_text(" ", strip=True)) if active else None
        if active_line is not None:
            return active_line
        return available_lines[0] if available_lines else None

    def _parse_1x2_rows(self, table: Any) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for row in table.select("tr[data-bid]"):
            cells = row.find_all("td", recursive=False)
            if len(cells) < 7:
                continue
            name = _extract_betexplorer_bookmaker_name(cells[0])
            if not _is_supported_scrape_bookmaker(name):
                continue

            home = _safe_float(cells[4].get("data-odd"))
            draw = _safe_float(cells[5].get("data-odd"))
            away = _safe_float(cells[6].get("data-odd"))
            if home is None or draw is None or away is None:
                continue

            rows.append(
                {
                    "name": name or "Bookmaker",
                    "home": round(home, 3),
                    "draw": round(draw, 3),
                    "away": round(away, 3),
                }
            )
        return rows

    def _parse_two_way_rows(self, table: Any, left_key: str, right_key: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        table_line = _safe_float(table.get("data-handicap"))
        for row in table.select("tr[data-bid]"):
            cells = row.find_all("td", recursive=False)
            if len(cells) < 7:
                continue
            name = _extract_betexplorer_bookmaker_name(cells[0])
            if not _is_supported_scrape_bookmaker(name):
                continue

            line = _safe_float(cells[4].get_text(" ", strip=True))
            left_price = _safe_float(cells[5].get("data-odd"))
            right_price = _safe_float(cells[6].get("data-odd"))
            if left_price is None or right_price is None:
                continue

            rows.append(
                {
                    "name": name or "Bookmaker",
                    "line": round(line if line is not None else table_line or 0.0, 2),
                    left_key: round(left_price, 3),
                    right_key: round(right_price, 3),
                }
            )
        return rows

    def _merge_comparison_markets(self, quote: MarketQuote, markets: dict[str, Any]) -> MarketQuote:
        match_winner = markets.get("match_winner") or {}
        bookmakers = list(match_winner.get("rows") or quote.extra.get("bookmakers") or [])
        runners = quote.runners

        if bookmakers:
            runners = [
                _runner_from_bookmakers(1, quote.home_name, "home", bookmakers),
                _runner_from_bookmakers(2, "Draw", "draw", bookmakers),
                _runner_from_bookmakers(3, quote.away_name, "away", bookmakers),
            ]

        overround = round(sum((1 / runner.price) for runner in runners if runner.price), 4)
        merged_extra = {
            **quote.extra,
            "bookmaker_count": len(bookmakers) or int(quote.extra.get("bookmaker_count") or 0),
            "bookmakers": bookmakers[:12],
            "overround": overround,
            "favorite_name": _favorite_name(runners),
            "related_markets": {
                "match_winner": {
                    "market_type": "match_winner",
                    "active_line": 0.0,
                    "available_lines": [0.0],
                    "line_count": 1,
                    "bookmaker_count": len(bookmakers),
                    "rows": bookmakers[:12],
                    "summary": _aggregate_match_winner_rows(bookmakers) if bookmakers else {},
                },
                **{name: value for name, value in markets.items() if name != "match_winner"},
            },
        }

        return MarketQuote(
            market_id=quote.market_id,
            event_id=quote.event_id,
            event_name=quote.event_name,
            market_name=quote.market_name,
            home_name=quote.home_name,
            away_name=quote.away_name,
            provider=quote.provider,
            start_time=quote.start_time,
            status=quote.status,
            in_play=quote.in_play,
            total_matched=float(len(bookmakers)) if bookmakers else quote.total_matched,
            updated_at=quote.updated_at,
            runners=runners,
            extra=merged_extra,
        )

    def _parse_listing_page(self, html: str, source_path: str) -> list[MarketQuote]:
        soup = BeautifulSoup(html, "lxml")
        table = soup.find("table", class_="table-main")
        if table is None:
            raise RuntimeError(f"BetExplorer listing table was not found for {source_path}.")

        now = datetime.now(UTC)
        page_now_local, page_timezone = _extract_betexplorer_page_clock(soup, now, self.local_timezone)
        current_tournament = ""
        quotes: list[MarketQuote] = []

        for row in table.find_all("tr"):
            row_classes = set(row.get("class") or [])
            if "js-tournament" in row_classes:
                tournament_link = row.find("a", class_="table-main__tournament")
                if tournament_link:
                    current_tournament = " ".join(tournament_link.get_text(" ", strip=True).split())
                continue

            cells = row.find_all("td")
            if len(cells) < 5:
                continue
            if not all(cell.find("button") for cell in cells[2:5]):
                continue

            link = cells[0].find("a", href=True)
            if link is None:
                continue

            match_name = " ".join(link.get_text(" ", strip=True).split())
            home_name, away_name = _split_match_name(match_name)
            match_href = str(link["href"])
            match_id = match_href.rstrip("/").split("/")[-1]
            start_local = _parse_betexplorer_local_datetime(row.get("data-dt"))
            if start_local is None:
                continue

            start_time = start_local.replace(tzinfo=page_timezone).astimezone(UTC)
            status, in_play = _infer_scrape_status(start_local, page_now_local)

            home_runner = _runner_from_scrape_cell(1, home_name, "home", cells[2])
            draw_runner = _runner_from_scrape_cell(2, "Draw", "draw", cells[3])
            away_runner = _runner_from_scrape_cell(3, away_name, "away", cells[4])
            runners = [home_runner, draw_runner, away_runner]

            if not all(runner.price for runner in runners):
                continue

            overround = round(sum((1 / runner.price) for runner in runners if runner.price), 4)
            summary_row = {
                "name": "BetExplorer",
                "home": round(home_runner.price or 0.0, 2),
                "draw": round(draw_runner.price or 0.0, 2),
                "away": round(away_runner.price or 0.0, 2),
            }

            quotes.append(
                MarketQuote(
                    market_id=f"betexplorer-{match_id}",
                    event_id=match_id,
                    event_name=f"{home_name} vs {away_name}",
                    market_name="Match Winner",
                    home_name=home_name,
                    away_name=away_name,
                    provider=self.provider_name,
                    start_time=start_time,
                    status=status,
                    in_play=in_play,
                    total_matched=None,
                    updated_at=now,
                    runners=runners,
                    extra={
                        "fixture_id": match_id,
                        "league_name": current_tournament,
                        "match_url": urljoin(str(self.client.base_url), match_href),
                        "source_page": urljoin(str(self.client.base_url), source_path),
                        "bookmaker_count": 1,
                        "bookmakers": [summary_row],
                        "overround": overround,
                        "market_type": "胜平负",
                        "odds_scope": "网页抓取",
                    },
                )
            )

        active_quotes = [
            item
            for item in quotes
            if item.status in ACTIVE_STATUSES
            and item.start_time <= now + timedelta(hours=self.settings.market_window_hours)
        ]
        if self.settings.normalized_live_score_mode == "off":
            active_quotes.sort(key=lambda item: (item.in_play, item.start_time, item.event_name))
        else:
            active_quotes.sort(key=lambda item: (not item.in_play, item.start_time, item.event_name))
        if active_quotes:
            return active_quotes[: self.settings.tracked_markets_limit]

        quotes.sort(key=lambda item: (item.status == "FT", not item.in_play, item.start_time))
        return quotes[: self.settings.tracked_markets_limit]


class ApiFootballOddsProvider(MarketProvider):
    provider_name = "api_football_odds"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = httpx.AsyncClient(
            base_url=self.settings.api_football_base_url,
            timeout=20,
            headers={"x-apisports-key": self.settings.api_football_key},
        )
        self.last_error: str | None = None
        self.pre_match_bet_id: int | None = None
        self.live_bet_id: int | None = None
        self.fixture_cache: dict[str, dict[str, Any]] = {}
        self.fixture_cache_at: datetime | None = None
        self.prematch_odds_cache: dict[str, dict[str, Any]] = {}
        self.prematch_odds_cache_at: datetime | None = None
        self.live_odds_cache: dict[str, dict[str, Any]] = {}
        self.live_odds_cache_at: datetime | None = None

    async def discover_markets(self) -> list[MarketQuote]:
        try:
            await self._ensure_reference_data()
            fixtures = await self._refresh_fixtures(force=True)
            quotes = await self._build_quotes(fixtures, force_prematch=True, force_live=True)
            self.last_error = None
            return quotes
        except Exception as exc:
            self.last_error = str(exc)
            raise

    async def fetch_market_books(self, market_ids: list[str]) -> list[MarketQuote]:
        try:
            fixtures = await self._refresh_fixtures(force=False)
            quotes = await self._build_quotes(fixtures, force_prematch=False, force_live=True)
            if not market_ids:
                self.last_error = None
                return quotes

            wanted = set(market_ids)
            filtered = [quote for quote in quotes if quote.market_id in wanted]
            self.last_error = None
            return filtered or quotes
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

    async def _ensure_reference_data(self) -> None:
        if self.pre_match_bet_id is None:
            self.pre_match_bet_id = await self._resolve_bet_id("/odds/bets", "Match Winner")
        if self.live_bet_id is None:
            self.live_bet_id = await self._resolve_bet_id("/odds/live/bets", "Match Winner")

    async def _resolve_bet_id(self, path: str, search_term: str) -> int | None:
        payload = await self._get_payload(path, {"search": search_term})
        candidates = payload.get("response", [])
        for item in candidates:
            name = str(item.get("name", "")).lower()
            if "winner" in name:
                return int(item["id"])
        return int(candidates[0]["id"]) if candidates else None

    async def _refresh_fixtures(self, force: bool) -> list[dict[str, Any]]:
        now = datetime.now(UTC)
        if (
            not force
            and self.fixture_cache_at
            and (now - self.fixture_cache_at).total_seconds() < self.settings.discovery_interval_seconds
        ):
            return list(self.fixture_cache.values())

        fixtures: dict[str, dict[str, Any]] = {}
        live_items = await self._fetch_live_fixtures()
        for item in live_items:
            fixtures[str(item["fixture"]["id"])] = item

        for date_key in _window_date_keys(now, self.settings.market_window_hours):
            for item in await self._fetch_fixtures_by_date(date_key):
                fixture_id = str(item["fixture"]["id"])
                if fixture_id not in fixtures:
                    fixtures[fixture_id] = item

        filtered = [
            item
            for item in fixtures.values()
            if _is_supported_fixture(item, now, self.settings.market_window_hours, self.settings.target_league_id_list)
        ]
        filtered.sort(key=lambda item: (not _is_live_fixture(item), _fixture_start(item)))
        filtered = filtered[: self.settings.tracked_markets_limit * 2]

        self.fixture_cache = {str(item["fixture"]["id"]): item for item in filtered}
        self.fixture_cache_at = now
        return filtered

    async def _fetch_live_fixtures(self) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"live": "all", "timezone": self.settings.api_football_timezone}
        if self.settings.target_league_id_list:
            params["live"] = "-".join(str(item) for item in sorted(self.settings.target_league_id_list))
        payload = await self._get_payload("/fixtures", params)
        return payload.get("response", [])

    async def _fetch_fixtures_by_date(self, date_key: str) -> list[dict[str, Any]]:
        payload = await self._get_payload(
            "/fixtures",
            {
                "date": date_key,
                "timezone": self.settings.api_football_timezone,
            },
        )
        return payload.get("response", [])

    async def _build_quotes(
        self,
        fixtures: list[dict[str, Any]],
        force_prematch: bool,
        force_live: bool,
    ) -> list[MarketQuote]:
        if not fixtures:
            return []

        now = datetime.now(UTC)
        fixture_ids = {str(item["fixture"]["id"]) for item in fixtures}
        pre_match_dates = sorted({_fixture_start(item).date().isoformat() for item in fixtures if not _is_live_fixture(item)})
        prematch_map = await self._refresh_prematch_odds(pre_match_dates, force=force_prematch)
        live_map = await self._refresh_live_odds(force=force_live)

        quotes: list[MarketQuote] = []
        for fixture in fixtures:
            fixture_id = str(fixture["fixture"]["id"])
            odds_item = None
            if _is_live_fixture(fixture):
                odds_item = live_map.get(fixture_id) or prematch_map.get(fixture_id)
            else:
                odds_item = prematch_map.get(fixture_id) or live_map.get(fixture_id)

            if not odds_item:
                continue

            quote = self._build_quote(fixture, odds_item, now)
            if quote:
                quotes.append(quote)

        quotes.sort(key=lambda item: (not item.in_play, item.start_time))
        return quotes[: self.settings.tracked_markets_limit]

    async def _refresh_prematch_odds(self, date_keys: list[str], force: bool) -> dict[str, dict[str, Any]]:
        now = datetime.now(UTC)
        if (
            not force
            and self.prematch_odds_cache_at
            and (now - self.prematch_odds_cache_at).total_seconds() < self.settings.prematch_odds_refresh_seconds
        ):
            return self.prematch_odds_cache

        mapping: dict[str, dict[str, Any]] = {}
        if self.pre_match_bet_id is None:
            return mapping

        for date_key in date_keys:
            response_items = await self._get_paged(
                "/odds",
                {
                    "date": date_key,
                    "bet": self.pre_match_bet_id,
                    "timezone": self.settings.api_football_timezone,
                },
                self.settings.prematch_odds_max_pages,
            )
            for item in response_items:
                fixture = item.get("fixture") or {}
                fixture_id = fixture.get("id")
                if fixture_id is None:
                    continue
                mapping[str(fixture_id)] = item

        self.prematch_odds_cache = mapping
        self.prematch_odds_cache_at = now
        return mapping

    async def _refresh_live_odds(self, force: bool) -> dict[str, dict[str, Any]]:
        now = datetime.now(UTC)
        if (
            not force
            and self.live_odds_cache_at
            and (now - self.live_odds_cache_at).total_seconds() < self.settings.live_odds_refresh_seconds
        ):
            return self.live_odds_cache

        mapping: dict[str, dict[str, Any]] = {}
        if self.live_bet_id is None:
            return mapping

        response_items = await self._get_paged(
            "/odds/live",
            {"bet": self.live_bet_id},
            self.settings.live_odds_max_pages,
        )
        for item in response_items:
            fixture = item.get("fixture") or {}
            fixture_id = fixture.get("id")
            if fixture_id is None:
                continue
            mapping[str(fixture_id)] = item

        self.live_odds_cache = mapping
        self.live_odds_cache_at = now
        return mapping

    def _build_quote(self, fixture_item: dict[str, Any], odds_item: dict[str, Any], now: datetime) -> MarketQuote | None:
        fixture = fixture_item.get("fixture", {})
        teams = fixture_item.get("teams", {})
        league = fixture_item.get("league", {})
        home_name = teams.get("home", {}).get("name", "") or "Home"
        away_name = teams.get("away", {}).get("name", "") or "Away"
        rows = self._extract_bookmakers(odds_item, home_name, away_name)
        if not rows:
            return None

        runners = [
            _runner_from_bookmakers(1, home_name, "home", rows),
            _runner_from_bookmakers(2, "Draw", "draw", rows),
            _runner_from_bookmakers(3, away_name, "away", rows),
        ]
        overround = round(sum((1 / runner.price) for runner in runners if runner.price), 4)
        updated_at = _parse_datetime(odds_item.get("update")) or now
        fixture_id = str(fixture.get("id"))
        bookmaker_rows = rows[:6]

        return MarketQuote(
            market_id=f"fixture-{fixture_id}",
            event_id=fixture_id,
            event_name=f"{home_name} vs {away_name}",
            market_name="Match Winner",
            home_name=home_name,
            away_name=away_name,
            provider=self.provider_name,
            start_time=_fixture_start(fixture_item),
            status=str(fixture_item.get("fixture", {}).get("status", {}).get("short", "NS")),
            in_play=_is_live_fixture(fixture_item),
            total_matched=float(len(bookmaker_rows)),
            updated_at=updated_at,
            runners=runners,
            extra={
                "fixture_id": fixture_id,
                "league_name": league.get("name", ""),
                "league_country": league.get("country", ""),
                "bookmaker_count": len(rows),
                "bookmakers": bookmaker_rows,
                "overround": overround,
                "market_type": "胜平负",
                "odds_scope": "滚球" if _is_live_fixture(fixture_item) else "赛前",
                "favorite_name": _favorite_name(runners),
            },
        )

    def _extract_bookmakers(self, odds_item: dict[str, Any], home_name: str, away_name: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        preferred = {item.lower() for item in self.settings.preferred_bookmaker_names}
        for bookmaker in odds_item.get("bookmakers", []) or []:
            bookmaker_name = str(bookmaker.get("name", "")).strip()
            if preferred and bookmaker_name and bookmaker_name.lower() not in preferred:
                continue

            bet = next(
                (
                    item
                    for item in bookmaker.get("bets", []) or []
                    if "winner" in str(item.get("name", "")).lower()
                ),
                None,
            )
            if not bet:
                continue

            values_by_outcome: dict[str, tuple[float, bool]] = {}
            for value in bet.get("values", []) or []:
                outcome = _normalise_outcome_label(value.get("value"), home_name, away_name)
                odd = _safe_float(value.get("odd"))
                if outcome is None or odd is None:
                    continue
                is_main = bool(value.get("main"))
                existing = values_by_outcome.get(outcome)
                if existing is None or is_main:
                    values_by_outcome[outcome] = (odd, is_main)

            if not {"home", "draw", "away"} <= set(values_by_outcome):
                continue

            rows.append(
                {
                    "name": bookmaker_name or "Bookmaker",
                    "home": values_by_outcome["home"][0],
                    "draw": values_by_outcome["draw"][0],
                    "away": values_by_outcome["away"][0],
                }
            )

        if rows:
            return rows

        fallback_rows: list[dict[str, Any]] = []
        for bookmaker in odds_item.get("bookmakers", []) or []:
            row = {"name": str(bookmaker.get("name", "")).strip() or "Bookmaker"}
            for bet in bookmaker.get("bets", []) or []:
                for value in bet.get("values", []) or []:
                    outcome = _normalise_outcome_label(value.get("value"), home_name, away_name)
                    odd = _safe_float(value.get("odd"))
                    if outcome and odd:
                        row[outcome] = odd
            if {"home", "draw", "away"} <= set(row):
                fallback_rows.append(row)
        return fallback_rows

    async def _get_payload(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        response = await self.client.get(path, params=params)
        response.raise_for_status()
        payload = response.json()
        errors = payload.get("errors") or {}
        if isinstance(errors, dict) and any(errors.values()):
            raise RuntimeError(f"API-Football error: {errors}")
        return payload

    async def _get_paged(self, path: str, params: dict[str, Any], max_pages: int) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page = 1
        while page <= max_pages:
            payload = await self._get_payload(path, {**params, "page": page})
            items.extend(payload.get("response", []))
            paging = payload.get("paging") or {}
            total_pages = int(paging.get("total") or 1)
            current_page = int(paging.get("current") or page)
            if current_page >= total_pages:
                break
            page += 1
        return items


class AutoMarketProvider(MarketProvider):
    provider_name = "auto"

    def __init__(self, primary: MarketProvider | None, fallback: MarketProvider) -> None:
        self.primary = primary
        self.fallback = fallback
        self.using_fallback = primary is None
        self.last_error: str | None = None

    async def discover_markets(self) -> list[MarketQuote]:
        if self.primary and not self.using_fallback:
            try:
                return await self.primary.discover_markets()
            except Exception as exc:
                self.last_error = str(exc)
                self.using_fallback = True
        return await self.fallback.discover_markets()

    async def fetch_market_books(self, market_ids: list[str]) -> list[MarketQuote]:
        if self.primary and not self.using_fallback:
            try:
                return await self.primary.fetch_market_books(market_ids)
            except Exception as exc:
                self.last_error = str(exc)
                self.using_fallback = True
        return await self.fallback.fetch_market_books(market_ids)

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
            "active_provider": primary_status.get("active_provider", self.fallback.provider_name),
            "fallback_active": False,
            "last_error": self.last_error,
            "ready": primary_status.get("ready", False),
        }


def build_provider(settings: Settings) -> MarketProvider:
    demo = DemoMarketProvider(settings)
    mode = settings.normalized_data_mode

    if mode == "demo":
        return demo
    if mode == "betexplorer_scrape":
        return BetExplorerScrapeProvider(settings)
    if mode == "api_football_odds":
        if settings.api_football_ready:
            return ApiFootballOddsProvider(settings)
        return UnavailableMarketProvider(
            provider_name="api_football_odds",
            message="当前是免费真实盘口模式，但还没有配置 API_FOOTBALL_KEY。",
        )
    if mode == "auto":
        primary = ApiFootballOddsProvider(settings) if settings.api_football_ready else None
        return AutoMarketProvider(primary=primary, fallback=demo)
    return demo


def quote_to_dict(quote: MarketQuote) -> dict[str, Any]:
    runners: list[dict[str, Any]] = []
    for runner in quote.runners:
        runners.append(
            {
                "selection_id": runner.selection_id,
                "name": runner.name,
                "price": runner.price,
                "implied_probability": runner.implied_probability,
                "mid_price": runner.price,
                "spread": runner.market_width,
                "market_width": runner.market_width,
                "best_price": runner.best_price,
                "worst_price": runner.worst_price,
                "bookmaker_count": runner.bookmaker_count,
                "bookmakers": runner.bookmakers,
                "momentum": 0.0,
                "outcome_key": "home" if runner.selection_id == 1 else "draw" if runner.selection_id == 2 else "away",
            }
        )

    return {
        "market_id": quote.market_id,
        "event_id": quote.event_id,
        "event_name": quote.event_name,
        "home_name": quote.home_name,
        "away_name": quote.away_name,
        "market_name": quote.market_name,
        "provider": quote.provider,
        "start_time": quote.start_time,
        "status": quote.status,
        "in_play": quote.in_play,
        "total_matched": quote.total_matched,
        "updated_at": quote.updated_at,
        "runners": runners,
        "extra": quote.extra,
    }


def _fixture_start(item: dict[str, Any]) -> datetime:
    return _parse_datetime((item.get("fixture") or {}).get("date")) or datetime.now(UTC)


def _is_live_fixture(item: dict[str, Any]) -> bool:
    status_short = str((item.get("fixture") or {}).get("status", {}).get("short", ""))
    return status_short in LIVE_STATUSES


def _is_supported_fixture(
    item: dict[str, Any],
    now: datetime,
    market_window_hours: int,
    target_league_ids: set[int],
) -> bool:
    fixture = item.get("fixture") or {}
    league = item.get("league") or {}
    status_short = str(fixture.get("status", {}).get("short", "NS"))
    fixture_time = _fixture_start(item)
    within_window = now - timedelta(hours=2) <= fixture_time <= now + timedelta(hours=market_window_hours)
    if target_league_ids and int(league.get("id") or 0) not in target_league_ids:
        return False
    if status_short in FINISHED_STATUSES:
        return False
    return within_window or status_short in LIVE_STATUSES


def _window_date_keys(now: datetime, window_hours: int) -> list[str]:
    values = {now.date().isoformat(), (now + timedelta(hours=window_hours)).date().isoformat()}
    return sorted(values)


def _runner_from_bookmakers(
    selection_id: int,
    label: str,
    outcome_key: str,
    bookmakers: list[dict[str, Any]],
) -> RunnerQuote:
    values = [float(item[outcome_key]) for item in bookmakers if item.get(outcome_key) is not None]
    value_rows = [
        {"name": item["name"], "price": round(float(item[outcome_key]), 3)}
        for item in bookmakers
        if item.get(outcome_key) is not None
    ]
    current_price = round(mean(values), 3) if values else None
    best_price = round(max(values), 3) if values else None
    worst_price = round(min(values), 3) if values else None
    market_width = round((best_price or 0.0) - (worst_price or 0.0), 3) if values else 0.0
    implied_probability = round(1 / current_price, 4) if current_price else None
    return RunnerQuote(
        selection_id=selection_id,
        name=label,
        price=current_price,
        implied_probability=implied_probability,
        bookmaker_count=len(values),
        best_price=best_price,
        worst_price=worst_price,
        market_width=market_width,
        bookmakers=value_rows[:8],
    )


def _runner_from_scrape_cell(
    selection_id: int,
    label: str,
    outcome_key: str,
    cell: Any,
) -> RunnerQuote:
    button = cell.find("button") if cell else None
    current_price = _safe_float(button.get("data-odd") if button else None)
    best_price = _safe_float(button.get("data-odd-max") if button else None) or current_price
    display_price = best_price or current_price
    width = abs((best_price or 0.0) - (current_price or best_price or 0.0))
    bookmaker_price = display_price

    return RunnerQuote(
        selection_id=selection_id,
        name=label,
        price=round(display_price, 3) if display_price is not None else None,
        implied_probability=round(1 / display_price, 4) if display_price else None,
        bookmaker_count=1 if display_price else 0,
        best_price=round(best_price, 3) if best_price is not None else None,
        worst_price=round(current_price or best_price or 0.0, 3) if display_price is not None else None,
        market_width=round(width, 3) if display_price is not None else 0.0,
        bookmakers=(
            [{"name": "BetExplorer", "price": round(bookmaker_price, 3)}]
            if bookmaker_price is not None
            else []
        ),
    )


def _favorite_name(runners: list[RunnerQuote]) -> str:
    candidates = [runner for runner in runners if runner.price]
    if not candidates:
        return ""
    return min(candidates, key=lambda item: item.price or 999.0).name


def _extract_available_lines(soup: BeautifulSoup) -> list[float]:
    lines = {
        value
        for value in (
            _safe_float(table.get("data-handicap")) for table in soup.select("table.table-main[data-handicap]")
        )
        if value is not None
    }
    return sorted(lines)


def _extract_betexplorer_bookmaker_name(cell: Any) -> str:
    if cell is None:
        return ""
    text = " ".join(cell.get_text(" ", strip=True).split())
    return text


def _is_supported_scrape_bookmaker(name: str) -> bool:
    normalized = name.strip().lower()
    if not normalized:
        return False
    return "betfair" not in normalized


def _aggregate_match_winner_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {}

    averages = {
        "home": _round_mean([row["home"] for row in rows if row.get("home") is not None]),
        "draw": _round_mean([row["draw"] for row in rows if row.get("draw") is not None]),
        "away": _round_mean([row["away"] for row in rows if row.get("away") is not None]),
    }
    best_prices = {
        "home": max((row["home"] for row in rows if row.get("home") is not None), default=None),
        "draw": max((row["draw"] for row in rows if row.get("draw") is not None), default=None),
        "away": max((row["away"] for row in rows if row.get("away") is not None), default=None),
    }
    favorite_side = min(
        ("home", "draw", "away"),
        key=lambda key: averages.get(key) if averages.get(key) is not None else 999.0,
    )
    return {
        "favorite_side": favorite_side,
        "avg_home": averages["home"],
        "avg_draw": averages["draw"],
        "avg_away": averages["away"],
        "best_home": round(best_prices["home"], 3) if best_prices["home"] is not None else None,
        "best_draw": round(best_prices["draw"], 3) if best_prices["draw"] is not None else None,
        "best_away": round(best_prices["away"], 3) if best_prices["away"] is not None else None,
    }


def _aggregate_two_way_rows(rows: list[dict[str, Any]], left_key: str, right_key: str) -> dict[str, Any]:
    if not rows:
        return {}

    left_values = [float(row[left_key]) for row in rows if row.get(left_key) is not None]
    right_values = [float(row[right_key]) for row in rows if row.get(right_key) is not None]
    if not left_values or not right_values:
        return {}

    avg_left = _round_mean(left_values)
    avg_right = _round_mean(right_values)
    left_prob = round(1 / avg_left, 4) if avg_left else 0.0
    right_prob = round(1 / avg_right, 4) if avg_right else 0.0
    lean = "balanced"
    if avg_left and avg_right:
        if avg_left + 0.03 < avg_right:
            lean = left_key
        elif avg_right + 0.03 < avg_left:
            lean = right_key

    return {
        f"avg_{left_key}": avg_left,
        f"avg_{right_key}": avg_right,
        f"best_{left_key}": round(max(left_values), 3),
        f"best_{right_key}": round(max(right_values), 3),
        "lean": lean,
        "lean_strength": round(abs(left_prob - right_prob), 4),
    }


def _handicap_favored_side(line: float) -> str:
    if line < 0:
        return "home"
    if line > 0:
        return "away"
    return "balanced"


def _round_mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(mean(values), 3)


def _split_match_name(raw_value: str) -> tuple[str, str]:
    parts = [part.strip() for part in raw_value.split(" - ", 1)]
    if len(parts) == 2:
        return parts[0], parts[1]
    return raw_value.strip(), "Away"


def _parse_betexplorer_local_datetime(raw_value: str | None) -> datetime | None:
    if not raw_value:
        return None

    try:
        day, month, year, hour, minute = [int(part) for part in raw_value.split(",")]
    except ValueError:
        return None

    return datetime(year, month, day, hour, minute)


def _extract_betexplorer_page_clock(
    soup: BeautifulSoup,
    now_utc: datetime,
    fallback_timezone: timezone | ZoneInfo,
) -> tuple[datetime, timezone | ZoneInfo]:
    row = soup.find("tr", attrs={"data-dt-now": True})
    page_now_local = _parse_betexplorer_local_datetime(row.get("data-dt-now")) if row else None
    if page_now_local is None:
        fallback_now = now_utc.astimezone(fallback_timezone)
        return fallback_now.replace(tzinfo=None), fallback_timezone

    offset_minutes = _infer_fixed_offset_minutes(page_now_local, now_utc)
    page_timezone = timezone(timedelta(minutes=offset_minutes))
    return page_now_local, page_timezone


def _infer_fixed_offset_minutes(page_now_local: datetime, now_utc: datetime) -> int:
    diff_minutes = int(round((page_now_local - now_utc.replace(tzinfo=None)).total_seconds() / 60))
    while diff_minutes <= -720:
        diff_minutes += 1440
    while diff_minutes > 840:
        diff_minutes -= 1440
    return int(round(diff_minutes / 15) * 15)


def _infer_scrape_status(start_time: datetime, page_now_local: datetime) -> tuple[str, bool]:
    if start_time <= page_now_local <= start_time + timedelta(hours=2, minutes=15):
        return "LIVE", True
    if page_now_local > start_time + timedelta(hours=2, minutes=15):
        return "FT", False
    return "NS", False


def _normalise_outcome_label(raw_value: Any, home_name: str, away_name: str) -> str | None:
    value = str(raw_value or "").strip().lower()
    home_key = home_name.strip().lower()
    away_key = away_name.strip().lower()
    if not value:
        return None
    if value in {"home", "1", home_key}:
        return "home"
    if value in {"draw", "x", "tie"}:
        return "draw"
    if value in {"away", "2", away_key}:
        return "away"
    if home_key and home_key in value:
        return "home"
    if away_key and away_key in value:
        return "away"
    if "draw" in value:
        return "draw"
    return None


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_datetime(raw_value: Any) -> datetime | None:
    if not raw_value:
        return None
    if isinstance(raw_value, datetime):
        return raw_value.astimezone(UTC) if raw_value.tzinfo else raw_value.replace(tzinfo=UTC)
    try:
        return datetime.fromisoformat(str(raw_value).replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None
