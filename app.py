from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from datetime import date, timedelta

import pandas as pd
import pytz
import streamlit as st
from astral import LocationInfo
from astral.sun import sun as astral_sun

from charts import make_tide_chart
from constraints import DAY_NAMES, SPECIES_RULES, apply_constraints
from noaa import STATIONS, fetch_predictions

st.set_page_config(page_title="Shellfishing Windows", page_icon="🦪", layout="wide")

# Larger table + expander text
st.markdown("""
<style>
    div[data-testid="stDataFrame"] * { font-size: 15px !important; }
    div[data-testid="stExpander"] summary p { font-size: 16px !important; font-weight: 500; }
</style>
""", unsafe_allow_html=True)

st.title("Shellfishing Windows")

PACIFIC = pytz.timezone("America/Los_Angeles")
END_OF_YEAR = date(date.today().year, 12, 31)


def _today_sun(station_id: str):
    try:
        s = STATIONS[station_id]
        loc = LocationInfo(s["name"], "CA", "America/Los_Angeles", s["lat"], s["lon"])
        times = astral_sun(loc.observer, date=date.today(), tzinfo=PACIFIC)
        return times["sunrise"], times["sunset"]
    except Exception:
        return None, None


def noaa_day_url(station_id: str, day: date) -> str:
    d = day.strftime("%Y%m%d")
    return (
        f"https://tidesandcurrents.noaa.gov/noaatidepredictions.html"
        f"?id={station_id}&units=standard"
        f"&bdate={d}&edate={d}"
        f"&timezone=LST%2FLDT&clock=12hour&datum=MLLW&interval=hilo&action=dailychart"
    )


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Settings")

    station_id = st.selectbox(
        "Tide station",
        options=list(STATIONS.keys()),
        format_func=lambda k: STATIONS[k]["name"],
        index=0,
    )

    species = st.selectbox("Species", options=list(SPECIES_RULES.keys()))
    rule = SPECIES_RULES[species]
    if rule["closed_months"]:
        st.caption(f"⚠️ {rule['notes']}")
    else:
        st.caption(f"✅ {rule['notes']}")

    st.divider()

    threshold = st.slider(
        "Max tide height (ft MLLW)",
        min_value=-3.0, max_value=4.0, value=1.0, step=0.25,
        format="%.2f ft",
    )

    st.divider()

    rise, sset = _today_sun(station_id)
    if rise and sset:
        st.caption(
            f"Today: sunrise {rise.strftime('%-I:%M %p')}, "
            f"sunset {sset.strftime('%-I:%M %p')}"
        )

    def fmt_hour(h: float) -> str:
        hh = int(h) % 24
        mm = int((h - int(h)) * 60)
        suffix = "am" if hh < 12 else "pm"
        hh12 = hh % 12 or 12
        return f"{hh12}:{mm:02d}{suffix}"

    hour_range = st.slider(
        "Allowed hours",
        min_value=0.0, max_value=24.0, value=(0.0, 24.0), step=0.5,
        format="%.1f",
        help="Set 0–24 to allow any time of day.",
    )
    hour_start, hour_end = hour_range
    st.caption(f"{fmt_hour(hour_start)} → {fmt_hour(hour_end)}")

    st.divider()

    selected_day_names = st.multiselect(
        "Days of week",
        options=DAY_NAMES,
        default=["Sat", "Sun"],
        help="Leave empty to allow any day.",
    )
    allowed_days = {DAY_NAMES.index(d) for d in selected_day_names}

    st.divider()

    start_date = st.date_input("Start date", value=date.today(), max_value=END_OF_YEAR)
    end_date = st.date_input(
        "End date",
        value=min(date.today() + timedelta(weeks=4), END_OF_YEAR),
        min_value=start_date,
        max_value=END_OF_YEAR,
    )
    st.caption(f"Searching {start_date} → {end_date}")

    st.divider()

    min_window = st.slider(
        "Min opportunity duration (min)",
        min_value=15, max_value=120, value=30, step=15,
        help="Minimum consecutive minutes where ALL conditions are met.",
    )


# ── Data fetch ────────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner="Fetching tide data…")
def load_data(sid: str, s: date, e: date) -> pd.DataFrame:
    return fetch_predictions(sid, s, e)


try:
    df = load_data(station_id, start_date, end_date)
except Exception as exc:
    st.error(f"Could not fetch NOAA data: {exc}")
    st.stop()

# ── Apply constraints ─────────────────────────────────────────────────────────
with st.spinner("Finding windows…"):
    df_annotated, windows, sun_map = apply_constraints(
        df,
        station_id=station_id,
        threshold=threshold,
        species=species,
        allowed_days=allowed_days,
        hour_start=hour_start,
        hour_end=hour_end,
        min_window_minutes=min_window,
    )

# ── Results ───────────────────────────────────────────────────────────────────
if windows.empty:
    st.info("No qualifying windows found. Try relaxing the constraints.")
    st.stop()

n_days = windows["date"].nunique()
st.success(
    f"Found **{len(windows)}** window{'s' if len(windows) != 1 else ''} "
    f"across **{n_days}** day{'s' if n_days != 1 else ''}."
)

# Summary table — one row per window, NOAA link per row
table_rows = []
for _, w in windows.iterrows():
    rise_dt, sset_dt = sun_map.get(w["date"], (None, None))
    table_rows.append({
        "Date":     w["date"].strftime("%a %b %-d"),
        "Sunrise":  rise_dt.strftime("%-I:%M %p") if rise_dt else "—",
        "Sunset":   sset_dt.strftime("%-I:%M %p") if sset_dt else "—",
        "Start":    w["start"].strftime("%-I:%M %p"),
        "End":      w["end"].strftime("%-I:%M %p"),
        "Duration": f"{w['duration_min']} min",
        "Min Tide": f"{w['min_tide']:+.2f} ft",
        "NOAA":     noaa_day_url(station_id, w["date"]),
    })

table_df = pd.DataFrame(table_rows)
selection = st.dataframe(
    table_df,
    use_container_width=True,
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row",
    column_config={
        "NOAA": st.column_config.LinkColumn("NOAA Chart", display_text="Open ↗"),
    },
)

qualifying_days = sorted(windows["date"].unique())

# Resolve which day to chart (selected row → that day; nothing selected → all days)
selected_rows = selection.selection.rows
if selected_rows:
    selected_date_str = table_rows[selected_rows[0]]["Date"]
    chart_days = [d for d in qualifying_days if d.strftime("%a %b %-d") == selected_date_str]
    st.caption("Click a different row to switch, or click the same row again to deselect.")
else:
    chart_days = qualifying_days

st.divider()

# ── Tide chart(s) ─────────────────────────────────────────────────────────────
for day in chart_days:
    day_wins = windows[windows["date"] == day]
    starts = "  |  ".join(day_wins["start"].dt.strftime("%-I:%M %p"))
    label = f"{day.strftime('%A, %b %-d')} — {starts}"
    with st.expander(label, expanded=True):
        fig = make_tide_chart(
            df_annotated, day, threshold, windows, sun_map, hour_start, hour_end
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
