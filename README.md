# ML Ventas

Dashboard para analizar ventas de MercadoLibre. Subís tu reporte Excel y en segundos ves todas tus métricas.

## Cómo correrlo

```bash
# 1. Crear entorno virtual (solo la primera vez)
python3 -m venv .venv

# 2. Activar el entorno
source .venv/bin/activate        # Linux/Mac
.venv\Scripts\activate           # Windows

# 3. Instalar dependencias (solo la primera vez)
pip install -r requirements.txt

# 4. Correr la app
streamlit run app.py
```

La app queda disponible en `http://localhost:8501`.

## Cómo usarlo

1. Descargá el reporte de ventas desde **MercadoLibre → Mis ventas → Exportar** (formato Excel)
2. Entrá a la app y subí el archivo
3. Navegá al Dashboard para ver tus métricas

Podés cargar múltiples archivos: las ventas se acumulan sin duplicar.  
Al cerrar el navegador, los datos de la sesión se borran automáticamente.

## Estructura

```
ml-ventas/
├── app.py                  # Página de inicio / upload
├── pages/
│   ├── 1_Dashboard.py      # Dashboard principal
│   └── 2_Datos.py          # Explorador de datos + descarga CSV
├── core/
│   ├── parser.py           # Lectura y normalización del Excel de ML
│   ├── database.py         # Gestión de sesión DuckDB en memoria
│   └── metrics.py          # Queries SQL de métricas de negocio
├── components/
│   └── charts.py           # Gráficos Plotly
└── requirements.txt
```

## Métricas disponibles

- Ingresos brutos y netos (ARS)
- Comisión ML y tasa efectiva
- Costo de envíos e impuestos
- Ticket promedio y unidades vendidas
- Evolución temporal (día / semana / mes)
- Distribución por estado de venta
- Top productos por ingresos y por unidades
- Ventas por provincia
- Waterfall de desglose bruto → neto
- Ventas por día de la semana
