from __future__ import annotations

from datetime import date

import pandas as pd
import pytz
from astral import LocationInfo
from astral.sun import sun

from noaa import STATIONS

# CA DFW recreational harvest rules (simplified)
SPECIES_RULES: dict[str, dict] = {
    "Mussels": {
        "closed_months": set(range(5, 11)),  # May–Oct biotoxin quarantine
        "notes": "CA closes May–Oct (biotoxin season)",
    },
    "Clams / Oysters / Uni": {
        "closed_months": set(),
        "notes": "Open year-round (check local postings)",
    },
}

PACIFIC = pytz.timezone("US/Pacific")
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _sun_times(day: date, station_id: str) -> tuple:
    s = STATIONS[station_id]
    loc = LocationInfo(s["name"], "CA", "US/Pacific", s["lat"], s["lon"])
    times = sun(loc.observer, date=day, tzinfo=PACIFIC)
    return times["sunrise"], times["sunset"]


def apply_constraints(
    df: pd.DataFrame,
    station_id: str,
    threshold: float,
    species: str,
    allowed_days: set,       # set of weekday ints: 0=Mon … 6=Sun
    hour_start: float,       # earliest allowed hour (e.g. 6.0)
    hour_end: float,         # latest allowed hour   (e.g. 20.0)
    min_window_minutes: int = 30,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """
    Returns:
      - df with constraint columns added
      - windows DataFrame: one row per qualifying window
      - sun_map: {date: (sunrise, sunset)} for every date in df
    """
    df = df.copy()

    # 1. Tide threshold
    df["ok_tide"] = df["height"] <= threshold

    # 2. Compute sunrise/sunset for every date (used by charts even when not a constraint)
    unique_dates = df["time"].dt.date.unique()
    sun_map: dict[date, tuple] = {}
    for d in unique_dates:
        try:
            sun_map[d] = _sun_times(d, station_id)
        except Exception:
            sun_map[d] = (None, None)

    # 3. Time-of-day window
    hour_of_day = df["time"].dt.hour + df["time"].dt.minute / 60.0
    df["ok_time"] = (hour_of_day >= hour_start) & (hour_of_day <= hour_end)

    # 4. Day of week
    if allowed_days:
        df["ok_day"] = df["time"].dt.dayofweek.isin(allowed_days)
    else:
        df["ok_day"] = True  # no restriction if nothing selected

    # 5. Species season
    closed_months = SPECIES_RULES.get(species, {}).get("closed_months", set())
    df["ok_season"] = ~df["time"].dt.month.isin(closed_months)

    # Combined
    df["qualifying"] = (
        df["ok_tide"] & df["ok_time"] & df["ok_day"] & df["ok_season"]
    )

    # 6. Group consecutive qualifying rows into windows
    df["window_id"] = (df["qualifying"] != df["qualifying"].shift()).cumsum()
    qualifying_df = df[df["qualifying"]]
    if qualifying_df.empty:
        empty_windows = pd.DataFrame(
            columns=["start", "end", "min_tide", "date", "duration_min", "sunrise", "sunset"]
        )
        return df, empty_windows, sun_map

    windows_raw = (
        qualifying_df
        .groupby("window_id")
        .agg(
            start=("time", "first"),
            end=("time", "last"),
            min_tide=("height", "min"),
            date=("time", lambda x: x.iloc[0].date()),
        )
        .reset_index(drop=True)
    )

    windows_raw["duration_min"] = (
        (windows_raw["end"] - windows_raw["start"]).dt.total_seconds() / 60
    ).astype(int)
    windows = windows_raw[windows_raw["duration_min"] >= min_window_minutes].copy()
    windows = windows.sort_values("start").reset_index(drop=True)

    # Attach sun times for chart rendering
    windows["sunrise"] = windows["date"].map(lambda d: sun_map.get(d, (None, None))[0])
    windows["sunset"]  = windows["date"].map(lambda d: sun_map.get(d, (None, None))[1])

    return df, windows, sun_map
