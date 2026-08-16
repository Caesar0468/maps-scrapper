"""Playwright Google Maps scraper with metadata, hours, phone, and source attribution."""
from __future__ import annotations

import json
import random
import re
import time
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, unquote
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout, sync_playwright
from config.targets import MIN_RATING, MIN_REVIEWS
from scraper.grid_generator import generate_search_targets
from scraper.menu_extractor import extract_menu_for_place
from urllib.parse import urlparse, parse_qs

RATING_RE = re.compile(r"(\d\.\d)")
REVIEW_COUNT_RE = re.compile(r"\(?\b([\d,]+(?:\.\d+)?)\s*([KkMm])?\s*(?:reviews?|\)?)\b", re.IGNORECASE)
COORD_AT_RE = re.compile(r"/@(-?\d+\.\d+),(-?\d+\.\d+),")
COORD_3D4D_RE = re.compile(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)")
PLACE_ID_RE = re.compile(r"(ChIJ[a-zA-Z0-9_-]+)")
PHONE_RE = re.compile(r"(?:\+91[\s-]?)?(?:\(?0?\d{2,4}\)?[\s-]?)?\d{4}[\s-]?\d{4,6}")

def random_delay(min_s: float = 0.4, max_s: float = 0.8) -> None:
    time.sleep(random.uniform(min_s, max_s))

def dismiss_cookie_banners(page: Page) -> None:
    """Dismiss cookie consent and sign-in prompts, but NOT generic close buttons."""
    for text in ("Accept all", "Reject all", "I agree", "Agree", "Not now", "Maybe later"):
        try:
            btn = page.locator(f'button:has-text("{text}")').first
            if btn.is_visible(timeout=500):
                btn.click(timeout=1000)
                random_delay(0.2, 0.4)
                break
        except Exception:
            pass

def dismiss_overlays(page: Page) -> None:
    """Dismiss common Google Maps popups."""
    dismiss_cookie_banners(page)

def parse_rating(text: str) -> float | None:
    if not text:
        return None
    match = RATING_RE.search(text)
    return float(match.group(1)) if match else None

def parse_review_count(text: str) -> int | None:
    """Parse review count from text like '1,234 reviews' or '(1,234)' or '1.2K reviews'."""
    if not text:
        return None
    cleaned = text.replace("\u00a0", " ").replace("\u202f", " ")

    # Try "1,234 reviews"
    match = re.search(r"\b([\d,]+)\s*reviews?\b", cleaned, re.IGNORECASE)
    if match:
        return int(match.group(1).replace(",", ""))

    # Try "1.2K reviews" or "1.5M reviews"
    match = re.search(r"\b(\d+\.?\d*)\s*([KkMm])\s*reviews?\b", cleaned)
    if match:
        number = float(match.group(1))
        suffix = match.group(2).lower()
        if suffix == 'k':
            return int(number * 1000)
        elif suffix == 'm':
            return int(number * 1_000_000)

    # Try "(1,234)" after a rating
    match = re.search(r"\b\d\.\d\s*\(([\d,]+)\)", cleaned)
    if match:
        return int(match.group(1).replace(",", ""))

    # Any parenthesized number with comma
    match = re.search(r"\(([\d,]+)\)", cleaned)
    if match:
        return int(match.group(1).replace(",", ""))
    return None

def extract_rating_reviews(text: str) -> tuple[float | None, int | None]:
    """Extract rating and review count from a block of text.
    Handles both '4.5(12,237)' and '4.5 (12,237 reviews)' formats.
    """
    if not text:
        return None, None
    match = re.search(r"(\d\.\d)\s*\(([\d,]+)\)", text)
    if match:
        rating = float(match.group(1))
        reviews = int(match.group(2).replace(",", ""))
        return rating, reviews
    rating = parse_rating(text)
    reviews = parse_review_count(text)
    return rating, reviews

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

def dedupe_key(name: str, place_id: str | None, url: str, lat: float, lng: float) -> str:
    if place_id:
        return f"id:{place_id}"
    if url:
        return f"url:{url}"
    return f"coord:{name.strip().lower()}:{round(lat,4)}:{round(lng,4)}"

def try_sort_by_rating(page: Page) -> None:
    """Attempt to sort results by Top rated (highest first)."""
    try:
        sort_btn = page.locator('button[aria-label*="Sort"]').first
        if sort_btn.is_visible(timeout=3000):
            sort_btn.click()
            random_delay(0.5, 0.8)
            top_rated = page.locator('div[role="menuitemradio"]:has-text("Top rated")').first
            if top_rated.is_visible(timeout=2000):
                top_rated.click()
                random_delay(1.0, 1.5)
                print("    Sorted by Top rated.")
    except Exception:
        pass

def scroll_feed(page: Page, max_scrolls: int = 50, max_time: float = 30.0) -> None:
    """Scroll until end-of-list or limits reached."""
    start_time = time.time()
    last_count = 0
    stagnant = 0

    for i in range(max_scrolls):
        if time.time() - start_time > max_time:
            print(f"    ⏱️ Reached max scroll time ({max_time}s). Stopping.")
            break

        # Scroll
        try:
            feed = page.locator('div[role="feed"]').first
            if feed.count() > 0:
                feed.evaluate("el => el.scrollTop = el.scrollHeight")
            else:
                page.mouse.wheel(0, 2000)
        except Exception:
            page.mouse.wheel(0, 2000)

        random_delay(0.5, 0.8)

        # End-of-list check
        try:
            if page.locator('text="You\'ve reached the end of the list"').is_visible(timeout=500):
                print("    End of list reached.")
                break
        except Exception:
            pass

        # Count articles
        try:
            current = page.locator('div[role="article"]').count()
        except Exception:
            current = last_count

        if current == last_count:
            stagnant += 1
            if stagnant >= 5:
                print(f"    No new results after {stagnant} scrolls. Stopping.")
                break
        else:
            stagnant = 0
        last_count = current

def parse_list_cards(page: Page, locality: str, fallback: tuple[float, float]) -> list[dict[str, Any]]:
    """Parse restaurant cards from current page."""
    results = []
    article_selector = 'div[role="article"]'
    try:
        articles = page.locator(article_selector)
        count = articles.count()
        print(f"    Articles found: {count}")
        for i in range(count):
            try:
                article = articles.nth(i)
                link = article.locator('a[href*="/maps/place/"]').first
                if link.count() == 0:
                    link = article.locator('a').first
                if link.count() == 0:
                    continue
                href = link.get_attribute("href") or ""
                if not href.startswith("http"):
                    href = f"https://www.google.com{href}"

                text = article.inner_text(timeout=2000)
                if not text:
                    continue

                rating, reviews = extract_rating_reviews(text)
                if rating is None or reviews is None:
                    # Fallback to specific elements
                    try:
                        rating_el = article.locator('span[aria-hidden="true"]').first
                        if rating_el.count() > 0:
                            rating = parse_rating(rating_el.inner_text(timeout=500))
                    except Exception:
                        pass
                    try:
                        review_el = article.locator('span[aria-label*="reviews"]').first
                        if review_el.count() > 0:
                            reviews = parse_review_count(review_el.inner_text(timeout=500))
                    except Exception:
                        pass

                if rating is None or reviews is None:
                    continue
                if rating < MIN_RATING or reviews < MIN_REVIEWS:
                    continue

                lines = [l.strip() for l in text.split('\n') if l.strip()]
                name = lines[0] if lines else "Unknown"

                lat, lng = extract_coordinates(href, fallback)
                results.append({
                    "name": name,
                    "rating": rating,
                    "review_count": reviews,
                    "locality": locality,
                    "latitude": lat,
                    "longitude": lng,
                    "google_maps_url": href,
                    "place_id": extract_place_id(href),
                })
            except Exception as e:
                print(f"    Error parsing article {i}: {e}")
                continue
    except Exception as e:
        print(f"    Error with article selector: {e}")

    # If no results, try alternative selectors
    if not results:
        print("    No results from articles, trying fallback selectors...")
        alt_selectors = ['div.Nv2PK', 'div[role="feed"] > div > div']
        for selector in alt_selectors:
            try:
                items = page.locator(selector)
                count = items.count()
                print(f"    Selector '{selector}' count: {count}")
                for i in range(count):
                    item = items.nth(i)
                    link = item.locator('a[href*="/maps/place/"]').first
                    if link.count() == 0:
                        continue
                    href = link.get_attribute("href") or ""
                    if not href.startswith("http"):
                        href = f"https://www.google.com{href}"
                    text = item.inner_text(timeout=1000)
                    rating, reviews = extract_rating_reviews(text)
                    if rating is None or reviews is None:
                        continue
                    if rating < MIN_RATING or reviews < MIN_REVIEWS:
                        continue
                    name = text.split('\n')[0].strip() if text else ""
                    lat, lng = extract_coordinates(href, fallback)
                    results.append({
                        "name": name,
                        "rating": rating,
                        "review_count": reviews,
                        "locality": locality,
                        "latitude": lat,
                        "longitude": lng,
                        "google_maps_url": href,
                        "place_id": extract_place_id(href),
                    })
            except Exception as e:
                print(f"    Error with fallback selector '{selector}': {e}")

    # Deduplicate
    unique = []
    seen_keys = set()
    for r in results:
        key = dedupe_key(r["name"], r.get("place_id"), r.get("google_maps_url"), r["latitude"], r["longitude"])
        if key not in seen_keys:
            seen_keys.add(key)
            unique.append(r)
    return unique

def extract_place_details(page: Page, listing: dict[str, Any]) -> dict[str, Any]:
    url = listing["google_maps_url"]
    fallback = (listing["latitude"], listing["longitude"])
    metadata_sources: dict[str, Any] = {}
    result = dict(listing)
    result["metadata_sources"] = metadata_sources

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        dismiss_overlays(page)
        random_delay(0.4, 0.7)
    except Exception as exc:
        result["scrape_error"] = str(exc)
        return result

    lat, lng = extract_coordinates(page.url, fallback)
    result["latitude"], result["longitude"] = lat, lng

    body_text = ""
    try:
        body_text = page.locator('[role="main"]').inner_text(timeout=1200)
    except Exception:
        pass

    # Address
    for selector in ('button[data-item-id="address"]', 'button[aria-label*="Address"]'):
        try:
            el = page.locator(selector).first
            if el.count() > 0:
                addr = el.inner_text(timeout=400).strip()
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
                raw = el.inner_text(timeout=400) or el.get_attribute("href") or ""
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
                if href and "google.com/url" in href:
                    parsed = parse_qs(urlparse(href).query)
                    actual = parsed.get("q", [""])[0]
                    if actual:
                        href = actual
                if href and "google.com" not in href:
                    result["website"] = href.strip()
                    metadata_sources["website"] = {"value": href.strip(), "source": "Google Maps Place Button"}
                    break
        except Exception:
            continue

    # Hours
    hours: list[str] = []
    try:
        hours_btn = page.locator('button[aria-label*="Hours"], button[data-item-id="oh"]').first
        if hours_btn.count() > 0:
            hours_btn.click(timeout=600)
            random_delay(0.2, 0.3)
            hour_rows = page.locator('table tr, div[aria-label*="hours"] div')
            for j in range(min(hour_rows.count(), 14)):
                row_text = hour_rows.nth(j).inner_text(timeout=200).strip()
                if row_text and len(row_text) < 80:
                    hours.append(row_text)
            metadata_sources["opening_hours"] = {"value": hours, "source": "Google Maps Hours Panel"}
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
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
    query_str = str(target.get("query") or f"restaurants near {target['name']}, Hyderabad")
    url = f"https://www.google.com/maps/search/{quote_plus(query_str)}"
    print(f"\n📍 Scanning {target['type']}: {target['name']}")

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=35000)
        dismiss_cookie_banners(page)
        time.sleep(1.5)
        dismiss_cookie_banners(page)

        if "/maps/place/" in page.url:
            for chip_text in ("Nearby restaurants", "Restaurants", "Food"):
                try:
                    chip = page.locator(f'button:has-text("{chip_text}")').first
                    if chip.is_visible(timeout=1500):
                        chip.click(timeout=2000)
                        random_delay(1.0, 1.6)
                        break
                except Exception:
                    pass

        # Wait for results
        try:
            page.wait_for_selector('div[role="article"]', timeout=20000, state="visible")
            print("    Results loaded.")
        except PlaywrightTimeout:
            print("    ⚠️ No articles found after 20s.")
            return []

        # Sort by top rated (optional)
        try_sort_by_rating(page)

        # Scroll to load all results
        scroll_feed(page, max_scrolls=50, max_time=30.0)

        locality_for_card = str(target["name"]) if target.get("type") == "locality" else ""

        listings = parse_list_cards(page, locality_for_card, (float(target["lat"]), float(target["lon"])))
        print(f"  ↳ Found {len(listings)} qualifying places (4.0+ ★ & 1K+ reviews)")

        detailed: list[dict[str, Any]] = []
        for idx, listing in enumerate(listings, start=1):
            print(f"    [{idx}/{len(listings)}] Details: {listing['name']} ({listing['rating']}★, {listing['review_count']:,} reviews)...")
            try:
                detailed.append(extract_place_details(page, listing))
                random_delay(0.3, 0.6)
            except Exception as exc:
                listing["scrape_error"] = str(exc)
                detailed.append(listing)

        return detailed

    except PlaywrightTimeout:
        print(f"  ⚠️ Timeout loading feed for: {target['name']}")
        return []
    except Exception as exc:
        print(f"  ⚠️ Error on {target['name']}: {exc}")
        return []

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

    headless = os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() == "true"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            viewport={"width": 1366, "height": 768},
            locale="en-IN",
        )
        page = context.new_page()

        try:
            page.goto("https://www.google.com/maps", wait_until="domcontentloaded", timeout=20000)
            dismiss_cookie_banners(page)
            random_delay(0.8, 1.2)
        except Exception:
            pass

        for idx, target in enumerate(targets, start=1):
            if progress_callback:
                progress_callback({
                    "status": "scraping",
                    "current": idx,
                    "total": len(targets),
                    "target": target["name"],
                    "message": f"Scraping {target['name']} ({idx}/{len(targets)})"
                })

            places = scrape_target(page, target)
            for place in places:
                key = dedupe_key(
                    place["name"],
                    place.get("place_id"),
                    place.get("google_maps_url"),
                    place["latitude"],
                    place["longitude"]
                )
                if key not in seen:
                    seen.add(key)
                    all_places.append(place)

            random_delay(0.4, 0.8)

        browser.close()

    return all_places