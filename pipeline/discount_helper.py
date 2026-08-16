"""Pre-booking deal deep-links for Swiggy Dineout and Zomato Gold."""

from __future__ import annotations

from urllib.parse import quote_plus


def swiggy_dineout_url(restaurant_name: str, locality: str = "Hyderabad") -> str:
    query = quote_plus(f"{restaurant_name} {locality}")
    return f"https://www.swiggy.com/restaurants/{query}"


def zomato_gold_url(restaurant_name: str, locality: str = "Hyderabad") -> str:
    query = quote_plus(f"{restaurant_name} {locality}")
    return f"https://www.zomato.com/hyderabad/restaurants/{query}"


def get_deal_links(restaurant: dict) -> dict[str, str]:
    name = restaurant.get("name", "")
    locality = restaurant.get("locality", "Hyderabad")
    return {
        "swiggy_dineout": swiggy_dineout_url(name, locality),
        "zomato_gold": zomato_gold_url(name, locality),
    }


def whatsapp_share_text(restaurant: dict) -> str:
    ai = restaurant.get("ai_analysis") or {}
    if isinstance(ai, str):
        import json
        try:
            ai = json.loads(ai)
        except Exception:
            ai = {}

    # FIX: handle None review_count
    review_count = restaurant.get('review_count') or 0
    lines = [
        f"🍽️ *{restaurant.get('name')}* — {restaurant.get('locality', 'Hyderabad')}",
        f"⭐ {restaurant.get('rating', 'N/A')} ({review_count:,} reviews)",
        f"💰 ~₹{ai.get('calculated_spend_for_two', '?')} for two ({ai.get('budget_tier', '')})",
        f"🔥 Hype: {ai.get('hype_verdict', 'N/A')} (Score: {ai.get('hype_score', '?')}/100)",
        f"🥗 Dietary: {ai.get('dietary_warning', 'None')}",
    ]
    must_try = ai.get("must_try_items", [])
    if must_try:
        lines.append(f"✅ Must Try: {', '.join(must_try[:3])}")
    if restaurant.get("google_maps_url"):
        lines.append(f"📍 {restaurant['google_maps_url']}")
    lines.append("\nShared via HY Food Intel 🗺️")
    return "\n".join(lines)


def whatsapp_share_url(restaurant: dict) -> str:
    text = quote_plus(whatsapp_share_text(restaurant))
    return f"https://wa.me/?text={text}"