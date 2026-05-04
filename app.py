"""
Página de inicio: carga de archivos y resumen de sesión.
Entry point: streamlit run app.py
"""

import streamlit as st

from core.database import get_db, get_session_summary, has_data, load_dataframe
from core.parser import parse_excel

st.set_page_config(
    page_title="ML Ventas",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── CSS ───────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
  /* Ocultar header de Streamlit */
  header[data-testid="stHeader"] { display: none; }

  /* Upload zone */
  [data-testid="stFileUploadDropzone"] {
    border: 2px dashed #FFE600 !important;
    border-radius: 12px !important;
    background: #161b22 !important;
    padding: 2rem !important;
  }

  /* Metric cards */
  [data-testid="metric-container"] {
    background: #161b22;
    border: 1px solid #21262d;
    border-radius: 10px;
    padding: 1rem 1.2rem;
  }
  [data-testid="metric-container"] label { color: #8b949e !important; font-size: 0.78rem !important; }
  [data-testid="metric-container"] [data-testid="stMetricValue"] { font-size: 1.5rem !important; }

  /* Botones primarios */
  .stButton > button[kind="primary"] {
    background: #FFE600;
    color: #0d1117;
    font-weight: 700;
    border: none;
    border-radius: 8px;
    padding: 0.6rem 2rem;
  }
  .stButton > button[kind="primary"]:hover { background: #e6cf00; }

  /* Alertas */
  .success-box {
    background: #0f2d1f;
    border: 1px solid #00A650;
    border-radius: 8px;
    padding: 1rem 1.2rem;
    margin: 0.5rem 0;
  }
  .info-box {
    background: #0d1b2e;
    border: 1px solid #3483FA;
    border-radius: 8px;
    padding: 1rem 1.2rem;
    margin: 0.5rem 0;
  }

  /* Separador */
  hr { border-color: #21262d !important; }
</style>
""", unsafe_allow_html=True)

# ── Session DB ────────────────────────────────────────────────────────────────

conn = get_db()

# ── Header ────────────────────────────────────────────────────────────────────

col_logo, col_title = st.columns([1, 8])
with col_logo:
    st.markdown("## 📊")
with col_title:
    st.markdown("## ML Ventas")
    st.caption("Analizá tus ventas de MercadoLibre al instante")

st.divider()

# ── Estado de la sesión ───────────────────────────────────────────────────────

summary = get_session_summary(conn)

if summary["loaded"]:
    st.markdown('<div class="info-box">', unsafe_allow_html=True)
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Ventas en sesión", f"{summary['unique_sales']:,}")
    col2.metric("Archivos cargados", summary["files_loaded"])
    col3.metric("Desde", str(summary["date_from"]) if summary["date_from"] else "—")
    col4.metric("Hasta", str(summary["date_to"]) if summary["date_to"] else "—")
    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("")

# ── Upload ────────────────────────────────────────────────────────────────────

if not summary["loaded"]:
    st.markdown("### Cargá tu reporte de ventas")
    st.markdown(
        "Descargá el reporte desde **MercadoLibre → Mis ventas → Exportar** "
        "y subilo acá. Los datos quedan solo en esta sesión: al cerrar el navegador se borran."
    )
    st.markdown("")
else:
    st.markdown("### Cargar otro archivo")
    st.markdown(
        "Podés sumar más ventas. Las que ya existen en la sesión no se duplican."
    )
    st.markdown("")

uploaded_file = st.file_uploader(
    "Arrastrá tu archivo Excel acá o hacé clic para seleccionarlo",
    type=["xlsx", "xls"],
    label_visibility="collapsed",
)

if uploaded_file is not None:
    file_bytes = uploaded_file.read()
    uploaded_file.seek(0)

    with st.spinner("Procesando archivo..."):
        try:
            df = parse_excel(uploaded_file)
            result = load_dataframe(conn, df, uploaded_file.name, file_bytes)

            st.markdown('<div class="success-box">', unsafe_allow_html=True)
            st.markdown(f"**✓ {uploaded_file.name}** procesado correctamente")

            c1, c2, c3 = st.columns(3)
            c1.metric("Filas en el archivo", f"{result['rows_in_file']:,}")
            c2.metric("Ventas nuevas agregadas", f"{result['rows_new']:,}")
            c3.metric("Ya existían (ignoradas)", f"{result['rows_duplicate']:,}")
            st.markdown("</div>", unsafe_allow_html=True)

            st.session_state["last_upload_ok"] = True

        except ValueError as e:
            st.error(f"Error al procesar el archivo: {e}")
        except Exception as e:
            st.error(f"Error inesperado: {e}")

# ── Navegación ────────────────────────────────────────────────────────────────

st.markdown("")

if has_data(conn):
    col_btn, _ = st.columns([2, 5])
    with col_btn:
        if st.button("Ver dashboard →", type="primary", use_container_width=True):
            st.switch_page("pages/1_Dashboard.py")

# ── Footer ────────────────────────────────────────────────────────────────────

st.markdown("")
st.divider()
st.caption(
    "Los datos cargados son exclusivos de esta sesión y no se almacenan en ningún servidor. "
    "Al cerrar o refrescar la página, todo se borra automáticamente."
)
