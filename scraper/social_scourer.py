"""Keyless Reddit, DuckDuckGo, and Google News context scraper for LLM enrichment."""
from __future__ import annotations

import re
import time
from typing import Any
import httpx
from urllib.parse import quote_plus

REDDIT_SEARCH = "https://www.reddit.com/r/hyderabad/search.json"
HEADERS = {
    "User-Agent": "hyd-food-intel/1.0 (local research bot; contact: local@localhost)",
    "Accept": "application/json",
}

def _sanitize(text: str, max_len: int = 500) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len]

def fetch_reddit_mentions(restaurant_name: str, limit: int = 20) -> list[dict[str, str]]:
    results = []
    try:
        with httpx.Client(timeout=20.0, headers=HEADERS, follow_redirects=True) as client:
            resp = client.get(REDDIT_SEARCH, params={
                "q": restaurant_name,
                "restrict_sr": "1",
                "limit": limit,
                "sort": "relevance",
            })
            if resp.status_code != 200:
                return results
            data = resp.json()
            posts = data.get("data", {}).get("children", [])
            for post in posts:
                pd = post.get("data", {})
                title = _sanitize(pd.get("title", ""), 200)
                body = _sanitize(pd.get("selftext", ""), 400)
                if title or body:
                    results.append({
                        "source": "Reddit r/hyderabad",
                        "title": title,
                        "snippet": body or title,
                        "url": f"https://reddit.com{pd.get('permalink', '')}",
                    })
            time.sleep(1.0)
    except Exception:
        pass
    return results

def fetch_duckduckgo_mentions(restaurant_name: str, max_results: int = 10) -> list[dict[str, str]]:
    results = []
    query = f"{restaurant_name} Hyderabad food review menu blog"
    DDGS = None
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            DDGS = None

    if DDGS is None:
        return results  # can't use DDG, skip

    try:
        with DDGS() as ddgs:
            for item in ddgs.text(query, max_results=max_results):
                results.append({
                    "source": "DuckDuckGo Web",
                    "title": _sanitize(item.get("title", ""), 200),
                    "snippet": _sanitize(item.get("body", ""), 400),
                    "url": item.get("href", ""),
                })
        time.sleep(0.5)
    except Exception:
        # Fallback to HTML scraping (simplified)
        try:
            with httpx.Client(timeout=20.0, headers=HEADERS) as client:
                resp = client.get("https://html.duckduckgo.com/html/", params={"q": query})
                if resp.status_code == 200:
                    # Use regex to extract snippets
                    snippets = re.findall(r'class="result__snippet"[^>]*>([^<]+)', resp.text)[:max_results]
                    for snip in snippets:
                        results.append({
                            "source": "DuckDuckGo HTML Fallback",
                            "title": query,
                            "snippet": _sanitize(snip, 400),
                            "url": "",
                        })
        except Exception:
            pass
    return results

def fetch_google_news_mentions(restaurant_name: str, max_results: int = 5) -> list[dict[str, str]]:
    """Fetch recent Google News mentions via RSS."""
    results = []
    query = quote_plus(f"{restaurant_name} Hyderabad food")
    rss_url = f"https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
    try:
        with httpx.Client(timeout=20.0) as client:
            resp = client.get(rss_url)
            if resp.status_code != 200:
                return results
            items = re.findall(r"<item>(.*?)</item>", resp.text, re.DOTALL)
            for item in items[:max_results]:
                title_match = re.search(r"<title>(.*?)</title>", item)
                link_match = re.search(r"<link>(.*?)</link>", item)
                desc_match = re.search(r"<description>(.*?)</description>", item)
                title = _sanitize(title_match.group(1) if title_match else "", 200)
                snippet = _sanitize(desc_match.group(1) if desc_match else "", 400)
                url = link_match.group(1) if link_match else ""
                if title:
                    results.append({
                        "source": "Google News",
                        "title": title,
                        "snippet": snippet,
                        "url": url,
                    })
    except Exception:
        pass
    return results

def build_context_summary(restaurant_name: str) -> dict[str, Any]:
    reddit = fetch_reddit_mentions(restaurant_name)
    ddg = fetch_duckduckgo_mentions(restaurant_name)
    gnews = fetch_google_news_mentions(restaurant_name)
    all_mentions = reddit + ddg + gnews

    lines = [f"=== Social Context for {restaurant_name} ==="]
    for m in all_mentions:
        lines.append(f"[{m['source']}] {m.get('title', '')}")
        lines.append(m.get("snippet", ""))
        if m.get("url"):
            lines.append(f"URL: {m['url']}")
        lines.append("---")

    summary_text = "\n".join(lines)
    return {
        "restaurant_name": restaurant_name,
        "reddit_count": len(reddit),
        "web_count": len(ddg),
        "news_count": len(gnews),
        "mentions": all_mentions,
        "summary_text": summary_text[:8000],
    }

def scour_restaurant(restaurant: dict[str, Any]) -> dict[str, Any]:
    name = restaurant.get("name", "")
    context = build_context_summary(name)
    return {"restaurant_name": name, "social_context": context}