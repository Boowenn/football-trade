from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime


def label_by_score(score: float) -> str:
    if score >= 80:
        return "强下注"
    if score >= 65:
        return "可下注"
    if score >= 50:
        return "继续观察"
    return "不下注"


def build_recommendation(snapshot: dict, history: Sequence[dict]) -> dict:
    now = snapshot["updated_at"]
    runners = snapshot["runners"]
    historical = list(history)
    live_score = snapshot.get("live_score") or {}
    signals: list[dict] = []

    if not historical:
        return {
            "market_id": snapshot["market_id"],
            "recommendation": "不下注",
            "selection_name": "",
            "market_label": "胜平负",
            "score": 0.0,
            "confidence_label": "不下注",
            "risk_level": "High",
            "reasons": ["当前只有一笔盘口快照，缺少赔率变化轨迹。"],
            "breakdown": {},
            "signal": "neutral",
            "generated_at": now,
            "signals": [],
        }

    previous = historical[-1]
    opening = historical[0]
    candidates: list[dict] = []

    for runner in runners:
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
        event_score = _event_alignment_score(side_key, live_score)
        trend_score = _clamp(total_change * 180, -18.0, 28.0)
        momentum_score = _clamp(step_change * 260, -10.0, 18.0)
        consensus_score = _clamp(bookmaker_count * 2.0 - width * 35.0, 0.0, 18.0)
        width_penalty = _clamp(width * 50.0, 0.0, 16.0)
        short_price_penalty = 10.0 if current_price <= 1.28 else 6.0 if current_price <= 1.42 else 0.0
        draw_penalty = 4.0 if side_key == "draw" and (live_score.get("minute") or 0) < 55 else 0.0

        total_score = round(
            _clamp(
                48.0 + trend_score + momentum_score + consensus_score + event_score - width_penalty - short_price_penalty - draw_penalty,
                0.0,
                100.0,
            ),
            2,
        )

        if total_change >= 0.04:
            signals.append(
                {
                    "type": "bullish",
                    "severity": "medium",
                    "title": f"{runner['name']} 赔率持续下调",
                    "detail": f"从开盘到现在下降了 {abs(total_change) * 100:.1f}%，盘口在向这一方向集中。",
                }
            )
        elif total_change <= -0.05:
            signals.append(
                {
                    "type": "bearish",
                    "severity": "medium",
                    "title": f"{runner['name']} 赔率持续上浮",
                    "detail": f"从开盘到现在上升了 {abs(total_change) * 100:.1f}%，市场对这一方向的支持在减弱。",
                }
            )

        if width >= 0.22:
            signals.append(
                {
                    "type": "neutral",
                    "severity": "high",
                    "title": f"{runner['name']} 盘口分歧较大",
                    "detail": f"不同博彩公司价差达到 {width:.2f}，一致性偏弱，建议降低信心。",
                }
            )

        candidates.append(
            {
                "name": runner["name"],
                "side_key": side_key,
                "price": current_price,
                "total_change": total_change,
                "step_change": step_change,
                "width": width,
                "bookmaker_count": bookmaker_count,
                "score": total_score,
                "breakdown": {
                    "trend_score": round(trend_score, 2),
                    "momentum_score": round(momentum_score, 2),
                    "consensus_score": round(consensus_score, 2),
                    "event_score": round(event_score, 2),
                    "width_penalty": round(width_penalty, 2),
                    "short_price_penalty": round(short_price_penalty + draw_penalty, 2),
                },
            }
        )

    if not candidates:
        return {
            "market_id": snapshot["market_id"],
            "recommendation": "不下注",
            "selection_name": "",
            "market_label": "胜平负",
            "score": 0.0,
            "confidence_label": "不下注",
            "risk_level": "High",
            "reasons": ["当前赔率数据不完整，无法生成有效建议。"],
            "breakdown": {},
            "signal": "neutral",
            "generated_at": now,
            "signals": signals,
        }

    best = max(candidates, key=lambda item: item["score"])
    signal = "neutral"
    recommendation = "不下注"
    selection_name = ""
    reasons: list[str] = []

    if best["score"] >= 65 and best["total_change"] >= 0.025:
        recommendation = _side_label(best["side_key"])
        selection_name = best["name"]
        signal = "bullish" if best["side_key"] != "draw" else "neutral"
        reasons = [
            f"{best['name']} 当前平均赔率 {best['price']:.2f}，较开盘收缩 {best['total_change'] * 100:.1f}%。",
            f"已覆盖 {best['bookmaker_count']} 家博彩公司，盘口分歧 {best['width']:.2f}。",
            _event_reason(best["side_key"], live_score),
        ]
    elif best["score"] >= 55 and best["total_change"] >= 0.015:
        recommendation = "观察 " + _side_label(best["side_key"])
        selection_name = best["name"]
        signal = "neutral"
        reasons = [
            f"{best['name']} 有一定赔率收缩，但强度还不够，当前变化 {best['total_change'] * 100:.1f}%。",
            f"盘口分歧 {best['width']:.2f}，建议继续观察后续变化。",
        ]
    else:
        reasons = [
            "当前盘口没有形成足够一致的方向性。",
            "赔率变化、博彩公司分歧和比赛事件没有同时支持同一方向。",
        ]

    risk_level = _risk_level(candidates, live_score)

    return {
        "market_id": snapshot["market_id"],
        "recommendation": recommendation,
        "selection_name": selection_name,
        "market_label": "胜平负",
        "score": round(best["score"], 2),
        "confidence_label": label_by_score(best["score"]),
        "risk_level": risk_level,
        "reasons": reasons,
        "breakdown": best["breakdown"],
        "signal": signal,
        "generated_at": now,
        "signals": signals,
    }


def _runner_price(runner: dict) -> float | None:
    price = runner.get("price") or runner.get("mid_price")
    if price is not None:
        return price

    best_price = runner.get("best_price")
    worst_price = runner.get("worst_price")
    if best_price and worst_price:
        return round((best_price + worst_price) / 2, 3)
    return best_price or worst_price


def _history_runner_price(point: dict, selection_id: int) -> float | None:
    runner = next((item for item in point.get("runners", []) if item["selection_id"] == selection_id), None)
    if not runner:
        return None
    return _runner_price(runner)


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

    score = 10.0 if home_score == away_score and minute >= 60 else -20.0 if home_score != away_score else 0.0
    if home_red != away_red and minute >= 60:
        score -= 4.0
    return score


def _event_reason(side_key: str, live_score: dict) -> str:
    minute = int(live_score.get("minute") or 0)
    home_score = int(live_score.get("home_score") or 0)
    away_score = int(live_score.get("away_score") or 0)
    home_red = int(live_score.get("home_red") or 0)
    away_red = int(live_score.get("away_red") or 0)

    if side_key == "home":
        if home_score > away_score:
            return f"实时比分 {home_score}-{away_score}，主队领先。"
        if away_red > home_red:
            return "客队红牌更多，主队场上优势更明显。"
        return f"当前比赛时间 {minute}'，盘口和场上形势暂时没有明显冲突。"

    if side_key == "away":
        if away_score > home_score:
            return f"实时比分 {home_score}-{away_score}，客队领先。"
        if home_red > away_red:
            return "主队红牌更多，客队场上优势更明显。"
        return f"当前比赛时间 {minute}'，盘口和场上形势暂时没有明显冲突。"

    if home_score == away_score:
        return f"当前比分 {home_score}-{away_score}，平局方向仍然有效。"
    return "比分已经被打破，平局方向不再占优。"


def _risk_level(candidates: list[dict], live_score: dict) -> str:
    widths = [item["width"] for item in candidates]
    counts = [item["bookmaker_count"] for item in candidates]
    max_width = max(widths) if widths else 0.4
    min_count = min(counts) if counts else 0
    minute = int(live_score.get("minute") or 0)

    if max_width <= 0.12 and min_count >= 4 and minute < 75:
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


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))
