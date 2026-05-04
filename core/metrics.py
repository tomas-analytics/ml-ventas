"""
Queries de métricas de negocio sobre la base DuckDB de la sesión.

Todas las funciones reciben una conexión DuckDB y los filtros activos,
y devuelven DataFrames o dicts listos para graficar o mostrar.
"""

from __future__ import annotations

import duckdb
import pandas as pd


# ── Filtros ───────────────────────────────────────────────────────────────────

def _where_clause(filters: dict) -> tuple[str, list]:
    """
    Construye el fragmento WHERE y la lista de parámetros según los filtros.

    Filtros soportados:
        date_from   (date)
        date_to     (date)
        status      (list[str])
        province    (list[str])
        product     (list[str])
    """
    conditions: list[str] = []
    params: list = []

    if filters.get("date_from"):
        conditions.append("sale_date >= ?")
        params.append(filters["date_from"])
    if filters.get("date_to"):
        conditions.append("sale_date <= ?")
        params.append(filters["date_to"])
    if filters.get("status"):
        placeholders = ", ".join("?" * len(filters["status"]))
        conditions.append(f"status IN ({placeholders})")
        params.extend(filters["status"])
    if filters.get("province"):
        placeholders = ", ".join("?" * len(filters["province"]))
        conditions.append(f"buyer_province IN ({placeholders})")
        params.extend(filters["province"])
    if filters.get("product"):
        placeholders = ", ".join("?" * len(filters["product"]))
        conditions.append(f"product_title IN ({placeholders})")
        params.extend(filters["product"])

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    return where, params


# ── KPIs ──────────────────────────────────────────────────────────────────────

def get_kpis(conn: duckdb.DuckDBPyConnection, filters: dict | None = None) -> dict:
    """
    Retorna las métricas principales de la sesión según los filtros activos.
    Solo considera ventas no canceladas para los cálculos financieros.
    """
    filters = filters or {}
    where, params = _where_clause(filters)

    # Agregamos condición de no canceladas para los montos
    financial_condition = (
        "status NOT IN ('Cancelado', 'Cancelada')"
    )
    full_where = (
        f"{where} AND {financial_condition}"
        if where
        else f"WHERE {financial_condition}"
    )

    row = conn.execute(f"""
        SELECT
            COUNT(*)                                          AS total_ventas,
            COALESCE(SUM(quantity), 0)                        AS total_unidades,
            COALESCE(SUM(product_revenue), 0)                 AS ingresos_brutos,
            COALESCE(SUM(total_amount), 0)                    AS ingresos_netos,
            COALESCE(SUM(ABS(COALESCE(sale_fee, 0))), 0)      AS comisiones_ml,
            COALESCE(SUM(ABS(COALESCE(taxes, 0))), 0)         AS impuestos,
            COALESCE(SUM(COALESCE(shipping_cost, 0)), 0)      AS costo_envio,
            COALESCE(AVG(total_amount), 0)                    AS ticket_promedio,
            COUNT(*) FILTER (WHERE status = 'Entregado')      AS ventas_entregadas,
            COUNT(*) FILTER (WHERE claim_open = 'Sí'
                             OR claim_open = 'Si')            AS ventas_con_reclamo
        FROM ventas
        {full_where}
    """, params).fetchone()

    total = conn.execute(f"SELECT COUNT(*) FROM ventas {where}", params).fetchone()[0]

    return {
        "total_ventas":       row[0],
        "total_unidades":     int(row[1] or 0),
        "ingresos_brutos":    float(row[2] or 0),
        "ingresos_netos":     float(row[3] or 0),
        "comisiones_ml":      float(row[4] or 0),
        "impuestos":          float(row[5] or 0),
        "costo_envio":        float(row[6] or 0),
        "ticket_promedio":    float(row[7] or 0),
        "ventas_entregadas":  int(row[8] or 0),
        "ventas_con_reclamo": int(row[9] or 0),
        "total_registros":    total,
        "tasa_comision":      (float(row[4] or 0) / float(row[2]) * 100) if row[2] else 0,
    }


# ── Revenue en el tiempo ──────────────────────────────────────────────────────

def get_revenue_over_time(
    conn: duckdb.DuckDBPyConnection,
    filters: dict | None = None,
    granularity: str = "day",
) -> pd.DataFrame:
    """
    Ingresos netos y brutos agrupados por período.
    granularity: 'day' | 'week' | 'month'
    """
    filters = filters or {}
    where, params = _where_clause(filters)

    trunc = {
        "day":   "CAST(sale_date AS DATE)",
        "week":  "DATE_TRUNC('week', sale_date)",
        "month": "DATE_TRUNC('month', sale_date)",
    }.get(granularity, "CAST(sale_date AS DATE)")

    return conn.execute(f"""
        SELECT
            {trunc}                              AS periodo,
            COALESCE(SUM(total_amount), 0)       AS ingresos_netos,
            COALESCE(SUM(product_revenue), 0)    AS ingresos_brutos,
            COUNT(*)                             AS cantidad_ventas,
            COALESCE(SUM(quantity), 0)           AS unidades
        FROM ventas
        {where}
        {'AND' if where else 'WHERE'} status NOT IN ('Cancelado', 'Cancelada')
        GROUP BY 1
        ORDER BY 1
    """, params).df()


# ── Ventas por estado ─────────────────────────────────────────────────────────

def get_sales_by_status(
    conn: duckdb.DuckDBPyConnection,
    filters: dict | None = None,
) -> pd.DataFrame:
    filters = filters or {}
    where, params = _where_clause(filters)
    return conn.execute(f"""
        SELECT
            COALESCE(status, 'Sin estado')   AS estado,
            COUNT(*)                         AS cantidad,
            COALESCE(SUM(total_amount), 0)   AS monto_total
        FROM ventas
        {where}
        GROUP BY 1
        ORDER BY 2 DESC
    """, params).df()


# ── Top productos ─────────────────────────────────────────────────────────────

def get_top_products(
    conn: duckdb.DuckDBPyConnection,
    filters: dict | None = None,
    by: str = "revenue",
    limit: int = 10,
) -> pd.DataFrame:
    """by: 'revenue' | 'units' | 'count'"""
    filters = filters or {}
    where, params = _where_clause(filters)

    order_col = {
        "revenue": "ingresos_netos DESC",
        "units":   "unidades DESC",
        "count":   "cantidad DESC",
    }.get(by, "ingresos_netos DESC")

    return conn.execute(f"""
        SELECT
            COALESCE(product_title, sku, 'Sin título') AS producto,
            COUNT(*)                                    AS cantidad,
            COALESCE(SUM(quantity), 0)                  AS unidades,
            COALESCE(SUM(total_amount), 0)              AS ingresos_netos,
            COALESCE(SUM(product_revenue), 0)           AS ingresos_brutos,
            COALESCE(AVG(unit_price), 0)                AS precio_promedio
        FROM ventas
        {where}
        {'AND' if where else 'WHERE'} status NOT IN ('Cancelado', 'Cancelada')
        GROUP BY 1
        ORDER BY {order_col}
        LIMIT {limit}
    """, params).df()


# ── Por provincia ─────────────────────────────────────────────────────────────

def get_sales_by_province(
    conn: duckdb.DuckDBPyConnection,
    filters: dict | None = None,
) -> pd.DataFrame:
    filters = filters or {}
    where, params = _where_clause(filters)
    return conn.execute(f"""
        SELECT
            COALESCE(buyer_province, 'Sin datos') AS provincia,
            COUNT(*)                              AS cantidad,
            COALESCE(SUM(total_amount), 0)        AS ingresos_netos,
            COALESCE(SUM(quantity), 0)            AS unidades
        FROM ventas
        {where}
        {'AND' if where else 'WHERE'} status NOT IN ('Cancelado', 'Cancelada')
        GROUP BY 1
        ORDER BY 2 DESC
    """, params).df()


# ── Desglose de costos ────────────────────────────────────────────────────────

def get_cost_breakdown(
    conn: duckdb.DuckDBPyConnection,
    filters: dict | None = None,
) -> pd.DataFrame:
    """Retorna un DataFrame con una fila por componente de costo."""
    filters = filters or {}
    where, params = _where_clause(filters)

    row = conn.execute(f"""
        SELECT
            COALESCE(SUM(product_revenue), 0)                                AS ingresos_brutos,
            COALESCE(SUM(ABS(COALESCE(sale_fee, 0))), 0)                     AS comision_ml,
            COALESCE(SUM(ABS(COALESCE(taxes, 0))), 0)                        AS impuestos,
            COALESCE(SUM(ABS(COALESCE(shipping_cost, 0))), 0)                AS costo_envio,
            COALESCE(SUM(ABS(COALESCE(discounts, 0))), 0)                    AS descuentos,
            COALESCE(SUM(ABS(COALESCE(refunds, 0))), 0)                      AS reembolsos,
            COALESCE(SUM(total_amount), 0)                                   AS ingreso_neto
        FROM ventas
        {where}
        {'AND' if where else 'WHERE'} status NOT IN ('Cancelado', 'Cancelada')
    """, params).fetchone()

    labels = [
        "Comisión ML", "Impuestos", "Costo envío",
        "Descuentos", "Reembolsos",
    ]
    values = [row[1], row[2], row[3], row[4], row[5]]

    return pd.DataFrame({
        "componente": ["Ingresos brutos"] + labels + ["Ingreso neto"],
        "valor": [row[0]] + values + [row[6]],
        "tipo": ["ingreso"] + ["costo"] * len(labels) + ["neto"],
    })


# ── Filtros disponibles ───────────────────────────────────────────────────────

def get_filter_options(conn: duckdb.DuckDBPyConnection) -> dict:
    """Retorna los valores únicos disponibles para construir los widgets de filtro."""
    statuses = conn.execute(
        "SELECT DISTINCT status FROM ventas WHERE status IS NOT NULL ORDER BY 1"
    ).df()["status"].tolist()

    provinces = conn.execute(
        "SELECT DISTINCT buyer_province FROM ventas WHERE buyer_province IS NOT NULL ORDER BY 1"
    ).df()["buyer_province"].tolist()

    products = conn.execute(
        "SELECT DISTINCT product_title FROM ventas WHERE product_title IS NOT NULL ORDER BY 1"
    ).df()["product_title"].tolist()

    date_range = conn.execute(
        "SELECT MIN(sale_date), MAX(sale_date) FROM ventas"
    ).fetchone()

    return {
        "statuses":  statuses,
        "provinces": provinces,
        "products":  products,
        "date_min":  date_range[0],
        "date_max":  date_range[1],
    }


# ── Tabla de datos ────────────────────────────────────────────────────────────

def get_sales_table(
    conn: duckdb.DuckDBPyConnection,
    filters: dict | None = None,
    limit: int = 500,
    offset: int = 0,
) -> pd.DataFrame:
    filters = filters or {}
    where, params = _where_clause(filters)
    return conn.execute(f"""
        SELECT
            sale_id, sale_date, status, product_title, sku,
            quantity, unit_price, product_revenue, sale_fee,
            shipping_cost, taxes, total_amount,
            buyer_name, buyer_city, buyer_province,
            delivery_type, claim_open
        FROM ventas
        {where}
        ORDER BY sale_date DESC, sale_id DESC
        LIMIT {limit} OFFSET {offset}
    """, params).df()


def get_total_rows(
    conn: duckdb.DuckDBPyConnection,
    filters: dict | None = None,
) -> int:
    filters = filters or {}
    where, params = _where_clause(filters)
    return conn.execute(f"SELECT COUNT(*) FROM ventas {where}", params).fetchone()[0]
