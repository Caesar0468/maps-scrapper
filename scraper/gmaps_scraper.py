"""Playwright Google Maps scraper with metadata, hours, phone, and source attribution."""
from __future__ import annotations

import json
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout, sync_playwright
from config.targets import MIN_RATING, MIN_REVIEWS
from scraper.grid_generator import generate_search_targets
from scraper.menu_extractor import extract_menu_for_place

RATING_RE = re.compile(r"(\d\.\d)")
REVIEW_COUNT_RE = re.compile(r"\(?\b([\d,]+(?:\.\d+)?)\s*([KkMm])?\s*(?:reviews?|\)?)\b", re.IGNORECASE)
COORD_AT_RE = re.compile(r"/@(-?\d+\.\d+),(-?\d+\.\d+),")
COORD_3D4D_RE = re.compile(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)")
PLACE_ID_RE = re.compile(r"(ChIJ[a-zA-Z0-9_-]+)")
PHONE_RE = re.compile(r"(?:\+91[\s-]?)?(?:\(?0?\d{2,4}\)?[\s-]?)?\d{4}[\s-]?\d{4,6}")

def random_delay(min_s: float = 0.4, max_s: float = 1.0) -> None:
    time.sleep(random.uniform(min_s, max_s))

def dismiss_overlays(page: Page) -> None:
    try:
        close_drawer = page.locator('button[aria-label="Close"], button[jsaction*="drawer.close"]').first
        if close_drawer.is_visible(timeout=600):
            close_drawer.click()
    except Exception:
        pass
    for text in ("Accept all", "Reject all", "I agree", "Agree"):
        try:
            btn = page.locator(f'button:has-text("{text}")').first
            if btn.is_visible(timeout=600):
                btn.click()
                random_delay(0.3, 0.5)
                break
        except Exception:
            pass

def parse_review_count(text: str) -> int | None:
    if not text:
        return None
    cleaned = text.replace("\u00a0", " ").replace("\u202f", " ").replace("(", "").replace(")", "").strip()
    match = REVIEW_COUNT_RE.search(cleaned)
    if not match:
        digits = re.search(r"\b([\d,]+)\b", cleaned)
        if digits:
            try:
                return int(digits.group(1).replace(",", ""))
            except ValueError:
                return None
        return None
    raw = match.group(1).replace(",", "")
    suffix = (match.group(2) or "").upper()
    try:
        val = float(raw)
        if suffix == "K":
            val *= 1000
        elif suffix == "M":
            val *= 1_000_000
        return int(val)
    except ValueError:
        return None

def parse_rating(text: str) -> float | None:
    if not text:
        return None
    match = RATING_RE.search(text)
    return float(match.group(1)) if match else None

def extract_coordinates(url: str, fallback: tuple[float, float]) -> tuple[float, float]:
    if not url:
        return fallback
    decoded = unquote(url)
    match = COORD_3D4D_RE.search(decoded)
    if match:
        return float(match.group(1)), float(match.group(2))
    match = COORD_AT_RE.search(decoded)
    if match:
        return float(match.group(1)), float(match.group(2))
    return fallback

def extract_place_id(url: str) -> str | None:
    if not url:
        return None
    match = PLACE_ID_RE.search(unquote(url))
    return match.group(1) if match else None

def dedupe_key(name: str, place_id: str | None, lat: float, lng: float) -> str:
    if place_id:
        return f"id:{place_id}"
    return f"coord:{name.strip().lower()}:{round(lat,4)}:{round(lng,4)}"

def scroll_feed(page: Page, max_scrolls: int = 30) -> None:
    feed = page.locator('div[role="feed"], div[aria-label*="Results"], .m6QErb[aria-label]').first
    if feed.count() == 0:
        return

    last_card_count = 0
    stagnant_count = 0

    for _ in range(max_scrolls):
        try:
            end_msg = page.locator('text="You\'ve reached the end of the list"').first
            if end_msg.is_visible(timeout=400):
                break
        except Exception:
            pass

        cards = page.locator('div[role="feed"] > div > div[jsaction], div.Nv2PK')
        current_count = cards.count()

        if current_count == last_card_count:
            stagnant_count += 1
            if stagnant_count >= 3:
                break
        else:
            stagnant_count = 0

        last_card_count = current_count

        try:
            feed.evaluate("el => el.scrollBy(0, 5000)")
            random_delay(0.5, 0.9)
        except Exception:
            break

def parse_list_cards(page: Page, locality: str, fallback: tuple[float, float]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    cards = page.locator('div[role="feed"] > div > div[jsaction], div[aria-label*="Results"] > div > div[jsaction], div.Nv2PK')
    count = cards.count()

    for i in range(count):
        try:
            card = cards.nth(i)
            link = card.locator('a[href*="/maps/place/"]').first
            if link.count() == 0:
                continue

            href = link.get_attribute("href") or ""
            if not href.startswith("http"):
                href = f"https://www.google.com{href}"

            name = ""
            name_el = card.locator('.fontHeadlineSmall, [class*="fontHeadline"]').first
            if name_el.count() > 0:
                name = name_el.inner_text(timeout=600).strip()
            if not name:
                aria = link.get_attribute("aria-label") or ""
                name = aria.split("\n")[0].strip()
            if not name:
                continue

            card_text = card.inner_text(timeout=600)
            rating = None
            rating_el = card.locator('span.MW4etd, span[class*="rating"]').first
            if rating_el.count() > 0:
                rating = parse_rating(rating_el.inner_text(timeout=300))
            if rating is None:
                rating = parse_rating(card_text)

            reviews = None
            review_el = card.locator('span.UY7F9, span[class*="reviews"]').first
            if review_el.count() > 0:
                reviews = parse_review_count(review_el.inner_text(timeout=300))
            if reviews is None:
                reviews = parse_review_count(card_text)

            if rating is None or reviews is None:
                continue
            if rating < MIN_RATING or reviews < MIN_REVIEWS:
                continue

            lat, lng = extract_coordinates(href, fallback)
            results.append(
                {
                    "name": name,
                    "rating": rating,
                    "review_count": reviews,
                    "locality": locality,
                    "latitude": lat,
                    "longitude": lng,
                    "google_maps_url": href,
                    "place_id": extract_place_id(href),
                }
            )
        except Exception:
            continue

    return results

def extract_place_details(page: Page, listing: dict[str, Any]) -> dict[str, Any]:
    url = listing["google_maps_url"]
    fallback = (listing["latitude"], listing["longitude"])
    metadata_sources: dict[str, Any] = {}
    result = dict(listing)
    result["metadata_sources"] = metadata_sources

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=25000)
        dismiss_overlays(page)
        random_delay(0.5, 1.0)
    except Exception as exc:
        result["scrape_error"] = str(exc)
        return result

    lat, lng = extract_coordinates(page.url, fallback)
    result["latitude"], result["longitude"] = lat, lng

    body_text = ""
    try:
        body_text = page.locator('[role="main"]').inner_text(timeout=1500)
    except Exception:
        pass

    # Address
    for selector in ('button[data-item-id="address"]', 'button[aria-label*="Address"]'):
        try:
            el = page.locator(selector).first
            if el.count() > 0:
                addr = el.inner_text(timeout=600).strip()
                if addr:
                    result["address"] = addr
                    metadata_sources["address"] = {"value": addr, "source": "Google Maps Place Header"}
                    break
        except Exception:
            continue

    # Phone
    for selector in ('button[data-item-id^="phone"]', 'button[aria-label*="Phone"]', 'a[href^="tel:"]'):
        try:
            el = page.locator(selector).first
            if el.count() > 0:
                raw = el.inner_text(timeout=600) or el.get_attribute("href") or ""
                match = PHONE_RE.search(raw.replace("tel:", "").strip())
                if match:
                    phone = match.group(0).strip()
                    result["phone"] = phone
                    metadata_sources["phone"] = {"value": phone, "source": "Google Maps Listing Header"}
                    break
        except Exception:
            continue

    # Website
    for selector in ('a[data-item-id="authority"]', 'a[aria-label*="Website"]'):
        try:
            el = page.locator(selector).first
            if el.count() > 0:
                href = el.get_attribute("href") or ""
                if href and "google.com" not in href:
                    result["website"] = href.strip()
                    metadata_sources["website"] = {"value": href.strip(), "source": "Google Maps Place Button"}
                    break
        except Exception:
            continue

    # Hours & Open-Now
    hours: list[str] = []
    try:
        hours_btn = page.locator('button[aria-label*="Hours"], button[data-item-id="oh"]').first
        if hours_btn.count() > 0:
            hours_btn.click(timeout=800)
            random_delay(0.2, 0.4)
            hour_rows = page.locator('table tr, div[aria-label*="hours"] div')
            for j in range(min(hour_rows.count(), 14)):
                row_text = hour_rows.nth(j).inner_text(timeout=300).strip()
                if row_text and len(row_text) < 80:
                    hours.append(row_text)
            metadata_sources["opening_hours"] = {"value": hours, "source": "Google Maps Hours Panel"}
    except Exception:
        pass

    open_match = re.search(r"\b(Open|Closed)\b", body_text[:500])
    if open_match:
        result["is_open_now"] = (open_match.group(1) == "Open")

    result["opening_hours"] = hours
    result["scraped_at"] = datetime.now(timezone.utc).isoformat()

    menu_data = extract_menu_for_place(page)
    if menu_data:
        result["raw_menu"] = menu_data.get("items", [])
        result["menu_source"] = menu_data.get("source", "")
        result["qr_menu_url"] = menu_data.get("qr_menu_url")
        result["menu_images"] = menu_data.get("menu_images", [])

    return result

def scrape_target(page: Page, target: dict[str, str | float]) -> list[dict[str, Any]]:
    name = str(target["name"])
    lat, lon = float(target["lat"]), float(target["lon"])
    
    # Coordinate-anchored search URL prevents Google Maps polygon redirects
    url = f"https://www.google.com/maps/search/restaurants/@{lat},{lon},15z"
    print(f"\n📍 Scanning {target['type']}: {name}")

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        dismiss_overlays(page)
        random_delay(0.8, 1.4)

        feed_selector = 'div[role="feed"], div[aria-label*="Results"], .m6QErb[aria-label]'
        feed_found = False

        try:
            page.wait_for_selector(feed_selector, timeout=5000)
            feed_found = True
        except Exception:
            # Fallback: Actively submit search in searchbox if the feed didn't open
            search_box = page.locator('input#searchboxinput, input[name="q"]').first
            if search_box.is_visible(timeout=2000):
                search_box.fill(f"Restaurants in {name} Hyderabad")
                search_box.press("Enter")
                random_delay(1.2, 2.0)
                try:
                    page.wait_for_selector(feed_selector, timeout=6000)
                    feed_found = True
                except Exception:
                    feed_found = False

        if not feed_found:
            print(f"  ⚠️ No feed found for {name}")
            return []

    except PlaywrightTimeout:
        print(f"  ⚠️ Timeout loading feed for: {name}")
        return []
    except Exception as exc:
        print(f"  ⚠️ Error on {name}: {exc}")
        return []

    scroll_feed(page, max_scrolls=25)
    listings = parse_list_cards(page, name, (lat, lon))
    print(f"  ↳ Found {len(listings)} qualifying places (4.0+ ★ & 1K+ reviews)")

    detailed: list[dict[str, Any]] = []
    for idx, listing in enumerate(listings, start=1):
        print(f"    [{idx}/{len(listings)}] Details: {listing['name']} ({listing['rating']}★, {listing['review_count']:,} reviews)...")
        try:
            detailed.append(extract_place_details(page, listing))
            random_delay(0.4, 0.7)
        except Exception as exc:
            listing["scrape_error"] = str(exc)
            detailed.append(listing)

    return detailed

def run_scraper(
    max_targets: int | None = None,
    skip_details: bool = False,
    progress_callback=None,
) -> list[dict[str, Any]]:
    targets = generate_search_targets()
    if max_targets:
        targets = targets[:max_targets]

    seen: set[str] = set()
    all_places: list[dict[str, Any]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={"width": 1366, "height": 768},
            locale="en-IN",
        )
        page = context.new_page()

        for idx, target in enumerate(targets, start=1):
            if progress_callback:
                progress_callback({"status": "scraping", "current": idx, "total": len(targets), "target": target["name"]})

            places = scrape_target(page, target)
            for place in places:
                key = dedupe_key(place["name"], place.get("place_id"), place["latitude"], place["longitude"])
                if key not in seen:
                    seen.add(key)
                    all_places.append(place)

            random_delay(0.4, 0.8)

        browser.close()

    return all_places
