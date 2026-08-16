# HY Food Intel (Telangana & Greater Hyderabad)

An offline-first, zero-cost AI food intelligence and restaurant exploration platform. The system scrapes, filters, context-scours, enriches via local LLMs (Ollama), and visualizes top-tier dining establishments across Hyderabad and the Outer Ring Road (ORR) corridor.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                 SYSTEM ARCHITECTURE                                    │
│                                                                                        │
│  [config/targets.py]                                                                   │
│         │                                                                              │
│         ▼                                                                              │
│  [scraper/grid_generator.py] ──► Generates 80+ Localities + Bounding Box Centroids      │
│         │                                                                              │
│         ▼                                                                              │
│  [scraper/gmaps_scraper.py] ───► Headful Playwright (Rating ≥ 4.0, Reviews ≥ 1,000)   │
│         │                             │                                                │
│         │                             ├─► [scraper/menu_extractor.py] (DOM + QR/OCR)   │
│         │                             └─► Data Attribution Engine                      │
│         ▼                                                                              │
│  [scraper/social_scourer.py] ──► Keyless Reddit (r/hyderabad) + DuckDuckGo Scour       │
│         │                                                                              │
│         ▼                                                                              │
│  [pipeline/analyzer.py] ───────► Local Ollama (qwen3:8b / llama3.1:8b) JSON Extraction │
│         │                             │ (Fallback to Rule-Based Heuristics)            │
│         ▼                             ▼                                                │
│  [database.py] ────────────────► SQLite (WAL Mode + FTS5 Full-Text Search)             │
│         │                                                                              │
│         ▼                                                                              │
│  [app.py] ─────────────────────► FastAPI + Jinja2 + Leaflet.js Interactive Web App     │
└────────────────────────────────────────────────────────────────────────────────────────┘

```

---

## Technical Specifications & Features

### 1. Geographic Targeting & Grid Engine

* **File:** `config/targets.py`, `scraper/grid_generator.py`

* **Regional Isolation:** All spatial coordinates and bounding limits are decoupled in `config/targets.py`. Adding new cities or states requires zero edits to scraper logic.


* **Spatial Tessellation:**
* Core Bounding Box: Latitude `17.1500` to `17.6500`, Longitude `78.1500` to `78.7000` with a step size of `0.025°` (~2.7 km resolution).


* 80+ Named Commercial Localities: Includes all high-density dining hubs (Jubilee Hills, Gachibowli, Madhapur, Charminar, Kompally, Secunderabad, etc.).




* **Distance Math:** Haversine great-circle calculation implemented in pure Python (`haversine_km`) for instant spatial distance evaluation.



### 2. Scraping, Extraction & Source Attribution

* **File:** `scraper/gmaps_scraper.py`

* **Strict Qualification Gate:** Only ingests places matching:

$$\text{Rating} \ge 4.0 \quad \land \quad \text{Reviews} \ge 1,000$$


* **Coordinate & ID Extraction:** Parses exact latitude and longitude from dynamic Google Maps URLs (`/@lat,lng` or `!3d...!4d...`) and extracts canonical Google Place IDs (`ChIJ...`).


* **Review Count Parsing:** Handles raw numeric values, comma delimiters (`1,250`), and compact metric notation (`1.2K`, `1.5M`).


* **Operating Hours & Live Status:** Scrapes the weekly opening schedule matrix and determines dynamic `is_open_now` state.


* **Field Traceability:** Every metadata field stores its extraction origin:
* `phone_source`: `"Google Maps Listing Header"` or `"Google Maps Place Details Text"`

* `website_source`: `"Google Maps Place Button"`

* `menu_source`: `"Google Maps Menu Tab"`, `"In-Store QR Code Scan"`, or `"Google Maps Menu Photo Gallery"`




### 3. Menu Extraction & Computer Vision QR Engine

* **File:** `scraper/menu_extractor.py`

* **Multi-Tier Fallback Hierarchy:**
1. **DOM Parsing:** Traverses Google Maps internal Menu tabs, extracting categories, item titles, descriptions, and INR prices (`₹...`).


2. **Photo Gallery QR Scanning:** If no text menu exists, fetches image thumbnails from the place photo stream, decodes QR barcodes using `cv2` (OpenCV) and `pyzbar`, and extracts web menu URLs.


3. **Visual Gallery Ingestion:** Stores high-resolution photo URLs of physical menu boards when QR codes are absent.





### 4. Context Scouring (Keyless)

* **File:** `scraper/social_scourer.py`

* **Reddit Scraper:** Queries `[https://www.reddit.com/r/hyderabad/search.json](https://www.reddit.com/r/hyderabad/search.json)` for community threads, reviews, and sentiment without requiring Reddit API keys.


* **Web Scraper:** Queries DuckDuckGo (`ddgs` library with direct HTML endpoint fallback) for food blogs, menu writeups, and critic mentions.


* **Sanitization:** Strips HTML entities, standardizes whitespace, and truncates context buffers to 8,000 characters to optimize LLM prompt windows.



### 5. Local LLM Intelligence & Heuristic Engine

* **File:** `pipeline/analyzer.py`

* **Zero-Cost Local Inference:** Interacts with local Ollama (`http://localhost:11434/api/generate`) targeting `qwen3:8b`, with automatic fallback to `llama3.1:8b`.


* **Enforced JSON Output Contract:**

```json
{
  "hype_score": 82,
  "hype_verdict": "Overhyped | Justified Hype | Hidden Gem | Reliable Classic",
  "hype_analysis_summary": "String (2-sentence community consensus vs reality)",
  "fake_review_risk": "Low | Moderate | High",
  "fake_review_reasons": "String (Astroturfing & velocity analysis)",
  "cuisines": ["Hyderabadi", "Biryani", "Mughlai"],
  "calculated_spend_for_two": 750,
  "budget_tier": "Budget (<₹500) | Moderate (₹500-₹1200) | Premium (₹1200-₹2500) | Fine Dining (₹2500+)",
  "dietary_suitability": "Pure Veg | Non-Veg Specialty | Balanced",
  "dietary_warning": "Avoid Veg Here | Avoid Non-Veg Here | Both Recommended | None",
  "dietary_warning_remarks": "String explaining kitchen handling / specialty focus",
  "must_try_items": ["Mutton Biryani", "Mirchi Ka Salan"],
  "skip_items": ["Chicken 65"],
  "red_flags": ["No dedicated parking", "45m weekend wait times"],
  "vibe_tags": ["Family Dining", "Late Night", "Hostel / Student Spot"],
  "is_pure_veg": false,
  "open_late_night": true
}

```

* **Graceful Heuristic Fallback:** If Ollama is offline or fails validation, a keyword and rule-based heuristic analyzer generates synthetic scores and dietary flags automatically.



### 6. Database & Search Layer

* **File:** `database.py`

* **Engine:** SQLite3 in WAL (Write-Ahead Logging) mode with `PRAGMA synchronous=NORMAL`.


* **Deduplication:** Composite unique constraint on `slug` and Google `place_id`.


* **Full-Text Search (FTS5):** Virtual table `restaurants_fts` indexing `name`, `locality`, `cuisines`, and `must_try_items` with automated row sync on upsert.



### 7. Interactive Frontend & Deep Profile Pages

* **Files:** `app.py`, `templates/`, `static/`

* **Map Engine:** Leaflet.js with OpenStreetMap and `Leaflet.markercluster`.


* **Real-Time Reactive Filters:**
* Keyword Search (FTS5 / multi-field substring matching)


* "Open Now" dynamic toggle


* Cuisine Tag Multi-Selector (`Biryani`, `South Indian`, `Chinese`, `Mughlai`, `Continental`, `Chaat`, `Mandi`, `Cafe`)


* Dietary Safety: `Pure Veg Only`, `Exclude "Avoid Veg" Flagged`, `Exclude "Avoid Non-Veg" Flagged`

* Hype Status: `Hidden Gem`, `Justified Hype`, `Reliable Classic`, `Overhyped`

* Trust Filter: `Low Fake-Review Risk Only`

* Spend-for-Two Range Slider (₹100 to ₹5,000+)


* HTML5 Geolocation "Near Me" GPS with distance radius chips (`<2km`, `<5km`, `<10km`, `All`)




* **Deep Restaurant Profile Page (`/restaurant/<slug>`):**
* Direct Google Maps navigation link


* Verified metadata cards (Phone, Website, Hours) with data source attribution badges


* Hype Score gauge & Fake Review Risk badge


* Dietary Recommendation callout box with safety remarks


* Embedded categorized menu view with item prices and QR code links


* Must-Try vs Skip Dishes comparison grid


* Operational red flags (parking constraints, wait times, hygiene warnings)


* Swiggy Dineout & Zomato Gold deal search links


* WhatsApp 1-Click Share card generator (`[https://wa.me/?text=](https://wa.me/?text=)...`)





---

## Directory Structure

```
hyd-food-intel/
├── config/
│   └── targets.py             # Target coordinates, bounding boxes, thresholds
├── scraper/
│   ├── __init__.py
│   ├── grid_generator.py      # Spatial math & bounding-box subdivision
│   ├── gmaps_scraper.py       # Playwright browser automation & metadata parser
│   ├── menu_extractor.py      # Menu tab scraper + OpenCV/PyZbar QR code scanner
│   └── social_scourer.py      # Keyless Reddit & DuckDuckGo search
├── pipeline/
│   ├── __init__.py
│   ├── analyzer.py            # Local Ollama batch analyzer & JSON validator
│   └── discount_helper.py     # Deal deep-links & WhatsApp formatting
├── database.py                # SQLite schema, migrations, FTS5 sync
├── app.py                     # FastAPI backend & SSR routes
├── templates/
│   ├── base.html              # Tailwind base layout
│   ├── index.html             # Split-screen map + sidebar filter drawer
│   └── restaurant.html        # Detailed AI Intelligence Profile page
├── static/
│   ├── css/style.css
│   └── js/
│       ├── map.js             # Leaflet map logic & clustering
│       └── filters.js         # Reactive UI filtering & API sync
├── data/
│   ├── sample_restaurants.json # Offline mock dataset
│   └── restaurants.db         # SQLite database file
├── run_pipeline.py            # Master CLI orchestrator
├── requirements.txt           # Python dependencies
└── Dockerfile                 # Container setup for free cloud hosting

```

---

## Installation & Setup

### 1. Environment Configuration

```bash
# Clone and enter project directory
cd hyd-food-intel

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browser binaries
playwright install chromium

```

### 2. Local Ollama Setup

```bash
# Verify Ollama is installed and running
ollama --version

# Pull the target model
ollama pull qwen3:8b
# Alternative lightweight model:
# ollama pull llama3.1:8b

```

---

## Running the Pipeline

### CLI Usage (`run_pipeline.py`)

* **Quick Test (5 Targets, Live Scraping + LLM):**
```bash
python run_pipeline.py --max-targets 5

```


* **Instant Demo (Bypass Scraping, Seed Sample Data + Run LLM):**
```bash
python run_pipeline.py --skip-scrape

```


* **Full Production Run (All Targets across Telangana/ORR):**
```bash
python run_pipeline.py --max-targets 500 --model qwen3:8b

```


* **Scrape and Ingest Only (Skip LLM & Social Scouring):**
```bash
python run_pipeline.py --skip-social --skip-llm

```



---

## Running the Web Server

```bash
uvicorn app.py:app --host 0.0.0.0 --port 8000 --reload

```

Open `http://localhost:8000` in any modern browser.

---

## API Endpoints

| Method | Endpoint | Description |
| --- | --- | --- |
| `GET` | `/` | Renders the main map explorer interface.

 |
| `GET` | `/restaurant/{slug}` | Renders the deep AI profile page for a restaurant.

 |
| `GET` | `/api/restaurants` | Filterable and sortable JSON list of restaurants.

 |
| `GET` | `/api/restaurants/{slug}` | Full JSON detail object including deal URLs.

 |
| `GET` | `/api/localities` | List of all unique localities in the database.

 |
| `GET` | `/api/export-csv` | Streams the database as an analytical CSV file.

 |
| `GET` | `/api/pipeline/status` | Polling endpoint for background pipeline execution.

 |
| `POST` | `/api/pipeline/run` | Triggers background pipeline execution via API.

 |

---

## LLM Debugging Guide & Invariant Rules

When instructing an LLM to debug or extend this codebase, verify these invariants:

1. **JSON Validation Guardrails (`pipeline/analyzer.py`):**
* Ollama output may contain markdown ticks (`json ... `). The `_extract_json()` utility removes them before calling `json.loads`.


* If parsing fails, `analyze_restaurant()` must always return `_validate_schema({})` populated with `_heuristic_analysis()` to prevent pipeline crashes.




2. **Database FTS5 Synchronization (`database.py`):**
* Whenever `upsert_restaurant()` is invoked, `_fts_sync()` must be called to ensure the virtual full-text search index mirrors the latest JSON values.




3. **Playwright Resiliency (`scraper/gmaps_scraper.py`):**
* Google Maps dynamically updates DOM classes; selections must rely on structural attributes (`role="feed"`, `aria-label`, `data-item-id`) rather than obfuscated CSS classes.


* Run Playwright with `headless=False` for local runs to avoid bot-detection interstitials.




4. **QR Code Scanning Fallbacks (`scraper/menu_extractor.py`):**
* OpenCV (`cv2`) and `pyzbar` imports are wrapped in `try-except` blocks. If C-libraries (`libzbar`) are missing on the host, the pipeline degrades gracefully without throwing fatal exceptions.
