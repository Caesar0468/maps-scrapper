#!/usr/bin/env python3
"""CLI pipeline orchestrator: Scrape → Menu → Scour → LLM → Database."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv
load_dotenv()

import database as db
from pipeline.analyzer import batch_analyze, check_ollama_available
from scraper.gmaps_scraper import run_scraper
from scraper.social_scourer import scour_restaurant

DATA_DIR = Path(__file__).parent / "data"
SAMPLE_FILE = DATA_DIR / "sample_restaurants.json"


def seed_sample_data() -> list[dict[str, Any]]:
    """Provide demo restaurants when scraping is skipped."""
    if SAMPLE_FILE.exists():
        try:
            return json.loads(SAMPLE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    return [
        {
            "name": "Paradise Biryani",
            "rating": 4.2,
            "review_count": 18500,
            "locality": "Secunderabad",
            "address": "MG Road, Secunderabad, Hyderabad",
            "latitude": 17.4399,
            "longitude": 78.4983,
            "phone": "+91 40 2784 3111",
            "website": "https://paradisebiryani.com",
            "google_maps_url": "https://www.google.com/maps/place/Paradise+Biryani",
            "opening_hours": ["Mon-Sun: 11:00 AM – 11:00 PM"],
            "is_open_now": True,
            "raw_menu": [
                {"category": "Biryani", "name": "Chicken Biryani", "price": "₹320"},
                {"category": "Biryani", "name": "Mutton Biryani", "price": "₹420"},
            ],
            "menu_source": "Google Maps Menu Tab",
            "metadata_sources": {
                "phone": {"value": "+91 40 2784 3111", "source": "Google Maps Listing Header"},
                "website": {"value": "https://paradisebiryani.com", "source": "Google Maps Place Button"},
            },
        },
        {
            "name": "Chutneys",
            "rating": 4.3,
            "review_count": 8200,
            "locality": "Jubilee Hills",
            "address": "Road No. 36, Jubilee Hills, Hyderabad",
            "latitude": 17.4226,
            "longitude": 78.4071,
            "phone": "+91 40 2355 8000",
            "google_maps_url": "https://www.google.com/maps/place/Chutneys",
            "opening_hours": ["Mon-Sun: 7:00 AM – 11:00 PM"],
            "is_open_now": True,
            "raw_menu": [
                {"category": "Tiffins", "name": "Masala Dosa", "price": "₹180"},
                {"category": "Tiffins", "name": "Pesarattu", "price": "₹160"},
            ],
            "menu_source": "Google Maps Menu Tab",
            "metadata_sources": {
                "phone": {"value": "+91 40 2355 8000", "source": "Google Maps Listing Header"},
            },
        },
        {
            "name": "Bawarchi RTC",
            "rating": 4.1,
            "review_count": 12000,
            "locality": "Nallakunta",
            "address": "RTC Cross Roads, Nallakunta, Hyderabad",
            "latitude": 17.4014,
            "longitude": 78.5114,
            "google_maps_url": "https://www.google.com/maps/place/Bawarchi",
            "opening_hours": ["Mon-Sun: 11:30 AM – 11:30 PM"],
            "is_open_now": False,
            "raw_menu": [
                {"category": "Biryani", "name": "Special Mutton Biryani", "price": "₹380"},
            ],
            "menu_source": "Google Maps Menu Tab",
        },
    ]


def run_full_pipeline(
    max_targets: int = 5,
    skip_scrape: bool = False,
    skip_social: bool = False,
    skip_llm: bool = False,
    model: str = "qwen3:8b",
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> int:
    def report(stage: str, **kwargs):
        payload = {"stage": stage, **kwargs}
        print(f"[{stage}] {kwargs}")
        if progress_callback:
            progress_callback(payload)

    def make_callback(stage: str):
        def cb(data: dict[str, Any]):
            if progress_callback:
                progress_callback({"stage": stage, **data})
        return cb

    conn = db.init_db()
    try:
        report("scrape", message="Starting scrape phase")
        if skip_scrape:
            places = seed_sample_data()
            report("scrape", message=f"Using {len(places)} sample restaurants")
        else:
            places = run_scraper(
                max_targets=max_targets,
                skip_details=False,
                progress_callback=make_callback("scrape"),
            )
            report("scrape", message=f"Scraped {len(places)} places")

        social_contexts: dict[int, dict] = {}
        if not skip_social:
            report("social", message="Scouring Reddit & DuckDuckGo")
            for idx, place in enumerate(places):
                try:
                    if progress_callback:
                        progress_callback({
                            "stage": "social",
                            "current": idx + 1,
                            "total": len(places),
                            "name": place.get("name", ""),
                            "message": f"Scouring social for {place.get('name', '')} ({idx+1}/{len(places)})"
                        })
                    result = scour_restaurant(place)
                    social_contexts[idx] = result.get("social_context", {})
                except Exception as exc:
                    print(f"  Social scour failed for {place.get('name')}: {exc}")

        if not skip_llm:
            ollama_ok = check_ollama_available(model)
            report("llm", message=f"Ollama available: {ollama_ok}, model: {model}")
            places = batch_analyze(
                places,
                social_contexts,
                model=model,
                progress_callback=make_callback("llm"),
            )
        else:
            report("llm", message="Skipping LLM analysis")

        report("database", message="Saving to SQLite")
        for idx, place in enumerate(places):
            if idx in social_contexts:
                place["social_context"] = social_contexts[idx]
            db.upsert_restaurant(conn, place)

        report("done", message=f"Pipeline complete — {len(places)} restaurants saved")
        return len(places)
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="HY Food Intel Pipeline")
    parser.add_argument("--max-targets", type=int, default=5, help="Max scrape targets")
    parser.add_argument("--skip-scrape", action="store_true", help="Use sample data instead of scraping")
    parser.add_argument("--skip-social", action="store_true", help="Skip Reddit/DDG scour")
    parser.add_argument("--skip-llm", action="store_true", help="Skip Ollama analysis")
    parser.add_argument("--model", default=None, help="Model name for LLM (defaults to provider default)")
    args = parser.parse_args()

    count = run_full_pipeline(
        max_targets=args.max_targets,
        skip_scrape=args.skip_scrape,
        skip_social=args.skip_social,
        skip_llm=args.skip_llm,
        model=args.model,
    )
    print(f"\n✅ Saved {count} restaurants to {db.DB_PATH}")
    sys.exit(0)


if __name__ == "__main__":
    main()