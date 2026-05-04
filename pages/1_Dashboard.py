"""
Dashboard principal: KPIs, gráficos y filtros.
"""

from __future__ import annotations

import streamlit as st

from components.charts import (
    cost_waterfall,
    revenue_over_time,
    sales_by_province,
    sales_by_status,
    sales_by_weekday,
    top_products,
)
from core.database import get_db, has_data
from core.metrics import (
    get_cost_breakdown,
    get_filter_options,
    get_kpis,
    get_revenue_over_time,
    get_sales_by_province,
    get_sales_by_status,
    get_top_products,
)

st.set_page_config(
    page_title="Dashboard — ML Ventas",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS ───────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
  header[data-testid="stHeader"] { display: none; }

  [data-testid="metric-container"] {
    background: #161b22;
    border: 1px solid #21262d;
    border-radius: 10px;
    padding: 1rem 1.2rem;
  }
  [data-testid="metric-container"] label {
    color: #8b949e !important;
    font-size: 0.78rem !important;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  [data-testid="metric-container"] [data-testid="stMetricValue"] {
    font-size: 1.45rem !important;
    font-weight: 700;
  }

  .section-title {
    color: #8b949e;
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin: 1.5rem 0 0.5rem 0;
  }

  hr { border-color: #21262d !important; }

  /* Sidebar */
  [data-testid="stSidebar"] { background: #0d1117; border-right: 1px solid #21262d; }
</style>
""", unsafe_allow_html=True)

# ── Guard: redirigir si no hay datos ─────────────────────────────────────────

conn = get_db()

if not has_data(conn):
    st.warning("No hay datos cargados en esta sesión.")
    if st.button("← Cargar archivo"):
        st.switch_page("app.py")
    st.stop()

# ── Filtros (sidebar) ─────────────────────────────────────────────────────────

opts = get_filter_options(conn)

with st.sidebar:
    st.markdown("### Filtros")
    st.divider()

    # Rango de fechas
    date_from = st.date_input(
        "Desde",
        value=opts["date_min"],
        min_value=opts["date_min"],
        max_value=opts["date_max"],
        key="filter_date_from",
    )
    date_to = st.date_input(
        "Hasta",
        value=opts["date_max"],
        min_value=opts["date_min"],
        max_value=opts["date_max"],
        key="filter_date_to",
    )

    # Estado
    selected_statuses = st.multiselect(
        "Estado de venta",
        options=opts["statuses"],
        default=[],
        placeholder="Todos",
        key="filter_status",
    )

    # Provincia
    selected_provinces = st.multiselect(
        "Provincia",
        options=opts["provinces"],
        default=[],
        placeholder="Todas",
        key="filter_province",
    )

    # Producto
    selected_products = st.multiselect(
        "Producto",
        options=opts["products"],
        default=[],
        placeholder="Todos",
        key="filter_product",
    )

    st.divider()

    # Granularidad del gráfico temporal
    granularity = st.radio(
        "Agrupar por",
        options=["day", "week", "month"],
        format_func=lambda x: {"day": "Día", "week": "Semana", "month": "Mes"}[x],
        index=0,
        horizontal=True,
        key="filter_granularity",
    )

    st.divider()
    if st.button("← Volver al inicio", use_container_width=True):
        st.switch_page("app.py")

# ── Construir filtros activos ─────────────────────────────────────────────────

filters: dict = {}
if date_from:
    filters["date_from"] = date_from
if date_to:
    filters["date_to"] = date_to
if selected_statuses:
    filters["status"] = selected_statuses
if selected_provinces:
    filters["province"] = selected_provinces
if selected_products:
    filters["product"] = selected_products

# ── Header ────────────────────────────────────────────────────────────────────

st.markdown("## 📈 Dashboard de ventas")
st.caption("Datos de la sesión actual · se borran al cerrar el navegador")
st.divider()

# ── KPIs ──────────────────────────────────────────────────────────────────────

kpis = get_kpis(conn, filters)

st.markdown('<p class="section-title">Resumen financiero</p>', unsafe_allow_html=True)

col1, col2, col3, col4, col5, col6 = st.columns(6)

col1.metric(
    "Ingresos netos",
    f"${kpis['ingresos_netos']:,.0f}",
    help="Total ARS después de comisiones, envíos e impuestos (excluye canceladas)",
)
col2.metric(
    "Ingresos brutos",
    f"${kpis['ingresos_brutos']:,.0f}",
    help="Suma de ingresos por productos antes de deducciones",
)
col3.metric(
    "Comisión ML",
    f"${kpis['comisiones_ml']:,.0f}",
    delta=f"-{kpis['tasa_comision']:.1f}% del bruto",
    delta_color="inverse",
    help="Total cobrado por MercadoLibre como cargo por venta",
)
col4.metric(
    "Ticket promedio",
    f"${kpis['ticket_promedio']:,.0f}",
    help="Ingreso neto promedio por venta",
)
col5.metric(
    "Unidades vendidas",
    f"{kpis['total_unidades']:,}",
    help="Suma de unidades en ventas no canceladas",
)
col6.metric(
    "Ventas totales",
    f"{kpis['total_ventas']:,}",
    delta=f"{kpis['ventas_entregadas']} entregadas",
    help="Ventas en el período filtrado (excluye canceladas)",
)

st.markdown("")

col_a, col_b, col_c = st.columns(3)
col_a.metric("Impuestos", f"${kpis['impuestos']:,.0f}")
col_b.metric(
    "Costo envío",
    f"${kpis['costo_envio']:,.0f}",
    delta_color="inverse",
    help="Costos de envío cobrados por ML al vendedor",
)
col_c.metric(
    "Con reclamo",
    f"{kpis['ventas_con_reclamo']}",
    delta=f"{kpis['ventas_con_reclamo'] / max(kpis['total_ventas'], 1) * 100:.1f}% del total",
    delta_color="inverse",
)

# ── Gráfico temporal ──────────────────────────────────────────────────────────

st.divider()
col_title, col_metric = st.columns([3, 2])
with col_title:
    st.markdown('<p class="section-title">Evolución temporal</p>', unsafe_allow_html=True)
with col_metric:
    time_metric = st.radio(
        "Métrica",
        options=["revenue", "units", "count"],
        format_func=lambda x: {"revenue": "Ingresos netos", "units": "Unidades", "count": "Cant. ventas"}[x],
        horizontal=True,
        key="filter_time_metric",
        label_visibility="collapsed",
    )

df_time = get_revenue_over_time(conn, filters, granularity)
st.plotly_chart(revenue_over_time(df_time, granularity, time_metric), use_container_width=True)

# ── Estado + Día de semana ────────────────────────────────────────────────────

st.divider()
col_left, col_right = st.columns(2)

with col_left:
    st.markdown('<p class="section-title">Distribución por estado</p>', unsafe_allow_html=True)
    df_status = get_sales_by_status(conn, filters)
    st.plotly_chart(sales_by_status(df_status), use_container_width=True)

with col_right:
    st.markdown('<p class="section-title">Ventas por día de la semana</p>', unsafe_allow_html=True)
    st.plotly_chart(sales_by_weekday(df_time), use_container_width=True)

# ── Top productos ─────────────────────────────────────────────────────────────

st.divider()
st.markdown('<p class="section-title">Productos</p>', unsafe_allow_html=True)

tab_rev, tab_units = st.tabs(["Por ingresos netos", "Por unidades vendidas"])

with tab_rev:
    df_top_rev = get_top_products(conn, filters, by="revenue", limit=12)
    st.plotly_chart(top_products(df_top_rev, by="revenue"), use_container_width=True)

with tab_units:
    df_top_units = get_top_products(conn, filters, by="units", limit=12)
    st.plotly_chart(top_products(df_top_units, by="units"), use_container_width=True)

# ── Provincia + Waterfall ─────────────────────────────────────────────────────

st.divider()
col_geo, col_costs = st.columns(2)

with col_geo:
    st.markdown('<p class="section-title">Ventas por provincia</p>', unsafe_allow_html=True)
    df_prov = get_sales_by_province(conn, filters)
    st.plotly_chart(sales_by_province(df_prov), use_container_width=True)

with col_costs:
    st.markdown('<p class="section-title">Desglose de ingresos</p>', unsafe_allow_html=True)
    df_costs = get_cost_breakdown(conn, filters)
    st.plotly_chart(cost_waterfall(df_costs), use_container_width=True)

# ── Footer ────────────────────────────────────────────────────────────────────

st.divider()
st.caption(f"Mostrando {kpis['total_ventas']:,} ventas · {kpis['total_registros']:,} registros totales en sesión")
