from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from statistics import mean
from typing import Any


def label_by_score(score: float) -> str:
    if score >= 80:
        return "强"
    if score >= 66:
        return "可下"
    if score >= 54:
        return "谨慎"
    return "不下"


def build_recommendation(snapshot: dict, history: Sequence[dict]) -> dict:
    now = snapshot["updated_at"]
    historical = list(history)
    live_score = snapshot.get("live_score") or {}

    if not historical:
        return _single_snapshot_recommendation(snapshot, now)
    if not _history_has_actionable_signal(snapshot, historical, live_score):
        return _single_snapshot_recommendation(snapshot, now)

    candidates, signals = _trend_candidates(snapshot, historical, live_score)
    if not candidates:
        return _empty_recommendation(
            snapshot["market_id"],
            now,
            signals,
            ["历史价格变化不足，暂时没有可执行信号。"],
        )

    best = max(candidates, key=lambda item: item["score"])
    recommendation, selection_name, signal = _final_call(best, snapshot)
    reasons = _build_reasons(best, snapshot, live_score)
    if recommendation == "不下注":
        reasons = [
            "盘口走势有参考价值，但强度还不够。",
            "当前更适合继续等待盘口、比分或比赛事件继续确认。",
        ] + reasons[:2]

    return {
        "market_id": snapshot["market_id"],
        "recommendation": recommendation,
        "selection_name": selection_name,
        "market_label": "胜平负",
        "score": round(best["score"], 2),
        "confidence_label": label_by_score(best["score"]),
        "risk_level": _risk_level(snapshot, live_score),
        "reasons": reasons[:5],
        "breakdown": best["breakdown"],
        "signal": signal,
        "generated_at": now,
        "signals": signals,
    }


def _single_snapshot_recommendation(snapshot: dict, now: datetime) -> dict:
    live_score = snapshot.get("live_score") or {}
    ordered = _ordered_runners(snapshot)
    if len(ordered) < 3:
        return _empty_recommendation(
            snapshot["market_id"],
            now,
            [],
            ["赔率数据还不完整，暂时不做下注建议。"],
        )

    favorite = ordered[0]
    second = ordered[1]
    third = ordered[2]
    overround = float(snapshot.get("extra", {}).get("overround") or 1.06)

    favorite_prob = round(1 / favorite["price"], 4)
    second_prob = round(1 / second["price"], 4)
    probability_gap = max(0.0, favorite_prob - second_prob)
    price_gap = max(0.0, second["price"] - favorite["price"])
    outer_gap = max(0.0, third["price"] - second["price"])

    favorite_score = (
        18.0
        if favorite_prob >= 0.64
        else 14.0
        if favorite_prob >= 0.56
        else 10.0
        if favorite_prob >= 0.50
        else 6.0
        if favorite_prob >= 0.45
        else 2.0
    )
    gap_score = _clamp(probability_gap * 90.0, 0.0, 16.0)
    separation_score = _clamp(price_gap * 5.5 + outer_gap * 2.2, 0.0, 12.0)
    bookmaker_bonus = _clamp((favorite["bookmaker_count"] - 2) * 1.35, 0.0, 9.0)
    market_context = _market_alignment_context(favorite["side_key"], snapshot, live_score)
    width_penalty = _clamp(favorite["width"] * 18.0, 0.0, 8.0)
    margin_penalty = _clamp(abs(overround - 1.0) * 36.0, 0.0, 7.0)
    balance_penalty = 8.0 if favorite_prob < 0.44 else 4.0 if favorite_prob < 0.48 else 0.0
    draw_penalty = 10.0 if favorite["side_key"] == "draw" else 0.0
    short_price_penalty = (
        28.0
        if favorite["price"] <= 1.08
        else 16.0
        if favorite["price"] <= 1.14
        else 10.0
        if favorite["price"] <= 1.22
        else 4.0
        if favorite["price"] <= 1.32
        else 0.0
    )
    live_unknown_penalty = 10.0 if snapshot.get("in_play") and not live_score.get("matched") else 0.0
    event_score = _event_alignment_score(favorite["side_key"], live_score) if live_score.get("matched") else 0.0

    total_score = round(
        _clamp(
            28.0
            + favorite_score
            + gap_score
            + separation_score
            + bookmaker_bonus
            + market_context["score"]
            + event_score
            - width_penalty
            - margin_penalty
            - balance_penalty
            - draw_penalty
            - short_price_penalty
            - live_unknown_penalty,
            0.0,
            100.0,
        ),
        2,
    )

    candidate = {
        "name": favorite["name"],
        "side_key": favorite["side_key"],
        "price": favorite["price"],
        "score": total_score,
        "bookmaker_count": favorite["bookmaker_count"],
        "width": favorite["width"],
        "market_context": market_context,
        "total_change": 0.0,
        "step_change": 0.0,
        "breakdown": {
            "favorite_score": round(favorite_score, 2),
            "gap_score": round(gap_score, 2),
            "separation_score": round(separation_score, 2),
            "bookmaker_bonus": round(bookmaker_bonus, 2),
            "market_alignment": round(market_context["score"], 2),
            "event_score": round(event_score, 2),
            "width_penalty": round(width_penalty, 2),
            "margin_penalty": round(margin_penalty, 2),
            "balance_penalty": round(balance_penalty + draw_penalty, 2),
            "short_price_penalty": round(short_price_penalty, 2),
            "live_unknown_penalty": round(live_unknown_penalty, 2),
        },
    }

    signals = _market_structure_signals(snapshot)
    recommendation, selection_name, signal = _final_call(candidate, snapshot)
    reasons = _build_reasons(candidate, snapshot, live_score)
    if recommendation == "不下注":
        reasons = [
            "主选方向存在，但赔率优势不够大。",
            "建议继续等待盘口进一步收敛或比赛事件确认。",
        ] + reasons[:2]

    return {
        "market_id": snapshot["market_id"],
        "recommendation": recommendation,
        "selection_name": selection_name,
        "market_label": "胜平负",
        "score": total_score,
        "confidence_label": label_by_score(total_score),
        "risk_level": _risk_level(snapshot, live_score),
        "reasons": reasons[:5],
        "breakdown": candidate["breakdown"],
        "signal": signal,
        "generated_at": now,
        "signals": signals,
    }


def _trend_candidates(snapshot: dict, historical: Sequence[dict], live_score: dict) -> tuple[list[dict], list[dict]]:
    previous = historical[-1]
    opening = historical[0]
    current_runners = _ordered_runners(snapshot)
    if not current_runners:
        return [], []

    favorite_price = current_runners[0]["price"]
    signals = _market_structure_signals(snapshot)
    candidates: list[dict] = []

    for runner in snapshot.get("runners", []):
        side_key = runner.get("outcome_key") or _infer_outcome_key(runner, snapshot)
        current_price = _runner_price(runner)
        opening_price = _history_runner_price(opening, runner["selection_id"])
        previous_price = _history_runner_price(previous, runner["selection_id"])
        if current_price is None or opening_price is None or previous_price is None:
            continue

        total_change = round((opening_price - current_price) / opening_price, 4)
        step_change = round((previous_price - current_price) / previous_price, 4)
        width = float(runner.get("market_width") or runner.get("spread") or 0.0)
        bookmaker_count = int(runner.get("bookmaker_count") or snapshot.get("extra", {}).get("bookmaker_count") or 0)
        market_context = _market_alignment_context(side_key, snapshot, live_score)
        event_score = _event_alignment_score(side_key, live_score) if live_score.get("matched") else 0.0

        price_strength = (
            18.0
            if current_price <= 1.6
            else 14.0
            if current_price <= 1.95
            else 10.0
            if current_price <= 2.35
            else 6.0
            if current_price <= 2.9
            else 2.0
        )
        trend_score = _clamp(total_change * 220.0, -16.0, 24.0)
        momentum_score = _clamp(step_change * 300.0, -9.0, 15.0)
        consensus_score = _clamp(bookmaker_count * 1.9 - width * 32.0, 0.0, 18.0)
        width_penalty = _clamp(width * 46.0, 0.0, 16.0)
        underdog_penalty = (
            10.0
            if current_price - favorite_price >= 1.1
            else 5.0
            if current_price - favorite_price >= 0.55
            else 0.0
        )
        draw_penalty = 10.0 if side_key == "draw" else 0.0
        short_price_penalty = 10.0 if current_price <= 1.18 else 5.0 if current_price <= 1.28 else 0.0

        total_score = round(
            _clamp(
                24.0
                + price_strength
                + trend_score
                + momentum_score
                + consensus_score
                + market_context["score"]
                + event_score
                - width_penalty
                - underdog_penalty
                - draw_penalty
                - short_price_penalty,
                0.0,
                100.0,
            ),
            2,
        )

        if total_change >= 0.03:
            signals.append(
                {
                    "type": "bullish",
                    "severity": "medium",
                    "title": f"{runner['name']} 赔率持续下压",
                    "detail": f"从开盘到当前累计回落 {abs(total_change) * 100:.1f}%，说明该方向持续受支持。",
                }
            )
        elif total_change <= -0.04:
            signals.append(
                {
                    "type": "bearish",
                    "severity": "medium",
                    "title": f"{runner['name']} 赔率持续走弱",
                    "detail": f"从开盘到当前累计上浮 {abs(total_change) * 100:.1f}%，市场支持正在下降。",
                }
            )

        candidates.append(
            {
                "name": runner["name"],
                "side_key": side_key,
                "price": current_price,
                "score": total_score,
                "width": width,
                "bookmaker_count": bookmaker_count,
                "total_change": total_change,
                "step_change": step_change,
                "market_context": market_context,
                "breakdown": {
                    "price_strength": round(price_strength, 2),
                    "trend_score": round(trend_score, 2),
                    "momentum_score": round(momentum_score, 2),
                    "consensus_score": round(consensus_score, 2),
                    "market_alignment": round(market_context["score"], 2),
                    "event_score": round(event_score, 2),
                    "width_penalty": round(width_penalty, 2),
                    "underdog_penalty": round(underdog_penalty + draw_penalty, 2),
                    "short_price_penalty": round(short_price_penalty, 2),
                },
            }
        )

    return candidates, signals


def _final_call(candidate: dict, snapshot: dict) -> tuple[str, str, str]:
    side_key = candidate["side_key"]
    score = float(candidate["score"])
    price = float(candidate["price"])
    market_context = candidate.get("market_context") or {}
    market_alignment = float(market_context.get("score") or 0.0)
    total_change = float(candidate.get("total_change") or 0.0)
    strong_market_support = market_alignment >= 8.0
    too_short_to_chase = price <= 1.08

    if side_key != "draw" and score >= 66.0 and not too_short_to_chase:
        if total_change >= 0.008 or strong_market_support or not snapshot.get("in_play"):
            return _side_label(side_key), candidate["name"], "bullish"

    if side_key != "draw" and score >= 56.0 and not too_short_to_chase:
        if total_change >= 0.004 or strong_market_support:
            return f"谨慎{_side_label(side_key)}", candidate["name"], "neutral"

    return "不下注", "", "neutral"


def _build_reasons(candidate: dict, snapshot: dict, live_score: dict) -> list[str]:
    reasons = [
        f"{candidate['name']} 当前均价 {candidate['price']:.2f}，可用赔率源 {candidate['bookmaker_count']} 家，离散度 {candidate['width']:.2f}。",
    ]

    total_change = float(candidate.get("total_change") or 0.0)
    step_change = float(candidate.get("step_change") or 0.0)
    if total_change > 0:
        reasons.append(
            f"从开盘到现在赔率回落 {total_change * 100:.1f}%，最近一跳再回落 {step_change * 100:.1f}%，市场倾向持续增强。"
        )
    elif total_change < 0:
        reasons.append(
            f"从开盘到现在赔率上浮 {abs(total_change) * 100:.1f}%，说明这个方向的支持有所减弱。"
        )
    else:
        reasons.append("当前更多依赖多家盘口横向比较，不依赖明显的历史趋势。")

    market_context = candidate.get("market_context") or {}
    reasons.extend(market_context.get("reasons") or [])
    reasons.extend(market_context.get("warnings") or [])

    event_reason = _event_reason(candidate["side_key"], live_score)
    if event_reason:
        reasons.append(event_reason)

    return reasons


def _ordered_runners(snapshot: dict) -> list[dict]:
    ordered = []
    for runner in snapshot.get("runners", []):
        price = _runner_price(runner)
        if price is None:
            continue
        ordered.append(
            {
                "name": runner["name"],
                "side_key": runner.get("outcome_key") or _infer_outcome_key(runner, snapshot),
                "price": price,
                "width": float(runner.get("market_width") or runner.get("spread") or 0.0),
                "bookmaker_count": int(runner.get("bookmaker_count") or 0),
            }
        )
    ordered.sort(key=lambda item: item["price"])
    return ordered


def _runner_price(runner: dict) -> float | None:
    price = runner.get("price") or runner.get("mid_price")
    if price is not None:
        return float(price)

    best_price = runner.get("best_price")
    worst_price = runner.get("worst_price")
    if best_price and worst_price:
        return round((float(best_price) + float(worst_price)) / 2, 3)
    if best_price is not None:
        return float(best_price)
    if worst_price is not None:
        return float(worst_price)
    return None


def _market_alignment_context(side_key: str, snapshot: dict, live_score: dict) -> dict[str, Any]:
    related_markets = (snapshot.get("extra") or {}).get("related_markets") or {}
    score = 0.0
    reasons: list[str] = []
    warnings: list[str] = []

    ah = related_markets.get("asian_handicap") or {}
    ah_summary = ah.get("summary") or {}
    ah_line = _safe_float(ah.get("active_line"))
    ah_side = ah_summary.get("line_favored_side")
    ah_price_lean = ah_summary.get("lean")

    if side_key in {"home", "away"} and ah_line is not None:
        if ah_side == side_key:
            bonus = 5.0 + min(abs(ah_line) * 6.0, 6.0)
            score += bonus
            reasons.append(f"亚盘主线 {_format_line(ah_line)} 支持 {side_key_to_text(side_key)}。")
        elif ah_side and ah_side != "balanced":
            penalty = 5.0 + min(abs(ah_line) * 6.0, 6.0)
            score -= penalty
            warnings.append(f"亚盘主线 {_format_line(ah_line)} 更支持 {side_key_to_text(ah_side)}，与当前方向不一致。")

        if ah_price_lean == side_key:
            score += 3.5
        elif ah_price_lean and ah_price_lean != "balanced":
            score -= 3.5

    ou = related_markets.get("over_under") or {}
    ou_summary = ou.get("summary") or {}
    ou_line = _safe_float(ou.get("active_line"))
    ou_lean = ou_summary.get("lean")

    if ou_line is not None:
        if side_key in {"home", "away"}:
            if ou_line <= 2.25:
                score += 2.0
                reasons.append(f"大小球主线 {ou_line:.2f} 偏低，比赛波动相对可控。")
            elif ou_line >= 3.25:
                score -= 2.5
                warnings.append(f"大小球主线 {ou_line:.2f} 偏高，比赛波动更大。")
        elif side_key == "draw":
            if ou_line <= 2.25:
                score += 1.0
            elif ou_line >= 3.0:
                score -= 4.0

    if live_score.get("matched") and side_key in {"home", "away"}:
        home_score = int(live_score.get("home_score") or 0)
        away_score = int(live_score.get("away_score") or 0)
        minute = int(live_score.get("minute") or 0)
        leading_side = "home" if home_score > away_score else "away" if away_score > home_score else "draw"

        if minute >= 70 and leading_side == side_key and ou_lean == "under":
            score += 2.5
            reasons.append("比赛进入后段且大小球偏向小球，领先方守住结果的条件更好。")
        if minute >= 70 and leading_side != side_key and leading_side != "draw" and ou_lean == "under":
            score -= 2.0

    return {
        "score": round(score, 2),
        "reasons": reasons,
        "warnings": warnings,
    }


def _market_structure_signals(snapshot: dict) -> list[dict]:
    signals: list[dict] = []
    related_markets = (snapshot.get("extra") or {}).get("related_markets") or {}
    match_summary = ((related_markets.get("match_winner") or {}).get("summary")) or {}
    ah = related_markets.get("asian_handicap") or {}
    ah_summary = ah.get("summary") or {}
    ah_side = ah_summary.get("line_favored_side")
    favorite_side = match_summary.get("favorite_side")

    if favorite_side and ah_side and favorite_side != ah_side and favorite_side != "draw" and ah_side != "balanced":
        signals.append(
            {
                "type": "neutral",
                "severity": "high",
                "title": "胜平负与亚盘方向不一致",
                "detail": f"胜平负当前偏向 {side_key_to_text(favorite_side)}，但亚盘主线偏向 {side_key_to_text(ah_side)}。",
            }
        )

    ou_line = _safe_float((related_markets.get("over_under") or {}).get("active_line"))
    if ou_line is not None and ou_line >= 3.5:
        signals.append(
            {
                "type": "neutral",
                "severity": "medium",
                "title": "比赛预期进球偏高",
                "detail": f"大小球主线来到 {ou_line:.2f}，说明节奏和波动都偏大。",
            }
        )

    widths = [
        float(runner.get("market_width") or runner.get("spread") or 0.0)
        for runner in snapshot.get("runners", [])
    ]
    if widths and max(widths) >= 0.22:
        signals.append(
            {
                "type": "neutral",
                "severity": "medium",
                "title": "不同公司报价分歧偏大",
                "detail": f"当前最大离散度 {max(widths):.2f}，说明市场共识还不够稳。",
            }
        )

    return signals


def _empty_recommendation(market_id: str, now: datetime, signals: list[dict], reasons: list[str]) -> dict:
    return {
        "market_id": market_id,
        "recommendation": "不下注",
        "selection_name": "",
        "market_label": "胜平负",
        "score": 0.0,
        "confidence_label": "不下",
        "risk_level": "High",
        "reasons": reasons,
        "breakdown": {},
        "signal": "neutral",
        "generated_at": now,
        "signals": signals,
    }


def _history_runner_price(point: dict, selection_id: int) -> float | None:
    runner = next((item for item in point.get("runners", []) if item["selection_id"] == selection_id), None)
    if not runner:
        return None
    return _runner_price(runner)


def _history_has_actionable_signal(snapshot: dict, historical: Sequence[dict], live_score: dict) -> bool:
    if live_score.get("matched"):
        return True

    if len(historical) < 2:
        return False

    for runner in snapshot.get("runners", []):
        selection_id = runner.get("selection_id")
        current_price = _runner_price(runner)
        if selection_id is None or current_price is None:
            continue

        prices = [
            price
            for price in (_history_runner_price(point, selection_id) for point in historical)
            if price is not None
        ]
        if not prices:
            continue

        low = min(prices + [current_price])
        high = max(prices + [current_price])
        absolute_move = high - low
        relative_move = absolute_move / max(low, 1.01)

        if absolute_move >= 0.03 or relative_move >= 0.01:
            return True

    return False


def _infer_outcome_key(runner: dict, snapshot: dict) -> str:
    name = str(runner.get("name", "")).strip().lower()
    if name == str(snapshot.get("home_name", "")).strip().lower():
        return "home"
    if name == str(snapshot.get("away_name", "")).strip().lower():
        return "away"
    return "draw"


def _event_alignment_score(side_key: str, live_score: dict) -> float:
    minute = int(live_score.get("minute") or 0)
    home_score = int(live_score.get("home_score") or 0)
    away_score = int(live_score.get("away_score") or 0)
    home_red = int(live_score.get("home_red") or 0)
    away_red = int(live_score.get("away_red") or 0)

    if side_key == "home":
        score = 14.0 if home_score > away_score else -18.0 if home_score < away_score else 0.0
        score += 10.0 if away_red > home_red else -12.0 if home_red > away_red else 0.0
        if minute >= 75 and home_score == away_score:
            score -= 4.0
        return score

    if side_key == "away":
        score = 14.0 if away_score > home_score else -18.0 if away_score < home_score else 0.0
        score += 10.0 if home_red > away_red else -12.0 if away_red > home_red else 0.0
        if minute >= 75 and home_score == away_score:
            score -= 4.0
        return score

    score = 8.0 if home_score == away_score and minute >= 60 else -20.0 if home_score != away_score else 0.0
    if home_red != away_red and minute >= 60:
        score -= 4.0
    return score


def _event_reason(side_key: str, live_score: dict) -> str:
    if not live_score.get("matched"):
        return ""

    minute = int(live_score.get("minute") or 0)
    home_score = int(live_score.get("home_score") or 0)
    away_score = int(live_score.get("away_score") or 0)
    home_red = int(live_score.get("home_red") or 0)
    away_red = int(live_score.get("away_red") or 0)

    if side_key == "home":
        if home_score > away_score:
            return f"实时比分 {home_score}-{away_score}，主队当前领先。"
        if away_red > home_red:
            return "客队红牌更多，主队在人数上占优。"
        return f"当前比赛时间 {minute}'，比分仍可继续观察。"

    if side_key == "away":
        if away_score > home_score:
            return f"实时比分 {home_score}-{away_score}，客队当前领先。"
        if home_red > away_red:
            return "主队红牌更多，客队在人数上占优。"
        return f"当前比赛时间 {minute}'，比分仍可继续观察。"

    if home_score == away_score:
        return f"当前比分 {home_score}-{away_score}，平局方向仍然成立。"
    return "当前比分已经被打破，平局方向承压。"


def _risk_level(snapshot: dict, live_score: dict) -> str:
    widths = [
        float(runner.get("market_width") or runner.get("spread") or 0.0)
        for runner in snapshot.get("runners", [])
    ]
    counts = [int(runner.get("bookmaker_count") or 0) for runner in snapshot.get("runners", [])]
    related_markets = (snapshot.get("extra") or {}).get("related_markets") or {}
    match_summary = ((related_markets.get("match_winner") or {}).get("summary")) or {}
    ah_summary = ((related_markets.get("asian_handicap") or {}).get("summary")) or {}
    conflict = (
        match_summary.get("favorite_side")
        and ah_summary.get("line_favored_side")
        and match_summary.get("favorite_side") != ah_summary.get("line_favored_side")
        and match_summary.get("favorite_side") != "draw"
        and ah_summary.get("line_favored_side") != "balanced"
    )
    max_width = max(widths) if widths else 0.4
    min_count = min(counts) if counts else 0
    minute = int(live_score.get("minute") or 0)

    if not conflict and max_width <= 0.12 and min_count >= 4 and minute < 75:
        return "Low"
    if max_width <= 0.22 and min_count >= 3 and minute < 85:
        return "Medium"
    return "High"


def _side_label(side_key: str) -> str:
    return {
        "home": "主胜",
        "draw": "平局",
        "away": "客胜",
    }.get(side_key, "不下注")


def side_key_to_text(side_key: str) -> str:
    return {
        "home": "主队",
        "draw": "平局",
        "away": "客队",
        "balanced": "均衡",
    }.get(side_key, side_key or "未知")


def _format_line(line: float) -> str:
    if line > 0:
        return f"+{line:.2f}"
    return f"{line:.2f}"


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _mean_price(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return round(mean(values), 3)
