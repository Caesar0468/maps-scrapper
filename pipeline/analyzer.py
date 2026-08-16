"""Restaurant analyzer using multi‑provider LLM."""
from __future__ import annotations

import json
import re
import time
from typing import Any

import httpx

from pipeline.llm_client import LLMClient

SYSTEM_PROMPT = """You are a Hyderabad food intelligence analyst. Analyze the restaurant using ONLY the provided data.
Respond with ONLY valid JSON matching this exact schema (no markdown, no extra text):
{
  "hype_score": 0-100 integer,
  "hype_verdict": "Overhyped | Justified Hype | Hidden Gem | Reliable Classic",
  "hype_analysis_summary": "2-sentence breakdown comparing internet hype vs real food quality.",
  "fake_review_risk": "Low | Moderate | High",
  "fake_review_reasons": "Why reviews appear genuine or astroturfed.",
  "cuisines": ["list of cuisines"],
  "calculated_spend_for_two": integer INR,
  "budget_tier": "Budget (<₹500) | Moderate (₹500-₹1200) | Premium (₹1200-₹2500) | Fine Dining (₹2500+)",
  "dietary_suitability": "Pure Veg | Non-Veg Specialty | Balanced",
  "dietary_warning": "Avoid Veg Here | Avoid Non-Veg Here | Both Recommended | None",
  "dietary_warning_remarks": "Detailed dietary reasoning.",
  "must_try_items": ["dishes"],
  "skip_items": ["dishes to avoid"],
  "red_flags": ["operational warnings"],
  "vibe_tags": ["ambiance tags"],
  "is_pure_veg": boolean,
  "open_late_night": boolean
}"""

SCHEMA_DEFAULTS: dict[str, Any] = {
    "hype_score": 50,
    "hype_verdict": "Reliable Classic",
    "hype_analysis_summary": "Insufficient data for detailed hype analysis.",
    "fake_review_risk": "Moderate",
    "fake_review_reasons": "Not enough social context to assess review authenticity.",
    "cuisines": ["Multi-Cuisine"],
    "calculated_spend_for_two": 800,
    "budget_tier": "Moderate (₹500-₹1200)",
    "dietary_suitability": "Balanced",
    "dietary_warning": "None",
    "dietary_warning_remarks": "",
    "must_try_items": [],
    "skip_items": [],
    "red_flags": [],
    "vibe_tags": ["Family Dining"],
    "is_pure_veg": False,
    "open_late_night": False,
}


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "y")
    return bool(value)


def _build_prompt(restaurant: dict[str, Any], social_context: dict[str, Any] | None) -> str:
    menu_items = restaurant.get("raw_menu") or restaurant.get("raw_menu_json") or []
    if isinstance(menu_items, str):
        try:
            menu_items = json.loads(menu_items)
        except json.JSONDecodeError:
            menu_items = []

    parts = [
        f"Restaurant: {restaurant.get('name')}",
        f"Rating: {restaurant.get('rating')} ({restaurant.get('review_count')} reviews)",
        f"Locality: {restaurant.get('locality')}",
        f"Address: {restaurant.get('address', 'N/A')}",
        f"Menu source: {restaurant.get('menu_source', 'N/A')}",
        f"Menu items sample: {json.dumps(menu_items[:15], ensure_ascii=False)}",
    ]
    if social_context:
        parts.append(f"Social context:\n{social_context.get('summary_text', '')[:4000]}")
    return "\n".join(parts)


def _extract_json(text: str) -> dict[str, Any]:
    text = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            return json.loads(match.group(0))
        raise


def _validate_schema(data: dict[str, Any]) -> dict[str, Any]:
    result = dict(SCHEMA_DEFAULTS)
    result.update({k: v for k, v in data.items() if k in SCHEMA_DEFAULTS})

    verdicts = {"Overhyped", "Justified Hype", "Hidden Gem", "Reliable Classic"}
    if result["hype_verdict"] not in verdicts:
        result["hype_verdict"] = "Reliable Classic"

    risks = {"Low", "Moderate", "High"}
    if result["fake_review_risk"] not in risks:
        result["fake_review_risk"] = "Moderate"

    warnings = {"Avoid Veg Here", "Avoid Non-Veg Here", "Both Recommended", "None"}
    if result["dietary_warning"] not in warnings:
        result["dietary_warning"] = "None"

    try:
        result["hype_score"] = max(0, min(100, int(result["hype_score"])))
    except (TypeError, ValueError):
        result["hype_score"] = 50

    try:
        result["calculated_spend_for_two"] = int(result["calculated_spend_for_two"])
    except (TypeError, ValueError):
        result["calculated_spend_for_two"] = 800

    for list_key in ("cuisines", "must_try_items", "skip_items", "red_flags", "vibe_tags"):
        if not isinstance(result[list_key], list):
            result[list_key] = SCHEMA_DEFAULTS[list_key]

    result["is_pure_veg"] = _to_bool(result.get("is_pure_veg", False))
    result["open_late_night"] = _to_bool(result.get("open_late_night", False))
    return result


def _heuristic_analysis(restaurant: dict[str, Any]) -> dict[str, Any]:
    name_lower = (restaurant.get("name") or "").lower()
    rating = restaurant.get("rating") or 4.0
    reviews = restaurant.get("review_count") or 1000

    cuisines = []
    if any(w in name_lower for w in ("biryani", "paradise", "shah ghouse", "bawarchi")):
        cuisines = ["Hyderabadi", "Biryani", "Mughlai"]
    elif any(w in name_lower for w in ("dosa", "tiffins", "south")):
        cuisines = ["South Indian"]
    elif any(w in name_lower for w in ("veg", "sattvik", "temple")):
        cuisines = ["Pure Veg", "South Indian"]
    else:
        cuisines = ["Multi-Cuisine"]

    is_pure_veg = any(w in name_lower for w in ("veg", "sattvik", "temple", "santhosh"))
    dietary_warning = "None"
    remarks = ""
    if "biryani" in name_lower or "mutton" in name_lower:
        dietary_warning = "Avoid Veg Here"
        remarks = "Specializes in meat biryanis; vegetarian options may share kitchen equipment."

    hype_score = min(95, int(rating * 15 + min(reviews / 500, 20)))
    fake_risk = "Low" if reviews > 5000 else "Moderate"

    return {
        "cuisines": cuisines,
        "hype_score": hype_score,
        "hype_verdict": "Reliable Classic" if rating >= 4.3 else "Justified Hype",
        "fake_review_risk": fake_risk,
        "is_pure_veg": is_pure_veg,
        "dietary_warning": dietary_warning,
        "dietary_warning_remarks": remarks,
        "calculated_spend_for_two": 600 if "budget" in name_lower else 900,
        "budget_tier": "Moderate (₹500-₹1200)",
        "must_try_items": [],
        "skip_items": [],
        "red_flags": [],
        "vibe_tags": ["Family Dining"],
        "open_late_night": False,
    }


def analyze_restaurant(restaurant: dict[str, Any], social_context: dict[str, Any] | None = None, model: str | None = None) -> dict[str, Any]:
    prompt = _build_prompt(restaurant, social_context)
    try:
        client = LLMClient(SYSTEM_PROMPT)
        parsed = client.complete_json(prompt, model=model)
        return _validate_schema(parsed)
    except Exception as exc:
        fallback = _validate_schema({})
        fallback["hype_analysis_summary"] = f"LLM analysis unavailable: {exc}. Using heuristic defaults."
        fallback.update(_heuristic_analysis(restaurant))
        return fallback


def batch_analyze(restaurants, social_contexts=None, model=None, progress_callback=None):
    social_contexts = social_contexts or {}
    results = []
    total = len(restaurants)
    for idx, restaurant in enumerate(restaurants, start=1):
        name = restaurant.get("name", "")
        ctx = social_contexts.get(idx - 1)
        if progress_callback:
            progress_callback({"current": idx, "total": total, "name": name, "message": f"Analyzing {name} ({idx}/{total})"})
        analysis = analyze_restaurant(restaurant, ctx, model=model)
        enriched = dict(restaurant)
        enriched["ai_analysis"] = analysis
        results.append(enriched)
        time.sleep(0.5)
    return results


def check_ollama_available(model: str = "qwen3:8b") -> bool:
    """Check if local Ollama is available and has the model."""
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get("http://localhost:11434/api/tags")
            if resp.status_code != 200:
                return False
            models = [m["name"] for m in resp.json().get("models", [])]
            return any(model in m for m in models)
    except Exception:
        return False