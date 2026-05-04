"""
Explorador de datos: tabla de ventas con filtros y descarga CSV.
"""

from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from core.database import get_db, has_data
from core.metrics import get_filter_options, get_sales_table, get_total_rows

st.set_page_config(
    page_title="Datos — ML Ventas",
    page_icon="🗂️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
  header[data-testid="stHeader"] { display: none; }
  hr { border-color: #21262d !important; }
  [data-testid="stSidebar"] { background: #0d1117; border-right: 1px solid #21262d; }
</style>
""", unsafe_allow_html=True)

conn = get_db()

if not has_data(conn):
    st.warning("No hay datos cargados en esta sesión.")
    if st.button("← Cargar archivo"):
        st.switch_page("app.py")
    st.stop()

# ── Filtros ───────────────────────────────────────────────────────────────────

opts = get_filter_options(conn)

with st.sidebar:
    st.markdown("### Filtros")
    st.divider()

    date_from = st.date_input(
        "Desde",
        value=opts["date_min"],
        min_value=opts["date_min"],
        max_value=opts["date_max"],
    )
    date_to = st.date_input(
        "Hasta",
        value=opts["date_max"],
        min_value=opts["date_min"],
        max_value=opts["date_max"],
    )

    selected_statuses = st.multiselect(
        "Estado",
        options=opts["statuses"],
        default=[],
        placeholder="Todos",
    )
    selected_provinces = st.multiselect(
        "Provincia",
        options=opts["provinces"],
        default=[],
        placeholder="Todas",
    )
    selected_products = st.multiselect(
        "Producto",
        options=opts["products"],
        default=[],
        placeholder="Todos",
    )

    st.divider()

    page_size = st.selectbox("Filas por página", [50, 100, 200, 500], index=1)

    st.divider()
    if st.button("← Dashboard", use_container_width=True):
        st.switch_page("pages/1_Dashboard.py")
    if st.button("← Inicio", use_container_width=True):
        st.switch_page("app.py")

# ── Construir filtros ─────────────────────────────────────────────────────────

filters: dict = {}
if date_from:
    filters["date_from"] = date_from
if date_to:
    filters["date_to"] = date_to
if selected_products:
    filters["product"] = selected_products
if selected_statuses:
    filters["status"] = selected_statuses
if selected_provinces:
    filters["province"] = selected_provinces

# ── Header ────────────────────────────────────────────────────────────────────

st.markdown("## 🗂️ Explorador de ventas")
st.divider()

total = get_total_rows(conn, filters)

# ── Paginación ────────────────────────────────────────────────────────────────

total_pages = max(1, (total + page_size - 1) // page_size)

col_info, col_page, col_dl = st.columns([3, 2, 2])

with col_info:
    st.caption(f"**{total:,}** ventas encontradas · {total_pages} página{'s' if total_pages > 1 else ''}")

with col_page:
    current_page = st.number_input(
        "Página",
        min_value=1,
        max_value=total_pages,
        value=1,
        step=1,
        label_visibility="collapsed",
    )

offset = (current_page - 1) * page_size

# ── Datos ─────────────────────────────────────────────────────────────────────

df = get_sales_table(conn, filters, limit=page_size, offset=offset)

# Formateo para visualización
display_df = df.copy()
display_df.columns = [
    "ID venta", "Fecha", "Estado", "Producto", "SKU",
    "Unid.", "Precio unit.", "Ingreso prod.", "Comisión",
    "Costo envío", "Impuestos", "Total neto",
    "Comprador", "Ciudad", "Provincia",
    "Entrega", "Reclamo",
]

# Formatear columnas monetarias
money_cols = ["Precio unit.", "Ingreso prod.", "Comisión", "Costo envío", "Impuestos", "Total neto"]
for col in money_cols:
    display_df[col] = display_df[col].apply(
        lambda x: f"${x:,.0f}" if pd.notna(x) and x != 0 else "—"
    )

st.dataframe(
    display_df,
    use_container_width=True,
    height=min(600, (len(display_df) + 1) * 35 + 60),
    column_config={
        "ID venta": st.column_config.TextColumn(width="medium"),
        "Fecha": st.column_config.DateColumn(width="small"),
        "Estado": st.column_config.TextColumn(width="medium"),
        "Producto": st.column_config.TextColumn(width="large"),
        "Reclamo": st.column_config.TextColumn(width="small"),
    },
    hide_index=True,
)

# ── Descarga CSV ──────────────────────────────────────────────────────────────

with col_dl:
    full_df = get_sales_table(conn, filters, limit=100_000, offset=0)
    csv_buffer = io.StringIO()
    full_df.to_csv(csv_buffer, index=False)
    st.download_button(
        label="⬇ Descargar CSV",
        data=csv_buffer.getvalue().encode("utf-8"),
        file_name="ventas_ml_sesion.csv",
        mime="text/csv",
        use_container_width=True,
    )
