"""Menu extraction from Google Maps DOM and QR code scanning from photos."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse
import httpx
from playwright.sync_api import Page

try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

try:
    from pyzbar.pyzbar import decode as qr_decode
    PYZBAR_AVAILABLE = True
except ImportError:
    PYZBAR_AVAILABLE = False

def _scan_qr_from_bytes(image_bytes: bytes) -> str | None:
    if not CV2_AVAILABLE or not PYZBAR_AVAILABLE:
        return None
    try:
        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return None
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        for decoded in qr_decode(gray):
            data = decoded.data.decode("utf-8", errors="ignore").strip()
            if data.startswith("http"):
                parsed = urlparse(data)
                if parsed.scheme in ("http", "https"):
                    return data
    except Exception:
        return None
    return None

def _download_image(url: str) -> bytes | None:
    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 200:
                return resp.content
    except Exception:
        pass
    return None

def _parse_menu_dom(page: Page) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    selectors = [
        'div[aria-label*="Menu"] div[class*="fontBodyMedium"]',
        'div[data-section-id="menu"] div',
        '[role="tabpanel"] div[class*="fontBodyMedium"]',
    ]
    for selector in selectors:
        try:
            nodes = page.locator(selector)
            count = min(nodes.count(), 80)
            current_category = "General"
            for i in range(count):
                text = nodes.nth(i).inner_text(timeout=1000).strip()
                if not text or len(text) > 200:
                    continue
                price_match = re.search(r"[₹$]\s*[\d,]+(?:\.\d{2})?", text)
                if price_match:
                    name = text.replace(price_match.group(0), "").strip(" -—:\n\t")
                    items.append(
                        {
                            "category": current_category,
                            "name": name or text,
                            "price": price_match.group(0).replace(" ", ""),
                            "description": "",
                        }
                    )
                elif len(text) < 40 and not re.search(r"\d", text):
                    current_category = text
            if items:
                break
        except Exception:
            continue
    return items

def _scan_menu_photos(page: Page) -> dict[str, Any]:
    result: dict[str, Any] = {"qr_menu_url": None, "menu_images": []}
    photo_selectors = [
        'div[role="tablist"] button[role="tab"]:has-text("Photos")',
        'button[role="tab"][aria-label*="Photos"]',
        'div[role="tablist"] button:has-text("By owner")',
    ]
    for selector in photo_selectors:
        try:
            btn = page.locator(selector).first
            if btn.count() == 0:
                continue
            btn.click(timeout=3000)
            page.wait_for_timeout(1500)
            imgs = page.locator('img[src*="googleusercontent"], img[src*="ggpht"]')
            for i in range(min(imgs.count(), 12)):
                src = imgs.nth(i).get_attribute("src")
                if not src:
                    continue
                if "menu" in (src.lower()) or i < 6:
                    result["menu_images"].append(src)
                    img_bytes = _download_image(src)
                    if img_bytes:
                        qr_url = _scan_qr_from_bytes(img_bytes)
                        if qr_url:
                            result["qr_menu_url"] = qr_url
                            return result
            break
        except Exception:
            continue
    return result

def extract_menu_for_place(page: Page) -> dict[str, Any] | None:
    items: list[dict[str, Any]] = []
    source = ""
    
    # Strictly target tabs within the restaurant's tablist
    menu_tab_selectors = [
        'div[role="tablist"] button[role="tab"]:has-text("Menu")',
        'button[role="tab"][aria-label*="Menu"]',
        'div[role="tablist"] button:has-text("Menu")',
    ]
    for selector in menu_tab_selectors:
        try:
            tab = page.locator(selector).first
            if tab.count() > 0:
                tab.click(timeout=2500)
                page.wait_for_timeout(1500)
                items = _parse_menu_dom(page)
                if items:
                    source = "Google Maps Menu Tab"
                    break
        except Exception:
            continue

    qr_data: dict[str, Any] = {"qr_menu_url": None, "menu_images": []}
    if not items:
        qr_data = _scan_menu_photos(page)
        if qr_data.get("qr_menu_url"):
            source = "In-Store QR Code Scan"
        elif qr_data.get("menu_images"):
            source = "Google Maps Menu Photo Gallery"

    if not items and not qr_data.get("qr_menu_url") and not qr_data.get("menu_images"):
        return None

    return {
        "items": items,
        "source": source or "Google Maps",
        "qr_menu_url": qr_data.get("qr_menu_url"),
        "menu_images": qr_data.get("menu_images", []),
        "extracted_at": datetime.now(timezone.utc).isoformat(),
    }