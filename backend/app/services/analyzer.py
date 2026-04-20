from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
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
    live_score = snapshot.get("live_score") or {}
    historical = list(history)
    use_history = bool(historical) and _history_has_actionable_signal(snapshot, historical, live_score)

    result_candidates, signals = _build_result_candidates(snapshot, historical if use_history else [], live_score)
    match_profile = _build_match_profile(snapshot, result_candidates)
    play_candidates = _build_play_candidates(snapshot, result_candidates, live_score)
    play_candidates.sort(key=lambda item: item["score"], reverse=True)
    plays_payload = [_serialize_play(item) for item in play_candidates[:5]]

    if not play_candidates:
        return _empty_recommendation(
            snapshot["market_id"],
            now,
            signals,
            ["当前盘口数据还不够完整，暂时无法给出玩法建议。"],
            plays_payload,
            stake_plan=_build_stake_plan(None, "High"),
        )

    best = play_candidates[0]
    risk_level = _risk_level(snapshot, live_score)
    primary_play = _serialize_play(best)
    stake_plan = _build_stake_plan(best, risk_level)
    why_not_others = _build_why_not_others(best, play_candidates[1:5], match_profile, risk_level)

    if best["score"] >= 66:
        recommendation = best["full_label"]
        selection_name = best["selection_name"]
        signal = best["signal"]
        reasons = best["reasons"][:5]
    elif best["score"] >= 54:
        recommendation = f"谨慎买 {best['full_label']}"
        selection_name = best["selection_name"]
        signal = "neutral"
        reasons = [
            f"当前最优玩法是 {best['full_label']}，但优势还没强到重仓级别。",
            "更适合轻仓或继续等待盘口继续确认。",
        ] + best["reasons"][:3]
    else:
        return _empty_recommendation(
            snapshot["market_id"],
            now,
            signals,
            [
                "当前没有足够优势的主推玩法。",
                f"最接近可执行的是 {best['full_label']}，但评分只有 {best['score']:.0f}。",
            ]
            + best["reasons"][:3],
            plays_payload,
            primary_play=primary_play,
            stake_plan=stake_plan,
            why_not_others=why_not_others,
        )

    return {
        "market_id": snapshot["market_id"],
        "recommendation": recommendation,
        "selection_name": selection_name,
        "market_label": best["market_label"],
        "score": round(best["score"], 2),
        "confidence_label": label_by_score(best["score"]),
        "risk_level": risk_level,
        "reasons": reasons[:5],
        "breakdown": best["breakdown"],
        "signal": signal,
        "generated_at": now,
        "signals": signals,
        "plays": plays_payload,
        "primary_play": primary_play,
        "stake_plan": stake_plan,
        "why_not_others": why_not_others,
    }


def _build_result_candidates(snapshot: dict, historical: Sequence[dict], live_score: dict) -> tuple[list[dict], list[dict]]:
    runners = snapshot.get("runners", [])
    ordered = _ordered_runners(snapshot)
    if not ordered:
        return [], []

    favorite_price = ordered[0]["price"]
    second_price = ordered[1]["price"] if len(ordered) > 1 else ordered[0]["price"]
    candidate_positions = {item["side_key"]: index for index, item in enumerate(ordered)}
    signals = _market_structure_signals(snapshot)
    candidates: list[dict] = []

    opening_point = historical[0] if historical else None
    previous_point = historical[-1] if historical else None

    for runner in runners:
        side_key = runner.get("outcome_key") or _infer_outcome_key(runner, snapshot)
        current_price = _runner_price(runner)
        if current_price is None:
            continue

        bookmaker_count = int(runner.get("bookmaker_count") or snapshot.get("extra", {}).get("bookmaker_count") or 0)
        width = float(runner.get("market_width") or runner.get("spread") or 0.0)
        implied_probability = 1 / current_price
        rank = candidate_positions.get(side_key, 2)
        market_context = _market_alignment_context(side_key, snapshot, live_score)
        event_score = _event_alignment_score(side_key, live_score) if live_score.get("matched") else 0.0

        total_change = 0.0
        step_change = 0.0
        trend_score = 0.0
        momentum_score = 0.0

        if opening_point and previous_point:
            opening_price = _history_runner_price(opening_point, runner["selection_id"])
            previous_price = _history_runner_price(previous_point, runner["selection_id"])
            if opening_price and previous_price:
                total_change = round((opening_price - current_price) / opening_price, 4)
                step_change = round((previous_price - current_price) / previous_price, 4)
                trend_score = _clamp(total_change * 220.0, -16.0, 24.0)
                momentum_score = _clamp(step_change * 300.0, -9.0, 15.0)

        favorite_bonus = (
            14.0
            if rank == 0
            else 6.0
            if rank == 1 and side_key != "draw"
            else 4.0
            if rank == 1 and side_key == "draw"
            else 0.0
        )
        price_strength = (
            16.0
            if current_price <= 1.60
            else 13.0
            if current_price <= 1.95
            else 10.0
            if current_price <= 2.35
            else 6.0
            if current_price <= 3.05
            else 2.0
        )
        gap_score = _result_gap_score(side_key, ordered, current_price)
        consensus_score = _clamp(bookmaker_count * 1.8 - width * 30.0, 0.0, 18.0)
        width_penalty = _clamp(width * 44.0, 0.0, 16.0)
        draw_penalty = 7.0 if side_key == "draw" and current_price > second_price else 0.0
        short_price_penalty = (
            14.0
            if current_price <= 1.12
            else 8.0
            if current_price <= 1.22
            else 3.0
            if current_price <= 1.32
            else 0.0
        )
        underdog_penalty = (
            10.0
            if current_price - favorite_price >= 1.10
            else 5.0
            if current_price - favorite_price >= 0.55
            else 0.0
        )

        total_score = round(
            _clamp(
                20.0
                + favorite_bonus
                + price_strength
                + gap_score
                + trend_score
                + momentum_score
                + consensus_score
                + market_context["score"]
                + event_score
                - width_penalty
                - draw_penalty
                - short_price_penalty
                - underdog_penalty,
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
                "kind": "result",
                "side_key": side_key,
                "selection_name": _selection_name_for_side(side_key, snapshot),
                "label": _result_label(side_key, snapshot),
                "price": current_price,
                "probability": round(implied_probability, 4),
                "score": total_score,
                "bookmaker_count": bookmaker_count,
                "width": width,
                "total_change": total_change,
                "step_change": step_change,
                "market_context": market_context,
                "reasons": _build_result_reasons(
                    side_key=side_key,
                    current_price=current_price,
                    bookmaker_count=bookmaker_count,
                    width=width,
                    total_change=total_change,
                    step_change=step_change,
                    market_context=market_context,
                    live_score=live_score,
                ),
                "breakdown": {
                    "favorite_bonus": round(favorite_bonus, 2),
                    "price_strength": round(price_strength, 2),
                    "gap_score": round(gap_score, 2),
                    "trend_score": round(trend_score, 2),
                    "momentum_score": round(momentum_score, 2),
                    "consensus_score": round(consensus_score, 2),
                    "market_alignment": round(market_context["score"], 2),
                    "event_score": round(event_score, 2),
                    "width_penalty": round(width_penalty, 2),
                    "draw_penalty": round(draw_penalty, 2),
                    "short_price_penalty": round(short_price_penalty, 2),
                    "underdog_penalty": round(underdog_penalty, 2),
                },
            }
        )

    return candidates, signals


def _build_play_candidates(snapshot: dict, result_candidates: list[dict], live_score: dict) -> list[dict]:
    related_markets = (snapshot.get("extra") or {}).get("related_markets") or {}
    match_profile = _build_match_profile(snapshot, result_candidates)
    plays: list[dict] = []

    best_side = _best_side_candidate(result_candidates)
    draw_candidate = next((item for item in result_candidates if item["side_key"] == "draw"), None)

    if best_side:
        direct_play = _build_match_winner_play(best_side, match_profile)
        if direct_play:
            plays.append(direct_play)

        ah_play = _build_asian_handicap_play(best_side, related_markets.get("asian_handicap") or {}, snapshot, match_profile)
        if ah_play:
            plays.append(ah_play)

        dnb_play = _build_draw_no_bet_play(best_side, related_markets.get("draw_no_bet") or {}, snapshot, match_profile)
        if dnb_play:
            plays.append(dnb_play)

        dc_play = _build_double_chance_play(best_side, related_markets.get("double_chance") or {}, snapshot, match_profile)
        if dc_play:
            plays.append(dc_play)

    if draw_candidate:
        draw_play = _build_draw_play(draw_candidate, match_profile)
        if draw_play:
            plays.append(draw_play)

    ou_play = _build_over_under_play(related_markets.get("over_under") or {}, snapshot, match_profile)
    if ou_play:
        plays.append(ou_play)

    btts_play = _build_btts_play(related_markets.get("both_teams_to_score") or {}, snapshot, match_profile)
    if btts_play:
        plays.append(btts_play)

    deduped: dict[str, dict] = {}
    for play in plays:
        key = play["full_label"]
        current = deduped.get(key)
        if current is None or play["score"] > current["score"]:
            deduped[key] = play

    return list(deduped.values())


def _build_match_winner_play(result_candidate: dict, match_profile: dict) -> dict | None:
    side_key = result_candidate["side_key"]
    price = result_candidate["price"]
    score = result_candidate["score"]
    if side_key == "draw":
        return None

    direct_score = score
    direct_score -= match_profile["draw_risk"] * 1.1
    direct_score -= 6.0 if price <= 1.52 else 2.0 if price <= 1.66 else 0.0
    direct_score -= 4.0 if match_profile["volatility"] >= 7 else 0.0
    direct_score += 3.0 if 1.68 <= price <= 2.55 else 0.0
    direct_score = _clamp(direct_score, 0.0, 100.0)

    label = _result_label(side_key, match_profile["snapshot"])
    reasons = [
        f"胜平负主方向是 {label}，当前均价 {price:.2f}。",
        f"方向基础评分 {result_candidate['score']:.0f}，盘口一致性较好。",
    ] + result_candidate["reasons"][:2]

    return _make_play(
        market_key="match_winner",
        market_label="胜平负",
        selection_name=result_candidate["selection_name"],
        label=label,
        price=price,
        score=direct_score,
        reasons=reasons,
        breakdown={
            **result_candidate["breakdown"],
            "draw_risk_penalty": round(match_profile["draw_risk"] * 1.1, 2),
        },
    )


def _build_draw_play(draw_candidate: dict, match_profile: dict) -> dict | None:
    if match_profile["draw_risk"] < 5:
        return None
    price = draw_candidate["price"]
    score = draw_candidate["score"]
    score += match_profile["draw_risk"] * 1.2
    score += 5.0 if match_profile["ou_line"] is not None and match_profile["ou_line"] <= 2.25 else 0.0
    score -= match_profile["volatility"] * 0.8
    score = _clamp(score, 0.0, 100.0)

    reasons = [
        f"平局当前均价 {price:.2f}。",
        "比赛更像低总进球和僵持型结构，适合把平局纳入正选。",
    ] + draw_candidate["reasons"][:2]

    return _make_play(
        market_key="match_winner",
        market_label="胜平负",
        selection_name="平局",
        label="平局",
        price=price,
        score=score,
        reasons=reasons,
        breakdown={
            **draw_candidate["breakdown"],
            "draw_risk_bonus": round(match_profile["draw_risk"] * 1.2, 2),
        },
    )


def _build_asian_handicap_play(best_side: dict, market: dict, snapshot: dict, match_profile: dict) -> dict | None:
    summary = market.get("summary") or {}
    line = _safe_float(market.get("active_line"))
    side_key = best_side["side_key"]
    if line is None or summary.get("line_favored_side") != side_key:
        return None

    price = _market_price(summary, side_key)
    if price is None:
        return None

    pick_line = line if side_key == "home" else -line
    score = best_side["score"]
    score += 8.0
    score += 5.0 if 1.55 <= price <= 2.18 else 2.0 if 1.42 <= price <= 2.35 else -4.0
    score += 4.0 if abs(pick_line) <= 0.75 else -5.0 if abs(pick_line) >= 1.50 else 0.0
    score += 3.5 if match_profile["draw_risk"] >= 5 else 0.0
    score -= 4.0 if match_profile["volatility"] >= 7 and abs(pick_line) >= 1.0 else 0.0
    score = _clamp(score, 0.0, 100.0)

    label = f"{_selection_name_for_side(side_key, snapshot)} {format_line(pick_line)}"
    reasons = [
        f"亚盘主线 {format_line(line)} 明确支持 {side_key_to_text(side_key)}。",
        f"该方向亚盘均价 {price:.2f}，比直接胜平负更贴合让球结构。",
    ] + best_side["reasons"][:2]

    return _make_play(
        market_key="asian_handicap",
        market_label="亚盘",
        selection_name=_selection_name_for_side(side_key, snapshot),
        label=label,
        price=price,
        score=score,
        reasons=reasons,
        breakdown={
            "base_side_score": round(best_side["score"], 2),
            "price_fit_bonus": round(5.0 if 1.55 <= price <= 2.18 else 2.0 if 1.42 <= price <= 2.35 else -4.0, 2),
            "line_bonus": round(4.0 if abs(pick_line) <= 0.75 else -5.0 if abs(pick_line) >= 1.50 else 0.0, 2),
            "draw_risk_bonus": round(3.5 if match_profile["draw_risk"] >= 5 else 0.0, 2),
        },
    )


def _build_draw_no_bet_play(best_side: dict, market: dict, snapshot: dict, match_profile: dict) -> dict | None:
    summary = market.get("summary") or {}
    side_key = best_side["side_key"]
    price = _market_price(summary, side_key)
    if price is None:
        return None

    score = best_side["score"]
    score += 5.0
    score += match_profile["draw_risk"] * 1.4
    score += 4.0 if 1.25 <= price <= 1.92 else 0.0
    score += 3.0 if best_side["price"] <= 1.58 else 0.0
    score -= 8.0 if price <= 1.15 else 3.0 if price <= 1.22 else 0.0
    score = _clamp(score, 0.0, 100.0)

    label = f"{_selection_name_for_side(side_key, snapshot)} 平退"
    reasons = [
        f"平局风险偏高时，用 DNB 代替直胜更稳。",
        f"当前 DNB 均价 {price:.2f}，可以防平。",
    ] + best_side["reasons"][:2]

    return _make_play(
        market_key="draw_no_bet",
        market_label="平局退款",
        selection_name=_selection_name_for_side(side_key, snapshot),
        label=label,
        price=price,
        score=score,
        reasons=reasons,
        breakdown={
            "base_side_score": round(best_side["score"], 2),
            "draw_risk_bonus": round(match_profile["draw_risk"] * 1.4, 2),
            "price_fit_bonus": round(4.0 if 1.25 <= price <= 1.92 else 0.0, 2),
            "short_price_penalty": round(8.0 if price <= 1.15 else 3.0 if price <= 1.22 else 0.0, 2),
        },
    )


def _build_double_chance_play(best_side: dict, market: dict, snapshot: dict, match_profile: dict) -> dict | None:
    summary = market.get("summary") or {}
    side_key = best_side["side_key"]
    outcome_key = "home_or_draw" if side_key == "home" else "away_or_draw"
    price = _market_price(summary, outcome_key)
    if price is None:
        return None

    score = best_side["score"]
    score += 2.0
    score += match_profile["draw_risk"] * 1.0
    score += 3.0 if 1.18 <= price <= 1.50 else 0.0
    score += 4.0 if best_side["score"] < 66.0 else 0.0
    score -= 10.0 if price <= 1.10 else 6.0 if price <= 1.15 else 0.0
    score = _clamp(score, 0.0, 100.0)

    label = "1X" if side_key == "home" else "X2"
    reasons = [
        f"双重机会 {label} 适合方向对但不想硬吃平局波动的场景。",
        f"当前均价 {price:.2f}，保护性强于直胜。",
    ] + best_side["reasons"][:2]

    return _make_play(
        market_key="double_chance",
        market_label="双重机会",
        selection_name=_selection_name_for_side(side_key, snapshot),
        label=label,
        price=price,
        score=score,
        reasons=reasons,
        breakdown={
            "base_side_score": round(best_side["score"], 2),
            "draw_risk_bonus": round(match_profile["draw_risk"] * 1.0, 2),
            "protection_bonus": round(4.0 if best_side["score"] < 66.0 else 0.0, 2),
            "price_penalty": round(10.0 if price <= 1.10 else 6.0 if price <= 1.15 else 0.0, 2),
        },
    )


def _build_over_under_play(market: dict, snapshot: dict, match_profile: dict) -> dict | None:
    summary = market.get("summary") or {}
    line = _safe_float(market.get("active_line"))
    lean = summary.get("lean")
    strength = float(summary.get("lean_strength") or 0.0)
    if line is None or lean not in {"over", "under"}:
        return None

    price = _market_price(summary, lean)
    if price is None:
        return None

    if strength < 0.08:
        return None

    score = 46.0 + strength * 90.0
    if lean == "over":
        score += 6.0 if 2.0 <= line <= 3.0 else -4.0 if line > 3.5 else 0.0
        score += match_profile["volatility"] * 0.9
        score += 4.0 if match_profile["btts_lean"] == "yes" else 0.0
        score -= 4.0 if match_profile["favorite_dominance"] >= 7 and match_profile["btts_lean"] == "no" else 0.0
        label = f"大 {line:.2f}"
        reasons = [
            f"大小球主线 {line:.2f} 当前更偏向大球。",
            f"大球均价 {price:.2f}，市场偏向强度 {strength:.2f}。",
        ]
    else:
        score += 5.0 if line >= 2.50 else 1.0 if line >= 2.25 else -5.0
        score += match_profile["draw_risk"] * 0.8
        score += 4.0 if match_profile["btts_lean"] == "no" else 0.0
        score += 3.0 if match_profile["favorite_dominance"] >= 7 else 0.0
        label = f"小 {line:.2f}"
        reasons = [
            f"大小球主线 {line:.2f} 当前更偏向小球。",
            f"小球均价 {price:.2f}，适合低节奏或强弱分明的场次。",
        ]

    score += 3.0 if 1.55 <= price <= 2.20 else -3.0 if price <= 1.35 else 0.0
    score = _clamp(score, 0.0, 100.0)

    return _make_play(
        market_key="over_under",
        market_label="大小球",
        selection_name=label,
        label=label,
        price=price,
        score=score,
        reasons=reasons,
        breakdown={
            "lean_strength": round(strength * 90.0, 2),
            "volatility_bonus": round(match_profile["volatility"] * 0.9 if lean == "over" else match_profile["draw_risk"] * 0.8, 2),
            "line_bonus": round(6.0 if lean == "over" and 2.0 <= line <= 3.0 else 5.0 if lean == "under" and line >= 2.50 else 0.0, 2),
        },
    )


def _build_btts_play(market: dict, snapshot: dict, match_profile: dict) -> dict | None:
    summary = market.get("summary") or {}
    lean = summary.get("lean")
    strength = float(summary.get("lean_strength") or 0.0)
    if lean not in {"yes", "no"} or strength < 0.06:
        return None

    price = _market_price(summary, lean)
    if price is None:
        return None

    score = 44.0 + strength * 92.0
    if lean == "yes":
        score += match_profile["volatility"] * 0.8
        score += 4.0 if match_profile["ou_lean"] == "over" else 0.0
        score -= 5.0 if match_profile["favorite_dominance"] >= 7 else 0.0
        label = "是"
        reasons = [
            f"BTTS 当前偏向 是，均价 {price:.2f}。",
            "更适合双方都能制造进球的开放型比赛。",
        ]
    else:
        score += match_profile["draw_risk"] * 0.4
        score += 4.0 if match_profile["ou_lean"] == "under" else 0.0
        score += 5.0 if match_profile["favorite_dominance"] >= 7 else 0.0
        label = "否"
        reasons = [
            f"BTTS 当前偏向 否，均价 {price:.2f}。",
            "更适合单边压制或低总进球比赛。",
        ]

    score += 2.0 if 1.50 <= price <= 2.20 else -3.0 if price <= 1.35 else 0.0
    score = _clamp(score, 0.0, 100.0)

    return _make_play(
        market_key="both_teams_to_score",
        market_label="BTTS",
        selection_name=label,
        label=label,
        price=price,
        score=score,
        reasons=reasons,
        breakdown={
            "lean_strength": round(strength * 92.0, 2),
            "profile_bonus": round(match_profile["volatility"] * 0.8 if lean == "yes" else match_profile["favorite_dominance"] * 0.7, 2),
        },
    )


def _make_play(
    market_key: str,
    market_label: str,
    selection_name: str,
    label: str,
    price: float,
    score: float,
    reasons: list[str],
    breakdown: dict[str, Any],
) -> dict[str, Any]:
    final_score = round(_clamp(score, 0.0, 100.0), 2)
    return {
        "market_key": market_key,
        "market_label": market_label,
        "selection_name": selection_name,
        "label": label,
        "full_label": f"{market_label} {label}",
        "price": round(price, 3),
        "score": final_score,
        "confidence_label": label_by_score(final_score),
        "signal": "bullish" if final_score >= 66 else "neutral",
        "reasons": reasons[:5],
        "breakdown": breakdown,
    }


def _serialize_play(play: dict[str, Any]) -> dict[str, Any]:
    return {
        "market_key": play["market_key"],
        "market_label": play["market_label"],
        "selection_name": play["selection_name"],
        "label": play["label"],
        "full_label": play["full_label"],
        "price": play["price"],
        "score": play["score"],
        "confidence_label": play["confidence_label"],
        "signal": play["signal"],
        "reasons": play["reasons"],
    }


def _build_stake_plan(primary_play: dict[str, Any] | None, risk_level: str) -> dict[str, Any]:
    if not primary_play or float(primary_play.get("score") or 0.0) < 54.0:
        return {
            "level": "放弃",
            "units": 0.0,
            "max_bankroll_pct": 0.0,
            "summary": "放弃，继续观察盘口。",
            "reason": "当前优势还没达到可执行阈值，不建议强行下注。",
        }

    score = float(primary_play.get("score") or 0.0)
    price = float(primary_play.get("price") or 0.0)

    base_units = 0.45 if score < 62 else 0.75 if score < 74 else 1.0 if score < 84 else 1.2
    risk_factor = {"Low": 1.0, "Medium": 0.85, "High": 0.65}.get(risk_level, 0.75)

    price_factor = 1.0
    price_reason = "赔率处在正常执行区间。"
    if 1.45 <= price <= 2.35:
        price_factor = 1.05
        price_reason = "赔率落在主执行区间，收益和容错更平衡。"
    elif 0 < price <= 1.20:
        price_factor = 0.75
        price_reason = "赔率偏薄，即使方向正确，收益弹性也有限。"
    elif price >= 3.40:
        price_factor = 0.78
        price_reason = "赔率偏高，兑现路径更窄，仓位需要收缩。"

    units = round(_clamp(base_units * risk_factor * price_factor, 0.0, 1.5), 2)
    bankroll_pct = round(units, 2)

    if units <= 0.0:
        level = "放弃"
    elif units < 0.6:
        level = "试探仓"
    elif units < 1.0:
        level = "标准仓"
    else:
        level = "进取仓"

    risk_reason = {
        "Low": "整体盘口分歧不大，可以按正常仓位执行。",
        "Medium": "盘口仍有一些波动，仓位按中性折扣处理。",
        "High": "当前波动和分歧都偏大，只保留压缩后的仓位。",
    }.get(risk_level, "风险状态不明，先按保守仓位处理。")

    return {
        "level": level,
        "units": units,
        "max_bankroll_pct": bankroll_pct,
        "summary": f"{level} {units:.2f}u，单场上限 {bankroll_pct:.2f}% 资金。",
        "reason": f"评分 {score:.0f} 分，{risk_reason}{price_reason}",
    }


def _build_why_not_others(
    best: dict[str, Any],
    alternatives: Sequence[dict[str, Any]],
    match_profile: dict[str, Any],
    risk_level: str,
) -> list[dict[str, Any]]:
    rows = []
    for alternative in alternatives[:4]:
        rows.append(
            {
                "market_key": alternative["market_key"],
                "market_label": alternative["market_label"],
                "full_label": alternative["full_label"],
                "selection_name": alternative["selection_name"],
                "price": round(float(alternative["price"]), 3),
                "score": round(float(alternative["score"]), 2),
                "score_gap": round(float(best["score"]) - float(alternative["score"]), 2),
                "reason": _why_not_reason(best, alternative, match_profile, risk_level),
            }
        )
    return rows


def _why_not_reason(
    best: dict[str, Any],
    alternative: dict[str, Any],
    match_profile: dict[str, Any],
    risk_level: str,
) -> str:
    score_gap = round(float(best["score"]) - float(alternative["score"]), 2)
    alt_market = alternative["market_key"]
    best_market = best["market_key"]
    alt_price = float(alternative.get("price") or 0.0)
    best_price = float(best.get("price") or 0.0)

    if alt_price <= 1.14:
        return f"赔率只有 {alt_price:.2f}，保护是有了，但回报太薄，不值得排在主推前面。"

    if alt_market == best_market:
        if alt_price < best_price:
            return f"同属 {alternative['market_label']}，但赔率只有 {alt_price:.2f}，性价比不如主推。"
        return f"同属 {alternative['market_label']}，综合评分比主推低 {score_gap:.0f} 分，优先级自然后移。"

    if alt_market in {"double_chance", "draw_no_bet"} and best_market not in {"double_chance", "draw_no_bet"}:
        return f"保护性更强，但赔率被压到 {alt_price:.2f}，为当前这点不确定性牺牲了太多回报。"

    if best_market in {"double_chance", "draw_no_bet"} and alt_market == "match_winner":
        return "赔率会更高，但当前平局风险还没被吃掉，直接走胜平负的波动大于主推。"

    if alt_market == "match_winner":
        if match_profile["draw_risk"] >= 5 and best_market != "match_winner":
            return "直胜回报更直接，但这场平局风险偏高，主推更重视防平和容错。"
        if alt_price <= 1.35:
            return f"赔率 {alt_price:.2f} 偏薄，哪怕方向没错，单位风险回报也弱于主推。"
        return f"赛果侧方向没错，但综合评分仍比主推低 {score_gap:.0f} 分。"

    if alt_market == "asian_handicap":
        if match_profile["volatility"] >= 7:
            return "让球玩法要同时满足赢球幅度，这场波动偏大，兑现条件比主推更苛刻。"
        if abs(float(match_profile.get("ah_line") or 0.0)) >= 1.0:
            return "让步已经不浅，需要净胜幅度配合，容错不如主推。"
        return "亚盘方向是对的，但让球兑现路径更窄，综合容错还是主推更好。"

    if alt_market == "over_under":
        if best_market != "over_under":
            return "总进球有倾向，但强度没有主推这条线那么集中，只能排在第二梯队。"
        return f"同样是大小球，但当前这条线评分比主推低 {score_gap:.0f} 分。"

    if alt_market == "both_teams_to_score":
        return "BTTS 需要两队的进球路径同时兑现，前提条件比主推更多，容错更低。"

    if alt_price >= 3.40:
        return f"赔率虽然更高，但命中路径更窄，波动会明显大于主推。"

    if risk_level == "High":
        return f"当前整体风险本来就偏高，这个玩法比主推少了 {score_gap:.0f} 分，不值得放到第一顺位。"

    return f"综合评分比主推低 {score_gap:.0f} 分，赔率和容错的平衡都不如主推。"


def _build_result_reasons(
    side_key: str,
    current_price: float,
    bookmaker_count: int,
    width: float,
    total_change: float,
    step_change: float,
    market_context: dict[str, Any],
    live_score: dict,
) -> list[str]:
    reasons = [
        f"{side_key_to_text(side_key)}方向当前均价 {current_price:.2f}，可用赔率源 {bookmaker_count} 家，离散度 {width:.2f}。",
    ]
    if total_change > 0:
        reasons.append(
            f"从开盘到现在赔率回落 {total_change * 100:.1f}%，最近一跳再回落 {step_change * 100:.1f}%。"
        )
    elif total_change < 0:
        reasons.append(f"从开盘到现在赔率上浮 {abs(total_change) * 100:.1f}%，支持力度有所回落。")
    else:
        reasons.append("当前更多依赖横向盘口结构，而不是历史趋势。")

    reasons.extend(market_context.get("reasons") or [])
    reasons.extend(market_context.get("warnings") or [])

    event_reason = _event_reason(side_key, live_score)
    if event_reason:
        reasons.append(event_reason)
    return reasons


def _build_match_profile(snapshot: dict, result_candidates: list[dict]) -> dict[str, Any]:
    related_markets = (snapshot.get("extra") or {}).get("related_markets") or {}
    ordered = _ordered_runners(snapshot)
    favorite_price = ordered[0]["price"] if ordered else 99.0
    second_price = ordered[1]["price"] if len(ordered) > 1 else favorite_price
    gap = max(0.0, second_price - favorite_price)

    ou_summary = ((related_markets.get("over_under") or {}).get("summary")) or {}
    ou_line = _safe_float((related_markets.get("over_under") or {}).get("active_line"))
    ah_summary = ((related_markets.get("asian_handicap") or {}).get("summary")) or {}
    ah_line = _safe_float((related_markets.get("asian_handicap") or {}).get("active_line"))
    btts_summary = ((related_markets.get("both_teams_to_score") or {}).get("summary")) or {}

    draw_risk = 0.0
    if ou_line is not None:
        if ou_line <= 2.25:
            draw_risk += 4.0
        elif ou_line <= 2.50:
            draw_risk += 2.0
    if ah_line is not None:
        if abs(ah_line) <= 0.25:
            draw_risk += 3.0
        elif abs(ah_line) <= 0.50:
            draw_risk += 1.0
    if gap <= 0.35:
        draw_risk += 2.0

    volatility = 0.0
    if ou_line is not None:
        if ou_line >= 3.25:
            volatility += 4.0
        elif ou_line >= 2.75:
            volatility += 2.0
    widths = [float(item.get("width") or 0.0) for item in result_candidates]
    if widths and max(widths) >= 0.18:
        volatility += 2.0
    if btts_summary.get("lean") == "yes":
        volatility += 2.0

    favorite_dominance = 0.0
    if favorite_price <= 1.55:
        favorite_dominance += 5.0
    elif favorite_price <= 1.75:
        favorite_dominance += 3.0
    if gap >= 0.60:
        favorite_dominance += 2.0
    if ah_summary.get("line_favored_side") == _favorite_side(snapshot) and ah_line is not None and abs(ah_line) >= 0.50:
        favorite_dominance += 3.0

    return {
        "snapshot": snapshot,
        "ou_line": ou_line,
        "ou_lean": ou_summary.get("lean"),
        "ou_strength": float(ou_summary.get("lean_strength") or 0.0),
        "ah_line": ah_line,
        "ah_favored_side": ah_summary.get("line_favored_side"),
        "btts_lean": btts_summary.get("lean"),
        "draw_risk": draw_risk,
        "volatility": volatility,
        "favorite_dominance": favorite_dominance,
    }


def _best_side_candidate(result_candidates: list[dict]) -> dict | None:
    sides = [item for item in result_candidates if item["side_key"] in {"home", "away"}]
    if not sides:
        return None
    return max(sides, key=lambda item: item["score"])


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


def _result_gap_score(side_key: str, ordered: list[dict], current_price: float) -> float:
    if not ordered:
        return 0.0

    current_index = next((index for index, item in enumerate(ordered) if item["side_key"] == side_key), len(ordered) - 1)
    if current_index == 0 and len(ordered) > 1:
        nearest_gap = max(0.0, ordered[1]["price"] - current_price)
    elif current_index > 0:
        nearest_gap = max(0.0, current_price - ordered[current_index - 1]["price"])
    else:
        nearest_gap = 0.0
    return _clamp(nearest_gap * 10.0, 0.0, 16.0)


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
            reasons.append(f"亚盘主线 {format_line(ah_line)} 支持 {side_key_to_text(side_key)}。")
        elif ah_side and ah_side != "balanced":
            penalty = 5.0 + min(abs(ah_line) * 6.0, 6.0)
            score -= penalty
            warnings.append(f"亚盘主线 {format_line(ah_line)} 更支持 {side_key_to_text(ah_side)}，与当前方向不一致。")

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
                score += 2.0
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

    dnb = related_markets.get("draw_no_bet") or {}
    dnb_summary = dnb.get("summary") or {}
    dnb_lean = dnb_summary.get("lean")
    if side_key in {"home", "away"} and dnb_lean == side_key:
        score += 2.0

    return {
        "score": round(score, 2),
        "reasons": reasons,
        "warnings": warnings,
    }


def _market_structure_signals(snapshot: dict) -> list[dict]:
    signals: list[dict] = []
    related_markets = (snapshot.get("extra") or {}).get("related_markets") or {}
    match_summary = ((related_markets.get("match_winner") or {}).get("summary")) or {}
    ah_summary = ((related_markets.get("asian_handicap") or {}).get("summary")) or {}
    dnb_summary = ((related_markets.get("draw_no_bet") or {}).get("summary")) or {}
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

    if favorite_side and dnb_summary.get("lean") and dnb_summary.get("lean") != favorite_side:
        signals.append(
            {
                "type": "neutral",
                "severity": "medium",
                "title": "DNB 与主方向有分歧",
                "detail": f"胜平负偏向 {side_key_to_text(favorite_side)}，但平退盘口更偏向 {side_key_to_text(dnb_summary.get('lean'))}。",
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


def _empty_recommendation(
    market_id: str,
    now: datetime,
    signals: list[dict],
    reasons: list[str],
    plays: list[dict],
    primary_play: dict[str, Any] | None = None,
    stake_plan: dict[str, Any] | None = None,
    why_not_others: list[dict[str, Any]] | None = None,
) -> dict:
    return {
        "market_id": market_id,
        "recommendation": "不下注",
        "selection_name": "",
        "market_label": "多玩法",
        "score": 0.0,
        "confidence_label": "不下",
        "risk_level": "High",
        "reasons": reasons[:5],
        "breakdown": {},
        "signal": "neutral",
        "generated_at": now,
        "signals": signals,
        "plays": plays,
        "primary_play": primary_play,
        "stake_plan": stake_plan or _build_stake_plan(None, "High"),
        "why_not_others": why_not_others or [],
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


def _market_price(summary: dict[str, Any], key: str) -> float | None:
    return _safe_float(summary.get(f"avg_{key}") or summary.get(f"best_{key}"))


def _selection_name_for_side(side_key: str, snapshot: dict) -> str:
    if side_key == "home":
        return snapshot.get("home_name", "主队")
    if side_key == "away":
        return snapshot.get("away_name", "客队")
    return "平局"


def _result_label(side_key: str, snapshot: dict) -> str:
    if side_key == "home":
        return "主胜"
    if side_key == "away":
        return "客胜"
    return "平局"


def _favorite_side(snapshot: dict) -> str:
    ordered = _ordered_runners(snapshot)
    return ordered[0]["side_key"] if ordered else "balanced"


def side_key_to_text(side_key: str) -> str:
    return {
        "home": "主队",
        "draw": "平局",
        "away": "客队",
        "balanced": "均衡",
        "over": "大球",
        "under": "小球",
        "yes": "是",
        "no": "否",
        "home_or_draw": "1X",
        "home_or_away": "12",
        "away_or_draw": "X2",
    }.get(side_key, side_key or "未知")


def format_line(line: float) -> str:
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
