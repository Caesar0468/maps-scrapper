#!/usr/bin/env python3
"""FastAPI application — REST endpoints and SSR restaurant profiles."""

from __future__ import annotations

import csv
import io
import json
import math
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import database as db
from pipeline.discount_helper import get_deal_links, whatsapp_share_text, whatsapp_share_url
from scraper.grid_generator import haversine_km

BASE_DIR = Path(__file__).parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title="HY Food Intel", version="1.0.0", docs_url="/api/docs")

_pipeline_lock = threading.Lock()
_pipeline_state: dict[str, Any] = {"running": False, "stage": "idle", "progress": {}}


def get_db():
    return db.init_db()


@app.on_event("startup")
def startup():
    get_db()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    conn = get_db()
    localities = db.get_localities(conn)
    conn.close()
    return TEMPLATES.TemplateResponse(
        "index.html",
        {"request": request, "localities": localities},
    )


@app.get("/restaurant/{slug}", response_class=HTMLResponse)
async def restaurant_profile(request: Request, slug: str):
    conn = get_db()
    restaurant = db.get_restaurant_by_slug(conn, slug)
    conn.close()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurant not found")

    deals = get_deal_links(restaurant)
    wa_url = whatsapp_share_url(restaurant)
    wa_text = whatsapp_share_text(restaurant)

    return TEMPLATES.TemplateResponse(
        "restaurant.html",
        {
            "request": request,
            "r": restaurant,
            "deals": deals,
            "wa_url": wa_url,
            "wa_text": wa_text,
        },
    )


def _apply_filters(
    restaurants: list[dict[str, Any]],
    *,
    q: str = "",
    locality: str = "",
    cuisine: str = "",
    open_now: bool = False,
    pure_veg: bool = False,
    avoid_veg: bool = False,
    avoid_nonveg: bool = False,
    hype: str = "",
    low_fake_risk: bool = False,
    budget_min: int = 0,
    budget_max: int = 50000,
    vibe: str = "",
    lat: float | None = None,
    lon: float | None = None,
    radius_km: float | None = None,
) -> list[dict[str, Any]]:
    results = []
    for r in restaurants:
        ai = r.get("ai_analysis") or {}
        if isinstance(ai, str):
            try:
                ai = json.loads(ai)
            except json.JSONDecodeError:
                ai = {}

        if q:
            haystack = f"{r.get('name','')} {r.get('locality','')} {' '.join(ai.get('cuisines',[]))} {' '.join(ai.get('must_try_items',[]))}".lower()
            if q.lower() not in haystack:
                continue

        if locality and r.get("locality") != locality:
            continue

        if cuisine:
            cuisines = [c.lower() for c in ai.get("cuisines", [])]
            if cuisine.lower() not in cuisines:
                continue

        if open_now and not r.get("is_open_now"):
            continue

        if pure_veg and not ai.get("is_pure_veg"):
            continue

        dw = ai.get("dietary_warning", "None")
        if avoid_veg and dw == "Avoid Veg Here":
            continue
        if avoid_nonveg and dw == "Avoid Non-Veg Here":
            continue

        if hype and ai.get("hype_verdict") != hype:
            continue

        if low_fake_risk and ai.get("fake_review_risk") != "Low":
            continue

        spend = ai.get("calculated_spend_for_two", 0)
        if spend and (spend < budget_min or spend > budget_max):
            continue

        if vibe:
            tags = [t.lower() for t in ai.get("vibe_tags", [])]
            if vibe.lower() not in " ".join(tags):
                continue

        if lat is not None and lon is not None and radius_km is not None:
            rlat, rlon = r.get("latitude"), r.get("longitude")
            if rlat and rlon:
                dist = haversine_km(lat, lon, rlat, rlon)
                r["distance_km"] = round(dist, 2)
                if dist > radius_km:
                    continue
            else:
                continue

        r["_ai"] = ai
        results.append(r)

    return results


@app.get("/api/restaurants")
async def api_restaurants(
    q: str = Query("", description="Search query"),
    locality: str = Query(""),
    cuisine: str = Query(""),
    open_now: bool = Query(False),
    pure_veg: bool = Query(False),
    exclude_avoid_veg: bool = Query(False),
    exclude_avoid_nonveg: bool = Query(False),
    hype: str = Query(""),
    low_fake_risk: bool = Query(False),
    budget_min: int = Query(0),
    budget_max: int = Query(50000),
    vibe: str = Query(""),
    lat: float | None = Query(None),
    lon: float | None = Query(None),
    radius_km: float | None = Query(None),
    sort: str = Query("reviews"),
):
    conn = get_db()
    all_r = db.get_all_restaurants(conn)
    conn.close()

    filtered = _apply_filters(
        all_r,
        q=q,
        locality=locality,
        cuisine=cuisine,
        open_now=open_now,
        pure_veg=pure_veg,
        avoid_veg=exclude_avoid_veg,
        avoid_nonveg=exclude_avoid_nonveg,
        hype=hype,
        low_fake_risk=low_fake_risk,
        budget_min=budget_min,
        budget_max=budget_max,
        vibe=vibe,
        lat=lat,
        lon=lon,
        radius_km=radius_km,
    )

    if sort == "rating":
        filtered.sort(key=lambda x: (-(x.get("rating") or 0), -(x.get("review_count") or 0)))
    elif sort == "name":
        filtered.sort(key=lambda x: x.get("name", "").lower())
    elif sort == "distance" and lat and lon:
        filtered.sort(key=lambda x: x.get("distance_km", 9999))
    elif sort == "hype":
        filtered.sort(key=lambda x: -(x.get("_ai", {}).get("hype_score", 0)))
    else:
        filtered.sort(key=lambda x: (-(x.get("review_count") or 0), -(x.get("rating") or 0)))

    for r in filtered:
        r.pop("_ai", None)

    return JSONResponse({"count": len(filtered), "restaurants": filtered})


@app.get("/api/restaurants/{slug}")
async def api_restaurant_detail(slug: str):
    conn = get_db()
    restaurant = db.get_restaurant_by_slug(conn, slug)
    conn.close()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Not found")
    restaurant["deals"] = get_deal_links(restaurant)
    restaurant["whatsapp_url"] = whatsapp_share_url(restaurant)
    return JSONResponse(restaurant)


@app.get("/api/localities")
async def api_localities():
    conn = get_db()
    localities = db.get_localities(conn)
    conn.close()
    return JSONResponse({"localities": localities})


@app.get("/api/export-csv")
async def export_csv():
    conn = get_db()
    restaurants = db.get_all_restaurants(conn)
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "name", "slug", "rating", "review_count", "locality", "address",
        "phone", "website", "latitude", "longitude", "google_maps_url",
        "hype_verdict", "dietary_warning", "spend_for_two", "cuisines",
    ])
    for r in restaurants:
        ai = r.get("ai_analysis") or {}
        if isinstance(ai, str):
            try:
                ai = json.loads(ai)
            except json.JSONDecodeError:
                ai = {}
        writer.writerow([
            r.get("name"), r.get("slug"), r.get("rating"), r.get("review_count"),
            r.get("locality"), r.get("address"), r.get("phone"), r.get("website"),
            r.get("latitude"), r.get("longitude"), r.get("google_maps_url"),
            ai.get("hype_verdict"), ai.get("dietary_warning"),
            ai.get("calculated_spend_for_two"), ", ".join(ai.get("cuisines", [])),
        ])

    output.seek(0)
    filename = f"hy_food_intel_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/pipeline/status")
async def pipeline_status():
    return JSONResponse(_pipeline_state)


@app.post("/api/pipeline/run")
async def run_pipeline_api(
    max_targets: int = Query(5, ge=1, le=500),
    skip_scrape: bool = Query(False),
):
    if _pipeline_state["running"]:
        return JSONResponse({"message": "Pipeline already running"}, status_code=409)

    def _run():
        global _pipeline_state
        _pipeline_state = {"running": True, "stage": "starting", "progress": {}}
        try:
            from run_pipeline import run_full_pipeline
            run_full_pipeline(
                max_targets=max_targets,
                skip_scrape=skip_scrape,
                progress_callback=lambda p: _pipeline_state.update({"stage": p.get("stage", ""), "progress": p}),
            )
            _pipeline_state["stage"] = "completed"
        except Exception as exc:
            _pipeline_state["stage"] = f"error: {exc}"
        finally:
            _pipeline_state["running"] = False

    if _pipeline_lock.acquire(blocking=False):
        threading.Thread(target=_run, daemon=True).start()
        _pipeline_lock.release()

    return JSONResponse({"message": "Pipeline started", "status": _pipeline_state})


app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
