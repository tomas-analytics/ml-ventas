"""
Funciones que construyen figuras Plotly a partir de DataFrames de métricas.
Todas retornan go.Figure y usan la paleta de colores del proyecto.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ── Paleta ────────────────────────────────────────────────────────────────────

COLORS = {
    "yellow":  "#FFE600",
    "blue":    "#3483FA",
    "green":   "#00A650",
    "red":     "#EF4444",
    "orange":  "#F59E0B",
    "purple":  "#8B5CF6",
    "gray":    "#6B7280",
    "bg":      "#0d1117",
    "bg2":     "#161b22",
    "text":    "#e6edf3",
    "grid":    "#21262d",
}

STATUS_COLORS = {
    "Entregado":      COLORS["green"],
    "Cancelado":      COLORS["red"],
    "Cancelada":      COLORS["red"],
    "Reclamo abierto": COLORS["orange"],
    "En camino":      COLORS["blue"],
    "En preparación": COLORS["purple"],
}

_LAYOUT_BASE = dict(
    paper_bgcolor=COLORS["bg"],
    plot_bgcolor=COLORS["bg"],
    font=dict(color=COLORS["text"], family="Inter, sans-serif", size=13),
    margin=dict(l=16, r=16, t=40, b=16),
    legend=dict(
        bgcolor="rgba(0,0,0,0)",
        bordercolor=COLORS["grid"],
        font=dict(size=12),
    ),
    xaxis=dict(gridcolor=COLORS["grid"], zerolinecolor=COLORS["grid"]),
    yaxis=dict(gridcolor=COLORS["grid"], zerolinecolor=COLORS["grid"]),
)


def _apply_base(fig: go.Figure, title: str = "") -> go.Figure:
    fig.update_layout(**_LAYOUT_BASE, title=dict(text=title, font=dict(size=15)))
    return fig


def _fmt_ars(value: float) -> str:
    if abs(value) >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    if abs(value) >= 1_000:
        return f"${value / 1_000:.0f}K"
    return f"${value:,.0f}"


# ── Revenue en el tiempo ──────────────────────────────────────────────────────

def revenue_over_time(df: pd.DataFrame, granularity: str = "day", metric: str = "revenue") -> go.Figure:
    if df.empty:
        return _empty_chart("Sin datos para el período seleccionado")

    period_label = {"day": "por día", "week": "por semana", "month": "por mes"}.get(granularity, "")
    fig = go.Figure()

    if metric == "revenue":
        fig.add_trace(go.Scatter(
            x=df["periodo"], y=df["ingresos_brutos"],
            name="Ingresos brutos",
            line=dict(color=COLORS["blue"], width=2, dash="dot"),
            hovertemplate="%{x}<br>Bruto: $%{y:,.0f}<extra></extra>",
        ))
        fig.add_trace(go.Scatter(
            x=df["periodo"], y=df["ingresos_netos"],
            name="Ingresos netos",
            line=dict(color=COLORS["yellow"], width=2.5),
            fill="tozeroy", fillcolor="rgba(255,230,0,0.07)",
            hovertemplate="%{x}<br>Neto: $%{y:,.0f}<extra></extra>",
        ))
        _apply_base(fig, f"Evolución de ingresos {period_label}")
        fig.update_yaxes(tickprefix="$", tickformat=",.0f")

    elif metric == "units":
        fig.add_trace(go.Bar(
            x=df["periodo"], y=df["unidades"],
            name="Unidades",
            marker=dict(color=COLORS["blue"], opacity=0.85),
            hovertemplate="%{x}<br>%{y:,} unidades<extra></extra>",
        ))
        _apply_base(fig, f"Unidades vendidas {period_label}")
        fig.update_yaxes(tickformat=",")

    elif metric == "count":
        fig.add_trace(go.Bar(
            x=df["periodo"], y=df["cantidad_ventas"],
            name="Ventas",
            marker=dict(color=COLORS["yellow"], opacity=0.85),
            hovertemplate="%{x}<br>%{y:,} ventas<extra></extra>",
        ))
        _apply_base(fig, f"Cantidad de ventas {period_label}")
        fig.update_yaxes(tickformat=",")

    fig.update_xaxes(tickformat="%d/%m/%y")
    return fig


# ── Ventas por estado ─────────────────────────────────────────────────────────

def sales_by_status(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return _empty_chart()

    colors = [STATUS_COLORS.get(s, COLORS["gray"]) for s in df["estado"]]

    fig = go.Figure(go.Pie(
        labels=df["estado"],
        values=df["cantidad"],
        hole=0.55,
        marker=dict(colors=colors, line=dict(color=COLORS["bg"], width=2)),
        textinfo="percent+label",
        hovertemplate="%{label}<br>%{value} ventas (%{percent})<extra></extra>",
    ))

    _apply_base(fig, "Ventas por estado")
    fig.update_layout(showlegend=False)
    return fig


# ── Top productos ─────────────────────────────────────────────────────────────

def top_products(df: pd.DataFrame, by: str = "revenue") -> go.Figure:
    if df.empty:
        return _empty_chart()

    df = df.copy().sort_values(
        "ingresos_netos" if by == "revenue" else "unidades"
    )

    value_col = "ingresos_netos" if by == "revenue" else "unidades"
    color = COLORS["yellow"] if by == "revenue" else COLORS["blue"]
    fmt = _fmt_ars if by == "revenue" else lambda v: f"{v:,.0f}"

    fig = go.Figure(go.Bar(
        x=df[value_col],
        y=df["producto"],
        orientation="h",
        marker=dict(
            color=df[value_col],
            colorscale=[[0, COLORS["bg2"]], [1, color]],
            showscale=False,
        ),
        text=[fmt(v) for v in df[value_col]],
        textposition="outside",
        hovertemplate="%{y}<br>%{x:,.0f}<extra></extra>",
        cliponaxis=False,
    ))

    title = "Top productos por ingresos netos" if by == "revenue" else "Top productos por unidades"
    _apply_base(fig, title)
    fig.update_layout(height=max(300, len(df) * 42))
    fig.update_xaxes(showticklabels=False)
    return fig


# ── Por provincia ─────────────────────────────────────────────────────────────

def sales_by_province(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return _empty_chart()

    df = df.head(15).sort_values("cantidad")

    fig = go.Figure(go.Bar(
        x=df["cantidad"],
        y=df["provincia"],
        orientation="h",
        marker=dict(
            color=df["cantidad"],
            colorscale=[[0, COLORS["bg2"]], [1, COLORS["blue"]]],
            showscale=False,
        ),
        text=df["cantidad"],
        textposition="outside",
        hovertemplate="%{y}<br>%{x} ventas<extra></extra>",
        cliponaxis=False,
    ))

    _apply_base(fig, "Ventas por provincia")
    fig.update_layout(height=max(300, len(df) * 38))
    fig.update_xaxes(showticklabels=False)
    return fig


# ── Waterfall de costos ───────────────────────────────────────────────────────

def cost_waterfall(df: pd.DataFrame) -> go.Figure:
    """
    Muestra cómo los ingresos brutos se transforman en ingresos netos
    a través de los distintos costos.
    """
    if df.empty or len(df) < 2:
        return _empty_chart()

    labels = df["componente"].tolist()
    values = df["valor"].tolist()
    tipos = df["tipo"].tolist()

    measures = []
    bar_colors = []
    for t in tipos:
        if t == "ingreso":
            measures.append("absolute")
            bar_colors.append(COLORS["blue"])
        elif t == "neto":
            measures.append("total")
            bar_colors.append(COLORS["yellow"])
        else:
            measures.append("relative")
            bar_colors.append(COLORS["red"])

    # Los costos van en negativo en el waterfall
    waterfall_values = []
    for v, t in zip(values, tipos):
        if t == "costo":
            waterfall_values.append(-abs(v))
        else:
            waterfall_values.append(v)

    fig = go.Figure(go.Waterfall(
        orientation="v",
        measure=measures,
        x=labels,
        y=waterfall_values,
        connector=dict(line=dict(color=COLORS["grid"], width=1)),
        increasing=dict(marker_color=COLORS["green"]),
        decreasing=dict(marker_color=COLORS["red"]),
        totals=dict(marker_color=COLORS["yellow"]),
        texttemplate="%{y:$,.0f}",
        textposition="outside",
        cliponaxis=False,
    ))

    _apply_base(fig, "Desglose: de ingresos brutos a ingresos netos")
    fig.update_yaxes(tickprefix="$", tickformat=",.0f")
    return fig


# ── Ventas por día de la semana ───────────────────────────────────────────────

def sales_by_weekday(df: pd.DataFrame) -> go.Figure:
    """df debe tener columnas: periodo, cantidad_ventas"""
    if df.empty:
        return _empty_chart()

    import numpy as np

    days_es = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]

    df = df.copy()
    df["periodo"] = pd.to_datetime(df["periodo"])
    df["weekday"] = df["periodo"].dt.weekday
    by_day = df.groupby("weekday")["cantidad_ventas"].sum().reindex(range(7), fill_value=0)

    fig = go.Figure(go.Bar(
        x=days_es,
        y=by_day.values,
        marker=dict(
            color=by_day.values,
            colorscale=[[0, COLORS["bg2"]], [1, COLORS["yellow"]]],
            showscale=False,
        ),
        text=by_day.values,
        textposition="outside",
        hovertemplate="%{x}: %{y} ventas<extra></extra>",
        cliponaxis=False,
    ))

    _apply_base(fig, "Ventas por día de la semana")
    fig.update_yaxes(showticklabels=False)
    return fig


# ── Helper ────────────────────────────────────────────────────────────────────

def _empty_chart(msg: str = "Sin datos") -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(
        text=msg,
        xref="paper", yref="paper",
        x=0.5, y=0.5,
        showarrow=False,
        font=dict(color=COLORS["gray"], size=14),
    )
    _apply_base(fig)
    return fig
