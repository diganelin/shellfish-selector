from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import requests
import requests_cache

requests_cache.install_cache(
    "noaa_cache",
    backend="sqlite",
    expire_after=timedelta(days=7),
)

BASE = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"

STATIONS: dict[str, dict] = {
    "9414131": {"name": "Pillar Point (Half Moon Bay)", "lat": 37.5041, "lon": -122.4816},
    "9414275": {"name": "Ocean Beach (SF outer coast)",  "lat": 37.7750, "lon": -122.5130},
    "9414290": {"name": "San Francisco",                "lat": 37.8063, "lon": -122.4659},
    "9415020": {"name": "Point Reyes",                  "lat": 37.9963, "lon": -122.9767},
    "9415625": {"name": "Bodega Bay",                   "lat": 38.3083, "lon": -123.0550},
    "9414750": {"name": "Alameda",                      "lat": 37.7717, "lon": -122.3000},
}


def fetch_predictions(station_id: str, start: date, end: date) -> pd.DataFrame:
    """Fetch 6-minute tide predictions from NOAA, splitting into <=31-day chunks."""
    chunks: list[list] = []
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=30), end)
        params = {
            "begin_date": cursor.strftime("%Y%m%d"),
            "end_date":   chunk_end.strftime("%Y%m%d"),
            "station":    station_id,
            "product":    "predictions",
            "datum":      "MLLW",
            "time_zone":  "gmt",
            "interval":   "6",
            "units":      "english",
            "application":"shellfishing_app",
            "format":     "json",
        }
        resp = requests.get(BASE, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if "predictions" not in data:
            raise ValueError(f"NOAA error: {data.get('error', {}).get('message', data)}")
        chunks.extend(data["predictions"])
        cursor = chunk_end + timedelta(days=1)

    df = pd.DataFrame(chunks)
    df["t"] = pd.to_datetime(df["t"], utc=True)
    df["v"] = pd.to_numeric(df["v"])
    df = df.rename(columns={"t": "time", "v": "height"}).drop(columns=["s"], errors="ignore")
    # Convert GMT → America/Los_Angeles (handles DST)
    df["time"] = df["time"].dt.tz_convert("America/Los_Angeles")
    df = df.sort_values("time").reset_index(drop=True)
    return df
