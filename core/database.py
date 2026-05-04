"""
Gestión de la base de datos DuckDB en memoria para la sesión del usuario.

Cada sesión de Streamlit tiene su propia instancia DuckDB aislada.
Al cerrar el navegador o refrescar la página, los datos se pierden.
La carga es idempotente: cargar el mismo archivo dos veces no genera duplicados.
La carga es aditiva: cargar un archivo nuevo agrega solo las ventas nuevas.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import duckdb
import pandas as pd
import streamlit as st
from loguru import logger

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ventas (
    sale_id              BIGINT,
    sale_date            DATE,
    status               VARCHAR,
    status_description   VARCHAR,
    is_multi_pack        VARCHAR,
    belongs_to_kit       VARCHAR,
    quantity             INTEGER,
    product_revenue      DOUBLE,
    sale_fee             DOUBLE,
    fixed_cost           DOUBLE,
    installments_cost    DOUBLE,
    shipping_revenue     DOUBLE,
    shipping_cost        DOUBLE,
    shipping_weight_cost DOUBLE,
    shipping_size_diff   DOUBLE,
    taxes                DOUBLE,
    discounts            DOUBLE,
    refunds              DOUBLE,
    total_amount         DOUBLE,
    billing_month        DATE,
    is_advertising       VARCHAR,
    sku                  VARCHAR,
    publication_id       VARCHAR,
    sales_channel        VARCHAR,
    product_title        VARCHAR,
    variant              VARCHAR,
    unit_price           DOUBLE,
    has_installments     VARCHAR,
    invoice_status       VARCHAR,
    buyer_legal_name     VARCHAR,
    buyer_document       VARCHAR,
    billing_address      VARCHAR,
    vat_condition        VARCHAR,
    buyer_name           VARCHAR,
    buyer_dni            VARCHAR,
    buyer_address        VARCHAR,
    buyer_city           VARCHAR,
    buyer_province       VARCHAR,
    buyer_zip            VARCHAR,
    buyer_country        VARCHAR,
    delivery_type        VARCHAR,
    shipped_at           DATE,
    delivered_at         DATE,
    carrier              VARCHAR,
    tracking_number      VARCHAR,
    tracking_url         VARCHAR,
    return_quantity      INTEGER,
    return_delivery_type VARCHAR,
    return_shipped_at    DATE,
    return_delivered_at  DATE,
    return_carrier       VARCHAR,
    return_tracking_number VARCHAR,
    return_tracking_url  VARCHAR,
    return_reviewed_by_ml VARCHAR,
    return_reviewed_at   DATE,
    return_credit        DOUBLE,
    return_result        VARCHAR,
    return_destination   VARCHAR,
    return_reason        VARCHAR,
    claim_quantity       INTEGER,
    claim_open           VARCHAR,
    claim_closed         VARCHAR,
    has_mediation        VARCHAR,
    _file_name           VARCHAR,
    _file_hash           VARCHAR,
    _loaded_at           TIMESTAMP
)
"""

_LOADS_SQL = """
CREATE TABLE IF NOT EXISTS cargas (
    file_name   VARCHAR,
    file_hash   VARCHAR,
    rows_in_file    INTEGER,
    rows_new        INTEGER,
    rows_duplicate  INTEGER,
    loaded_at   TIMESTAMP
)
"""


def _file_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def get_db() -> duckdb.DuckDBPyConnection:
    """Devuelve la conexión DuckDB de la sesión actual, creándola si no existe."""
    if "db" not in st.session_state:
        logger.info("Iniciando nueva base de datos en memoria para esta sesión")
        conn = duckdb.connect()
        conn.execute(_SCHEMA_SQL)
        conn.execute(_LOADS_SQL)
        st.session_state["db"] = conn
    return st.session_state["db"]


def load_dataframe(
    conn: duckdb.DuckDBPyConnection,
    df: pd.DataFrame,
    file_name: str,
    file_bytes: bytes,
) -> dict:
    """
    Carga un DataFrame en la tabla ventas de forma idempotente y aditiva.

    - Idempotente: mismo archivo (por sale_id) no genera duplicados.
    - Aditiva: archivo nuevo con ventas distintas se agrega.

    Returns:
        dict con claves: rows_in_file, rows_new, rows_duplicate
    """
    hash_val = _file_hash(file_bytes)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    rows_in_file = len(df)
    if rows_in_file == 0:
        return {"rows_in_file": 0, "rows_new": 0, "rows_duplicate": 0}

    # IDs existentes en la sesión
    existing_ids = set(
        conn.execute("SELECT sale_id FROM ventas").df()["sale_id"].tolist()
    )

    # Filtrar nuevas ventas
    new_df = df[~df["sale_id"].isin(existing_ids)].copy()
    rows_new = len(new_df)
    rows_duplicate = rows_in_file - rows_new

    if rows_new > 0:
        # Agregar columnas de auditoría
        new_df["_file_name"] = file_name
        new_df["_file_hash"] = hash_val
        new_df["_loaded_at"] = now

        # Alinear columnas con el schema (ignorar extras, rellenar faltantes con None)
        schema_cols = [
            row[0]
            for row in conn.execute("DESCRIBE ventas").fetchall()
        ]
        for col in schema_cols:
            if col not in new_df.columns:
                new_df[col] = None
        new_df = new_df[schema_cols]

        conn.register("_staging", new_df)
        conn.execute("INSERT INTO ventas SELECT * FROM _staging")
        conn.unregister("_staging")

    conn.execute(
        "INSERT INTO cargas VALUES (?, ?, ?, ?, ?, ?)",
        [file_name, hash_val, rows_in_file, rows_new, rows_duplicate, now],
    )

    logger.info(
        f"Carga completada: {rows_in_file} en archivo, "
        f"{rows_new} nuevas, {rows_duplicate} duplicadas"
    )

    return {
        "rows_in_file": rows_in_file,
        "rows_new": rows_new,
        "rows_duplicate": rows_duplicate,
    }


def get_session_summary(conn: duckdb.DuckDBPyConnection) -> dict:
    """Retorna un resumen rápido de los datos cargados en la sesión."""
    result = conn.execute("""
        SELECT
            COUNT(*)                                         AS total_rows,
            COUNT(DISTINCT sale_id)                          AS unique_sales,
            MIN(sale_date)                                   AS date_from,
            MAX(sale_date)                                   AS date_to,
            COUNT(DISTINCT _file_name)                       AS files_loaded
        FROM ventas
    """).fetchone()

    if result is None or result[0] == 0:
        return {"loaded": False}

    return {
        "loaded": True,
        "total_rows": result[0],
        "unique_sales": result[1],
        "date_from": result[2],
        "date_to": result[3],
        "files_loaded": result[4],
    }


def has_data(conn: duckdb.DuckDBPyConnection) -> bool:
    count = conn.execute("SELECT COUNT(*) FROM ventas").fetchone()[0]
    return count > 0
