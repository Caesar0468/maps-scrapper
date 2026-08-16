from playwright.sync_api import sync_playwright
import time

URL = "https://www.google.com/maps/search/Restaurants%20in%20Abids%20Hyderabad"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    page.goto(URL, wait_until="domcontentloaded", timeout=35000)
    time.sleep(3)
    # dismiss overlays
    for text in ("Accept all", "Reject all", "Not now", "Maybe later"):
        try:
            btn = page.locator(f'button:has-text("{text}")').first
            if btn.is_visible(timeout=500):
                btn.click(timeout=1000)
                time.sleep(1)
                break
        except Exception:
            pass

    # Wait for at least one article
    try:
        page.wait_for_selector('div[role="article"]', timeout=15000)
        print("Articles found")
    except Exception as e:
        print("No articles:", e)

    articles = page.locator('div[role="article"]')
    print("Article count:", articles.count())
    for i in range(min(3, articles.count())):
        try:
            art = articles.nth(i)
            print(f"\n--- Article {i} ---")
            print("Tag:", art.evaluate("el => el.tagName"))
            print("Inner text:", art.inner_text(timeout=1000)[:500])
            # Find links inside
            links = art.locator('a[href*="/maps/place/"]')
            print("Links count:", links.count())
            if links.count() > 0:
                print("First link href:", links.first.get_attribute("href"))
        except Exception as e:
            print("Error:", e)

    browser.close()