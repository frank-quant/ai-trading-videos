from pathlib import Path
import json

price = 667.10
shares_m = 404.464340
free_float_m = 30.09
consensus_eps_fy26 = 1.68
market_cap_yi = price * shares_m / 100
required_return = 0.12
years = 2
exit_multiple_low = 60
exit_multiple_high = 100
required_np = {
    "at_100x": market_cap_yi * (1 + required_return) ** years / exit_multiple_high,
    "at_60x": market_cap_yi * (1 + required_return) ** years / exit_multiple_low,
}
scenarios = {
    "downside": {"prob": 0.30, "np_2028": 12.68, "exit_pe": 45},
    "base": {"prob": 0.50, "np_2028": 22.37, "exit_pe": 60},
    "upside": {"prob": 0.20, "np_2028": 32.02, "exit_pe": 100},
}
weighted_price = 0
for s in scenarios.values():
    s["future_value_yi"] = s["np_2028"] * s["exit_pe"]
    s["pv_yi"] = s["future_value_yi"] / (1 + required_return) ** years
    s["value_per_share"] = s["pv_yi"] * 100 / shares_m
    s["upside_pct"] = (s["value_per_share"] / price - 1) * 100
    weighted_price += s["prob"] * s["value_per_share"]
metrics = {
    "price_cny": price,
    "shares_m": shares_m,
    "market_cap_yi": market_cap_yi,
    "free_float_pct": free_float_m / shares_m * 100,
    "pe_ttm_x": 482.188,
    "pe_fy2026_consensus_x": price / consensus_eps_fy26,
    "human_quad_share_2025_pct": 51.78 + 41.62,
    "human_asp_decline_pct": (16.64 / 59.34 - 1) * 100,
    "profit_gap_2025_yi": 5.907528 - 2.782105,
    "forecast_2028_high_low_x": 22.3718 / 12.68,
    "required_return": required_return,
    "discount_years": years,
    "required_np_2028_yi": required_np,
    "required_np_vs_low_forecast_pct": (required_np["at_60x"] / 12.68 - 1) * 100,
    "required_np_vs_high_forecast_pct": (required_np["at_100x"] / 22.3718 - 1) * 100,
    "scenarios": scenarios,
    "probability_weighted_price": weighted_price,
    "probability_weighted_upside_pct": (weighted_price / price - 1) * 100,
    "price_to_ipo_pct": (price / 150.80 - 1) * 100,
    "price_to_first_open_pct": (price / 1100.0 - 1) * 100,
    "price_to_listing_low_pct": (price / 404.03 - 1) * 100,
}
out = Path(__file__).resolve().parent / "calculated_metrics.json"
out.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(metrics, ensure_ascii=False, indent=2))
