from __future__ import annotations

from datetime import date
from typing import Optional

import pandas as pd
import plotly.graph_objects as go


def _ts(ts) -> Optional[str]:
    """Timezone-aware Timestamp → string Plotly can parse on a datetime axis."""
    if ts is None:
        return None
    try:
        return ts.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def _vline(fig: go.Figure, ts, label: str, color: str) -> None:
    """
    Draw a vertical dotted line + label without using add_vline.
    (add_vline internally calls sum([x, x]) which breaks on string x-values.)
    """
    ts_s = _ts(ts)
    if ts_s is None:
        return
    fig.add_shape(
        type="line",
        x0=ts_s, x1=ts_s,
        y0=0, y1=1,
        yref="paper",
        line=dict(color=color, width=1.2, dash="dot"),
    )
    fig.add_annotation(
        x=ts_s,
        y=0.98,
        yref="paper",
        text=label,
        showarrow=False,
        font=dict(color=color, size=11),
        xanchor="left",
        yanchor="top",
        bgcolor="rgba(255,255,255,0.7)",
    )


def make_tide_chart(
    df: pd.DataFrame,
    day: date,
    threshold: float,
    windows: pd.DataFrame,
    sun_map: dict,
    hour_start: float,
    hour_end: float,
) -> go.Figure:
    day_df = df[df["time"].dt.date == day].copy()
    if day_df.empty:
        return go.Figure()

    day_windows = windows[windows["date"] == day]
    sunrise, sunset = sun_map.get(day, (None, None))

    day_start = day_df["time"].iloc[0]

    fig = go.Figure()

    # Allowed time-of-day band (light blue)
    h_start_ts = day_start.normalize() + pd.Timedelta(hours=hour_start)
    h_end_ts   = day_start.normalize() + pd.Timedelta(hours=hour_end)
    fig.add_vrect(
        x0=_ts(h_start_ts), x1=_ts(h_end_ts),
        fillcolor="rgba(180, 210, 255, 0.10)",
        line_width=0, layer="below",
    )

    # Qualifying windows (green)
    for _, w in day_windows.iterrows():
        fig.add_vrect(
            x0=_ts(w["start"]), x1=_ts(w["end"]),
            fillcolor="rgba(0, 180, 100, 0.20)",
            line_width=0, layer="below",
        )

    # Tide curve
    fig.add_trace(go.Scatter(
        x=day_df["time"].dt.strftime("%Y-%m-%d %H:%M:%S"),
        y=day_df["height"],
        mode="lines",
        line=dict(color="#1f77b4", width=2.5),
        hovertemplate="%{x|%H:%M}  <b>%{y:.2f} ft</b><extra></extra>",
    ))

    # Threshold line (horizontal — add_hline uses y not x, so it's fine)
    fig.add_hline(
        y=threshold,
        line=dict(color="tomato", width=1.5, dash="dash"),
        annotation_text=f"Threshold {threshold:+.2f} ft",
        annotation_position="top right",
        annotation_font_color="tomato",
    )

    # Sunrise / sunset vertical lines
    _vline(fig, sunrise, f"Sunrise {sunrise.strftime('%-I:%M %p') if sunrise else ''}", "#e8a838")
    _vline(fig, sunset,  f"Sunset {sunset.strftime('%-I:%M %p') if sunset else ''}",   "#e07040")

    day_start_s = _ts(day_df["time"].iloc[0])
    day_end_s   = _ts(day_df["time"].iloc[-1])

    fig.update_layout(
        margin=dict(l=40, r=30, t=30, b=40),
        hovermode="x unified",
        showlegend=False,
        xaxis=dict(
            tickformat="%H:%M",
            title=None,
            showgrid=True,
            gridcolor="#eee",
            range=[day_start_s, day_end_s],
        ),
        yaxis=dict(
            title="Height (ft MLLW)",
            zeroline=True,
            zerolinecolor="#ccc",
            showgrid=True,
            gridcolor="#eee",
        ),
        height=380,
        plot_bgcolor="white",
        paper_bgcolor="white",
    )

    return fig
