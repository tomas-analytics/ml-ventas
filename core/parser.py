"""
Parser para archivos de ventas exportados desde MercadoLibre.

El Excel de ML tiene esta estructura fija:
  Filas 0-3: texto informativo (se ignora)
  Fila 4:    categorías de columna (sparse, se usa para desambiguar duplicados)
  Fila 5:    nombres de columna reales
  Fila 6+:   datos
"""

from __future__ import annotations

import re
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Union

import pandas as pd
from loguru import logger

# ── Meses en español ──────────────────────────────────────────────────────────

_MONTHS_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}

# ── Mapeo columna Excel → nombre interno ──────────────────────────────────────
# Las columnas duplicadas se desambiguan añadiendo " [2]", " [3]", etc.
# según el orden de aparición en el archivo.

COLUMN_MAP: dict[str, str] = {
    "# de venta":                                          "sale_id",
    "Fecha de venta":                                      "sale_date",
    "Estado":                                              "status",
    "Descripción del estado":                              "status_description",
    "Paquete de varios productos":                         "is_multi_pack",
    "Pertenece a un kit":                                  "belongs_to_kit",
    "Unidades":                                            "quantity",
    "Ingresos por productos (ARS)":                        "product_revenue",
    "Ingresos (ARS)":                                      "product_revenue",    # formato antiguo
    "Cargo por venta":                                     "sale_fee",
    "Cargo por venta e impuestos":                         "sale_fee",           # formato antiguo (combinado)
    "Costo fijo":                                          "fixed_cost",
    "Costo por ofrecer cuotas":                            "installments_cost",
    "Ingresos por envío (ARS)":                            "shipping_revenue",
    "Costos de envío (ARS)":                               "shipping_cost",
    "Costos de envío":                                     "shipping_cost",      # formato antiguo
    "Costo de envío basado en medidas y peso declarados":  "shipping_weight_cost",
    "Cargo por diferencias en medidas y peso del paquete": "shipping_size_diff",
    "Impuestos":                                           "taxes",
    "Descuentos y bonificaciones":                         "discounts",
    "Anulaciones y reembolsos (ARS)":                      "refunds",
    "Total (ARS)":                                         "total_amount",
    "Mes de facturación de tus cargos":                    "billing_month",
    "Venta por publicidad":                                "is_advertising",
    "SKU":                                                 "sku",
    "# de publicación":                                    "publication_id",
    "Canal de venta":                                      "sales_channel",
    "Título de la publicación":                            "product_title",
    "Variante":                                            "variant",
    "Precio unitario de venta de la publicación (ARS)":    "unit_price",
    "Tiene cuotas agregadas":                              "has_installments",
    "Factura adjunta":                                     "invoice_status",
    "Facturación":                                         "invoice_status",     # formato antiguo
    "Datos personales o de empresa":                       "buyer_legal_name",
    "Tipo y número de documento":                          "buyer_document",
    "Dirección":                                           "billing_address",
    "Condición fiscal (IVA)":                              "vat_condition",
    "Comprador":                                           "buyer_name",
    "Nombre del comprador":                                "buyer_name",         # formato antiguo
    "DNI":                                                 "buyer_dni",
    "Domicilio":                                           "buyer_address",
    "Ciudad":                                              "buyer_city",
    "Estado [2]":                                          "buyer_province",
    "Código postal":                                       "buyer_zip",
    "País":                                                "buyer_country",
    "Forma de entrega":                                    "delivery_type",
    "Fecha en camino":                                     "shipped_at",
    "Fecha entregado":                                     "delivered_at",
    "Transportista":                                       "carrier",
    "Número de seguimiento":                               "tracking_number",
    "URL de seguimiento":                                  "tracking_url",
    "Unidades [2]":                                        "return_quantity",
    "Forma de entrega [2]":                                "return_delivery_type",
    "Fecha en camino [2]":                                 "return_shipped_at",
    "Fecha entregado [2]":                                 "return_delivered_at",
    "Transportista [2]":                                   "return_carrier",
    "Número de seguimiento [2]":                           "return_tracking_number",
    "URL de seguimiento [2]":                              "return_tracking_url",
    "Revisado por Mercado Libre":                          "return_reviewed_by_ml",
    "Fecha de revisión":                                   "return_reviewed_at",
    "Dinero a favor":                                      "return_credit",
    "Resultado":                                           "return_result",
    "Destino":                                             "return_destination",
    "Motivo del resultado":                                "return_reason",
    "Unidades [3]":                                        "claim_quantity",
    "Reclamo abierto":                                     "claim_open",
    "Reclamo cerrado":                                     "claim_closed",
    "Con mediación":                                       "has_mediation",
}

# Columnas que deben existir para considerar el archivo válido
REQUIRED_COLUMNS = {"sale_id", "sale_date", "status", "total_amount"}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _fix_text(value: object) -> object:
    """Intenta corregir texto con doble-encoding latin-1/utf-8."""
    if not isinstance(value, str):
        return value
    try:
        return value.encode("latin-1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return value


def _clean_text(value: object) -> str | None:
    """Limpia un valor de texto: fix encoding, strip, vacío→None.
    MercadoLibre usa ' ' (espacio) para indicar campos sin dato."""
    value = _fix_text(value)
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _parse_billing_month(value: object) -> date | None:
    """Parsea el mes de facturación.
    Acepta 'abril 2026' (export real ML) o formatos estándar (datos sintéticos)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = str(value).strip().lower()
    if not s:
        return None
    m = re.match(r"(\w+)\s+(\d{4})", s)
    if m:
        month_name, year = m.group(1), int(m.group(2))
        month = _MONTHS_ES.get(month_name)
        if month:
            try:
                return date(year, month, 1)
            except ValueError:
                pass
    parsed = pd.to_datetime(value, errors="coerce")
    return parsed.date() if pd.notna(parsed) else None


def _parse_event_date(value: object, reference_year: int | None = None) -> date | None:
    """Parsea fechas de eventos del export de ML.

    Formatos soportados:
    - "22 de abril de 2026 01:48 hs." (full)
    - "22 de abril | 01:48"           (sin año, se infiere de reference_year)
    - "22 de abril"                   (sin año ni hora)
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (date, pd.Timestamp)):
        return value.date() if hasattr(value, "date") else value
    s = str(value).strip()
    if not s:
        return None
    s_lower = s.lower()
    # Formato completo con año
    m = re.match(r"(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})", s_lower)
    if m:
        day, month_name, year = int(m.group(1)), m.group(2), int(m.group(3))
        month = _MONTHS_ES.get(month_name)
        if month:
            try:
                return date(year, month, day)
            except ValueError:
                pass
    # Formato corto sin año: "22 de abril | 01:48" o "22 de abril"
    m = re.match(r"(\d{1,2})\s+de\s+(\w+)", s_lower)
    if m:
        day, month_name = int(m.group(1)), m.group(2)
        month = _MONTHS_ES.get(month_name)
        year = reference_year or date.today().year
        if month:
            try:
                return date(year, month, day)
            except ValueError:
                pass
    return None


def _parse_spanish_date(value: object) -> date | None:
    """Convierte '21 de mayo de 2026 00:00 hs.' en un objeto date."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (date, pd.Timestamp)):
        return value.date() if hasattr(value, "date") else value
    s = str(value).lower().strip()
    m = re.match(r"(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})", s)
    if m:
        day, month_name, year = int(m.group(1)), m.group(2), int(m.group(3))
        month = _MONTHS_ES.get(month_name)
        if month:
            try:
                return date(year, month, day)
            except ValueError:
                pass
    return None


def _make_unique_columns(columns: list[str]) -> list[str]:
    """
    Convierte una lista con posibles duplicados en nombres únicos.
    La primera ocurrencia conserva el nombre; las siguientes reciben ' [2]', ' [3]', etc.
    """
    seen: dict[str, int] = {}
    result: list[str] = []
    for col in columns:
        if col in seen:
            seen[col] += 1
            result.append(f"{col} [{seen[col]}]")
        else:
            seen[col] = 1
            result.append(col)
    return result


def _find_header_row(raw: pd.DataFrame) -> int:
    """
    Busca la fila que contiene '# de venta'.
    Lanza ValueError si no la encuentra en las primeras 15 filas.
    """
    for idx in range(min(15, len(raw))):
        row_values = [str(v).strip() for v in raw.iloc[idx].tolist() if pd.notna(v)]
        if "# de venta" in row_values:
            return idx
    raise ValueError(
        "No se encontró la columna '# de venta' en las primeras 15 filas. "
        "Verificá que el archivo sea un reporte de ventas de MercadoLibre."
    )

# ── Parser principal ──────────────────────────────────────────────────────────

def parse_excel(source: Union[str, Path, BytesIO]) -> pd.DataFrame:
    """
    Lee un archivo Excel de MercadoLibre y devuelve un DataFrame limpio
    con columnas normalizadas y tipos correctos.

    Args:
        source: ruta al archivo o BytesIO desde st.file_uploader

    Returns:
        DataFrame con columnas internas (sale_id, sale_date, status, ...)
    """
    logger.info("Leyendo archivo Excel...")
    raw = pd.read_excel(source, header=None, dtype=str)

    header_idx = _find_header_row(raw)
    logger.info(f"Fila de encabezado detectada en índice {header_idx}")

    # Construir nombres únicos a partir de la fila de encabezado
    header_row = [str(v).strip() if pd.notna(v) else "" for v in raw.iloc[header_idx].tolist()]
    unique_headers = _make_unique_columns(header_row)

    # Datos: todo lo que viene después del encabezado
    data = raw.iloc[header_idx + 1 :].copy()
    data.columns = unique_headers
    data = data.reset_index(drop=True)

    # Renombrar a nombres internos
    rename_map = {src: dst for src, dst in COLUMN_MAP.items() if src in data.columns}
    data = data.rename(columns=rename_map)

    # Eliminar columnas no mapeadas (ruido del archivo)
    known_internal = set(COLUMN_MAP.values())
    cols_to_keep = [c for c in data.columns if c in known_internal]
    data = data[cols_to_keep]

    # Eliminar filas completamente vacías
    data = data.dropna(how="all")

    # Verificar columnas requeridas
    missing = REQUIRED_COLUMNS - set(data.columns)
    if missing:
        raise ValueError(f"Columnas requeridas no encontradas: {missing}")

    logger.info(f"Filas crudas tras leer encabezado: {len(data)}")

    # ── Conversiones de tipo ──────────────────────────────────────────────────

    # sale_id: puede venir como float-string "3000000000000000.0"
    data["sale_id"] = (
        pd.to_numeric(data["sale_id"], errors="coerce")
        .dropna()
        .astype("int64")
    )
    # Fila que pierde sale_id es inválida
    data = data.dropna(subset=["sale_id"])
    data["sale_id"] = data["sale_id"].astype("int64")

    # Fechas
    data["sale_date"] = data["sale_date"].apply(_parse_spanish_date)

    if "billing_month" in data.columns:
        data["billing_month"] = data["billing_month"].apply(_parse_billing_month)

    # Columnas numéricas
    numeric_cols = [
        "quantity", "product_revenue", "sale_fee", "fixed_cost", "installments_cost",
        "shipping_revenue", "shipping_cost", "shipping_weight_cost", "shipping_size_diff",
        "taxes", "discounts", "refunds", "total_amount", "unit_price",
        "return_quantity", "return_credit", "claim_quantity",
    ]
    for col in numeric_cols:
        if col in data.columns:
            cleaned = (
                data[col]
                .astype(str)
                .str.replace(r"[$ ,]", "", regex=True)
                .str.replace(",", ".", regex=False)
            )
            data[col] = pd.to_numeric(cleaned, errors="coerce")

    # Fechas de eventos de envío/devolución
    # El export real de ML usa formato corto "22 de abril | 01:48" sin año
    event_date_cols = [
        "shipped_at", "delivered_at",
        "return_shipped_at", "return_delivered_at", "return_reviewed_at",
    ]
    ref_years = data["sale_date"].apply(
        lambda d: d.year if isinstance(d, date) else None
    )
    for col in event_date_cols:
        if col in data.columns:
            data[col] = [
                _parse_event_date(val, ref_year)
                for val, ref_year in zip(data[col], ref_years)
            ]

    # Texto: fix encoding + strip + vacío→None
    # MercadoLibre usa ' ' (espacio) como placeholder en celdas sin dato
    text_cols = [
        c for c in data.columns
        if c not in numeric_cols + ["sale_id", "sale_date", "billing_month"] + event_date_cols
    ]
    for col in text_cols:
        if col in data.columns:
            data[col] = data[col].apply(_clean_text)

    # Limpieza de filas sin fecha válida
    initial_count = len(data)
    data = data[data["sale_date"].notna()]
    dropped = initial_count - len(data)
    if dropped:
        logger.warning(f"Se descartaron {dropped} filas sin fecha válida")

    logger.info(f"Filas válidas tras parsear: {len(data)}")
    return data.reset_index(drop=True)
