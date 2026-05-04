# Cómo funciona ML Ventas — Documento técnico

## Qué es este proyecto

ML Ventas es una aplicación web que te permite analizar tus ventas de MercadoLibre sin instalar nada especial ni subir tus datos a ningún servidor externo. Subís el archivo Excel que descargás desde MercadoLibre, y al instante tenés un dashboard con métricas, gráficos y la posibilidad de exportar los datos filtrados.

Todo ocurre en la memoria de tu navegador: al cerrar la pestaña, los datos desaparecen. No hay base de datos permanente ni backend propio.

---

## Arquitectura general

```
Usuario
  │
  │  sube archivo .xlsx
  ▼
┌─────────────────────────────────────────────┐
│  Streamlit  (framework de la interfaz web)  │
│                                             │
│  app.py          ← página de inicio/upload  │
│  pages/1_Dashboard.py  ← gráficos y KPIs   │
│  pages/2_Datos.py      ← tabla + CSV        │
└──────────┬──────────────────────────────────┘
           │ llama a
           ▼
┌─────────────────────────────────────────────┐
│  core/  (lógica de negocio)                 │
│                                             │
│  parser.py    ← lee y limpia el Excel       │
│  database.py  ← guarda datos en DuckDB      │
│  metrics.py   ← consultas SQL de métricas  │
└──────────┬──────────────────────────────────┘
           │ datos para graficar
           ▼
┌─────────────────────────────────────────────┐
│  components/charts.py                       │
│  (gráficos Plotly listos para mostrar)      │
└─────────────────────────────────────────────┘
```

### Tecnologías clave

| Tecnología | Para qué se usa |
|---|---|
| **Streamlit** | Framework que convierte código Python en una app web sin escribir HTML ni JavaScript |
| **DuckDB** | Base de datos SQL que vive completamente en memoria RAM, dentro de la sesión del usuario |
| **Pandas** | Manipulación de datos tabulares (DataFrames) |
| **Plotly** | Gráficos interactivos |
| **OpenPyXL** | Lectura de archivos Excel `.xlsx` |

---

## Estructura de archivos

```
ml-ventas/
├── app.py                    # Entrada: página de inicio y carga de archivos
├── pages/
│   ├── 1_Dashboard.py        # Dashboard con KPIs y gráficos
│   └── 2_Datos.py            # Tabla de ventas con filtros y descarga CSV
├── core/
│   ├── parser.py             # Leer, limpiar y normalizar el Excel de ML
│   ├── database.py           # Crear y manejar la base DuckDB en sesión
│   └── metrics.py            # Todas las consultas SQL de métricas
├── components/
│   └── charts.py             # Funciones que construyen gráficos Plotly
├── .streamlit/
│   └── config.toml           # Configuración visual y del servidor
└── requirements.txt          # Dependencias Python
```

---

## Flujo completo de un archivo desde que se sube hasta que se ve en el dashboard

```
1. Usuario arrastra el .xlsx en app.py
        │
        ▼
2. parse_excel()  [core/parser.py]
   Lee el Excel fila por fila, detecta dónde empieza la tabla real,
   renombra columnas al estándar interno, parsea fechas y números.
        │
        ▼
3. load_dataframe()  [core/database.py]
   Compara los sale_id nuevos contra los ya cargados.
   Inserta solo las ventas que no existían → sin duplicados.
        │
        ▼
4. DuckDB en memoria  (tabla "ventas")
   Todos los datos disponibles en SQL para el resto de la sesión.
        │
        ▼
5. get_kpis() / get_revenue_over_time() / etc.  [core/metrics.py]
   Consultas SQL que calculan métricas según los filtros activos.
        │
        ▼
6. revenue_over_time() / top_products() / etc.  [components/charts.py]
   Funciones que convierten DataFrames en gráficos Plotly interactivos.
        │
        ▼
7. st.plotly_chart() / st.metric()  [pages/1_Dashboard.py]
   Streamlit renderiza todo como HTML en el navegador.
```

---

## Descripción detallada de cada archivo

---

### `app.py` — Página de inicio y carga de archivos

Es el punto de entrada de la app. Streamlit lo ejecuta con `streamlit run app.py`.

**Qué hace:**
- Muestra una zona para arrastrar o seleccionar el archivo `.xlsx`
- Llama a `parse_excel()` para procesar el archivo
- Llama a `load_dataframe()` para guardarlo en DuckDB
- Si ya hay datos cargados, muestra un resumen rápido (total de ventas, fechas, archivos cargados)
- Si el procesamiento falla, muestra el mensaje de error al usuario

**Comportamiento de sesión:**
Cada vez que un usuario abre la app, Streamlit crea una sesión nueva. La conexión DuckDB se guarda en `st.session_state["db"]`, que es un diccionario propio de cada sesión. Si el usuario abre otra pestaña, tiene su propia sesión separada. Al cerrar o refrescar, todo se pierde.

**Manejo de errores:**
```python
try:
    df = parse_excel(uploaded_file)
    result = load_dataframe(conn, df, ...)
except ValueError as e:
    st.error(f"Error al procesar el archivo: {e}")   # error esperado (archivo inválido)
except Exception as e:
    st.error(f"Error inesperado: {e}")               # error técnico
```
Los `ValueError` son errores "de negocio" que el parser lanza a propósito cuando el archivo no tiene el formato esperado. El bloque `Exception` captura cualquier error técnico inesperado.

---

### `core/parser.py` — El corazón del proyecto

Es el módulo más importante. Se encarga de convertir el Excel crudo de MercadoLibre en un DataFrame limpio y estructurado que el resto del sistema puede usar.

#### El problema que resuelve

El Excel de MercadoLibre no es un archivo simple. Tiene esta estructura:

```
Fila 0:  vacía
Fila 1:  "En este reporte encontrarás la información de tus ventas..."
Fila 2:  "Ir a Facturas y reportes..."
Fila 3:  (a veces) mensaje de error de ML
Fila 4:  "Ventas  Estado de tus ventas al 22 de abril..."
Fila 5:  "Ventas"  "Publicidad"  "Publicaciones"  "Compradores"  ... (categorías)
Fila 6:  "# de venta"  "Fecha de venta"  "Estado"  ...  (encabezados reales)
Fila 7+: datos
```

Dependiendo de cuándo se descargó, la fila del encabezado puede estar en distintas posiciones (fila 5 o fila 6). Además, muchas columnas tienen el mismo nombre ("Unidades", "Estado", "Transportista") porque aparecen tanto en la sección de ventas como en la de devoluciones.

#### Funciones del parser

**`_find_header_row(raw)`**
Recorre las primeras 15 filas buscando la celda que diga exactamente `"# de venta"`. Cuando la encuentra, esa es la fila de encabezado real. Devuelve el número de fila.

**`_make_unique_columns(columns)`**
Toma la lista de nombres de columna (con duplicados) y los hace únicos agregando sufijos `[2]`, `[3]`, etc. en orden de aparición:
```
"Estado", "Estado"  →  "Estado", "Estado [2]"
"Unidades", "Unidades", "Unidades"  →  "Unidades", "Unidades [2]", "Unidades [3]"
```
Esto es fundamental porque MercadoLibre reutiliza los mismos nombres para campos de envío y de devolución.

**`COLUMN_MAP`**
Es un diccionario que define el renombre de cada columna del Excel al nombre interno del proyecto. Por ejemplo:
```python
"# de venta"       → "sale_id"
"Fecha de venta"   → "sale_date"
"DNI"              → "buyer_dni"
"Estado [2]"       → "buyer_province"   # el segundo "Estado" es la provincia del comprador
"Unidades [2]"     → "return_quantity"  # el segundo "Unidades" es de devoluciones
```
Solo se conservan las columnas que están en este mapa. El resto se descarta.

**`_parse_spanish_date(value)`**
Convierte fechas en español como `"19 de abril de 2026 15:56 hs."` a un objeto `date` de Python. Usa un diccionario `_MONTHS_ES` que mapea nombres de meses en español a números.

**`_parse_billing_month(value)`**
Parsea el mes de facturación. El export real de ML lo trae como `"abril 2026"`, que `pd.to_datetime` no puede parsear directamente. Esta función extrae el mes y el año por separado usando `_MONTHS_ES` y devuelve el primer día de ese mes: `date(2026, 4, 1)`.

**`_parse_event_date(value, reference_year)`**
Parsea fechas de eventos de envío y devolución. El export real de ML usa un formato corto sin año: `"22 de abril | 01:48"`. Como no trae el año, la función lo infiere a partir de la fecha de venta (`reference_year`) de esa misma fila. Soporta también el formato completo con año.

**`_fix_text(value)`**
Intenta corregir texto con doble-encoding. Esto ocurre cuando el archivo fue guardado con codificación latin-1 pero leído como UTF-8 (o viceversa), produciendo caracteres extraños como `"PaÃ±uelo"` en lugar de `"Pañuelo"`. Intenta convertir el string y si falla, lo deja como está.

**`_clean_text(value)`**
Limpia un campo de texto: aplica `_fix_text`, hace strip de espacios, y convierte cadenas vacías o de solo espacios a `None`. Esto es necesario porque MercadoLibre usa `' '` (un espacio) como valor de "sin dato" en muchas celdas del Excel, en lugar de dejarlas vacías.

**`parse_excel(source)` — función principal**

Secuencia de pasos:
1. Lee el archivo completo sin header: `pd.read_excel(source, header=None, dtype=str)`. El `dtype=str` es importante: lee absolutamente todo como texto para evitar conversiones automáticas incorrectas de pandas.
2. Detecta la fila de encabezado con `_find_header_row`.
3. Toma la fila de encabezado y la convierte en nombres únicos con `_make_unique_columns`.
4. Usa esos nombres como columnas del DataFrame de datos.
5. Renombra con `COLUMN_MAP` y descarta columnas no mapeadas.
6. Elimina filas completamente vacías.
7. Verifica que existan las columnas requeridas mínimas (`sale_id`, `sale_date`, `status`, etc.).
8. Convierte tipos:
   - `sale_id` → entero de 64 bits (los IDs de ML son números muy grandes)
   - `sale_date` → `date` via `_parse_spanish_date`
   - `billing_month` → `date` via `_parse_billing_month`
   - Columnas numéricas → `float` via `pd.to_numeric` con limpieza de símbolos `$` y espacios
   - Fechas de eventos → `date` via `_parse_event_date` con año inferido
   - Columnas de texto → `_clean_text` (strip + vacío→None)
9. Descarta filas sin fecha de venta válida.
10. Devuelve el DataFrame limpio.

---

### `core/database.py` — La base de datos en sesión

Gestiona una base de datos DuckDB que vive completamente en memoria RAM durante la sesión del usuario.

#### Por qué DuckDB y no SQLite o una base normal

DuckDB está diseñado para análisis. Permite consultas SQL complejas con agregaciones sobre miles de filas en milisegundos, sin necesidad de un servidor. Al ser en memoria, no hay archivos temporales en disco y los datos desaparecen automáticamente al cerrar la sesión.

#### El esquema de la tabla `ventas`

```sql
CREATE TABLE IF NOT EXISTS ventas (
    sale_id              BIGINT,      -- ID de la venta (número grande, ej: 2000012585158951)
    sale_date            DATE,        -- Fecha de la venta
    status               VARCHAR,     -- "Entregado", "En camino", "Cancelado", etc.
    status_description   VARCHAR,     -- Descripción detallada del estado
    is_multi_pack        VARCHAR,     -- "Sí" / "No": si es paquete de varios productos
    belongs_to_kit       VARCHAR,     -- "Sí" / "No": si pertenece a un kit
    quantity             INTEGER,     -- Unidades vendidas
    product_revenue      DOUBLE,      -- Ingresos por producto (ARS)
    sale_fee             DOUBLE,      -- Comisión de MercadoLibre (valor negativo)
    fixed_cost           DOUBLE,      -- Costo fijo de la publicación
    installments_cost    DOUBLE,      -- Costo por ofrecer cuotas
    shipping_revenue     DOUBLE,      -- Lo que pagó el comprador por envío
    shipping_cost        DOUBLE,      -- Lo que cobró ML al vendedor por envío
    shipping_weight_cost DOUBLE,      -- Costo por peso/medidas declaradas
    shipping_size_diff   DOUBLE,      -- Cargo por diferencias de medidas reales vs declaradas
    taxes                DOUBLE,      -- Impuestos
    discounts            DOUBLE,      -- Descuentos y bonificaciones
    refunds              DOUBLE,      -- Anulaciones y reembolsos
    total_amount         DOUBLE,      -- Total neto de la venta (lo que el vendedor recibe)
    billing_month        DATE,        -- Mes en que ML factura los cargos
    is_advertising       VARCHAR,     -- "Sí" / "No": venta originada por publicidad
    sku                  VARCHAR,     -- Código de producto del vendedor
    publication_id       VARCHAR,     -- ID de la publicación en ML (ej: MLA861451808)
    sales_channel        VARCHAR,     -- "Mercado Libre" / "Mercado Shops"
    product_title        VARCHAR,     -- Título de la publicación
    variant              VARCHAR,     -- Variante (color, talle, etc.)
    unit_price           DOUBLE,      -- Precio unitario de lista
    has_installments     VARCHAR,     -- "Sí" / "No": si tiene cuotas agregadas
    invoice_status       VARCHAR,     -- "Factura adjunta" / "Factura no adjunta"
    buyer_legal_name     VARCHAR,     -- Nombre legal del comprador (persona o empresa)
    buyer_document       VARCHAR,     -- Tipo y número de documento (ej: "DNI: 24785717")
    billing_address      VARCHAR,     -- Dirección de facturación
    vat_condition        VARCHAR,     -- Condición fiscal: "Consumidor Final", "Responsable Inscripto", etc.
    buyer_name           VARCHAR,     -- Nombre del comprador
    buyer_dni            VARCHAR,     -- DNI del comprador (como texto, puede estar vacío)
    buyer_address        VARCHAR,     -- Domicilio de entrega
    buyer_city           VARCHAR,     -- Ciudad
    buyer_province       VARCHAR,     -- Provincia
    buyer_zip            VARCHAR,     -- Código postal
    buyer_country        VARCHAR,     -- País
    delivery_type        VARCHAR,     -- Tipo de entrega
    shipped_at           DATE,        -- Fecha en que salió al correo
    delivered_at         DATE,        -- Fecha en que fue entregado
    carrier              VARCHAR,     -- Transportista (Andreani, OCA, etc.)
    tracking_number      VARCHAR,     -- Número de seguimiento
    tracking_url         VARCHAR,     -- URL de seguimiento
    -- Devoluciones
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
    -- Reclamos
    claim_quantity       INTEGER,
    claim_open           VARCHAR,
    claim_closed         VARCHAR,
    has_mediation        VARCHAR,
    -- Auditoría interna
    _file_name           VARCHAR,     -- Nombre del archivo fuente
    _file_hash           VARCHAR,     -- Hash SHA-256 del archivo (primeros 16 caracteres)
    _loaded_at           TIMESTAMP    -- Timestamp de cuándo se cargó
)
```

También hay una tabla `cargas` que registra cada vez que se cargó un archivo (nombre, hash, cuántas filas nuevas, cuántas duplicadas).

#### `get_db()` — Gestión de la conexión

```python
def get_db() -> duckdb.DuckDBPyConnection:
    if "db" not in st.session_state:
        conn = duckdb.connect()   # conexión en memoria (sin archivo)
        conn.execute(_SCHEMA_SQL)  # crea la tabla ventas
        conn.execute(_LOADS_SQL)   # crea la tabla cargas
        st.session_state["db"] = conn
    return st.session_state["db"]
```

La primera vez que se llama, crea la conexión DuckDB y las tablas. Las siguientes veces, devuelve la misma conexión ya existente. Así todos los módulos de la app comparten la misma base de datos durante la sesión.

#### `load_dataframe()` — Carga idempotente y aditiva

Idempotente significa que cargar el mismo archivo dos veces no genera duplicados. Aditiva significa que cargar un archivo nuevo agrega solo las ventas que no existían.

Pasos:
1. Calcula un hash SHA-256 del contenido binario del archivo (primeros 16 caracteres). Esto identifica el archivo.
2. Consulta qué `sale_id` ya existen en la tabla.
3. Filtra el DataFrame nuevo para quedarse solo con los `sale_id` que no existen.
4. Agrega las columnas de auditoría (`_file_name`, `_file_hash`, `_loaded_at`).
5. Alinea las columnas con el esquema de la tabla: agrega columnas que faltan con `None`, reordena las que sobran.
6. Registra el DataFrame como tabla temporal `_staging` en DuckDB y hace el `INSERT`.
7. Registra la carga en la tabla `cargas`.
8. Devuelve un resumen: cuántas filas había en el archivo, cuántas eran nuevas, cuántas ya existían.

---

### `core/metrics.py` — Consultas SQL de métricas

Contiene todas las consultas que calculan los números que se muestran en el dashboard. Todas las funciones reciben la conexión DuckDB y un diccionario de filtros activos.

#### `_where_clause(filters)` — Constructor de WHERE dinámico

Recibe el diccionario de filtros del usuario y construye el fragmento SQL `WHERE` con parámetros preparados (nunca interpolación directa de strings, para evitar SQL injection):

```python
filters = {
    "date_from": date(2026, 1, 1),
    "date_to":   date(2026, 4, 30),
    "status":    ["Entregado", "En camino"],
    "province":  ["Buenos Aires"],
}
# Genera:
# WHERE sale_date >= ? AND sale_date <= ? AND status IN (?, ?) AND buyer_province IN (?)
# params: [date(2026,1,1), date(2026,4,30), "Entregado", "En camino", "Buenos Aires"]
```

Devuelve el string WHERE y la lista de parámetros. Todas las demás funciones lo llaman para aplicar los filtros del usuario.

#### `get_kpis(conn, filters)` — Métricas principales

Ejecuta una sola consulta que calcula en paralelo todos los KPIs:
- `total_ventas`: cantidad de ventas en el período (excluye canceladas para los montos)
- `ingresos_brutos`: suma de `product_revenue`
- `ingresos_netos`: suma de `total_amount` (lo que realmente recibe el vendedor)
- `comisiones_ml`: suma del valor absoluto de `sale_fee`
- `tasa_comision`: comisiones / ingresos brutos × 100
- `ticket_promedio`: promedio de `total_amount`
- `total_unidades`: suma de `quantity`
- `ventas_entregadas`: count donde `status = 'Entregado'`
- `ventas_con_reclamo`: count donde `claim_open = 'Sí'`

Las ventas canceladas se excluyen de los cálculos financieros pero sí aparecen en el count total.

#### `get_revenue_over_time(conn, filters, granularity)` — Evolución temporal

Agrupa ingresos por período. La granularidad puede ser `"day"`, `"week"` o `"month"`. Usa las funciones SQL `DATE_TRUNC` de DuckDB para agrupar por semana o mes. Devuelve un DataFrame con columnas: `periodo`, `ingresos_netos`, `ingresos_brutos`, `cantidad_ventas`, `unidades`.

#### `get_top_products(conn, filters, by, limit)` — Top productos

Agrupa por `product_title` y ordena según el criterio `by`: `"revenue"` (ingresos netos), `"units"` (unidades), o `"count"` (número de transacciones). Devuelve los N primeros.

#### `get_cost_breakdown(conn, filters)` — Desglose de costos

Calcula los componentes financieros para el gráfico waterfall: ingresos brutos, menos comisión ML, menos impuestos, menos costo de envío, menos descuentos, menos reembolsos = ingreso neto. Devuelve un DataFrame con columnas `componente`, `valor`, `tipo` (ingreso / costo / neto).

#### `get_filter_options(conn)` — Opciones de filtros

Consulta los valores únicos disponibles en la base actual: estados de venta, provincias, productos, y el rango de fechas mínimo/máximo. Estos valores se usan para poblar los widgets de filtro en el sidebar.

#### `get_sales_table(conn, filters, limit, offset)` — Tabla paginada

Devuelve un subconjunto de filas para mostrar en la página 2_Datos.py, con paginación. El `offset` indica desde qué fila empezar y `limit` cuántas traer. Ordena por fecha descendente.

---

### `components/charts.py` — Gráficos Plotly

Contiene funciones puras: reciben un DataFrame y devuelven un objeto `go.Figure` de Plotly. No tienen lógica de negocio, solo presentación.

#### Paleta de colores

```python
COLORS = {
    "yellow":  "#FFE600",   # Color primario (amarillo ML)
    "blue":    "#3483FA",   # Azul ML
    "green":   "#00A650",   # Verde (éxito, entregado)
    "red":     "#EF4444",   # Rojo (cancelado, costos)
    "bg":      "#0d1117",   # Fondo oscuro (GitHub dark)
    "bg2":     "#161b22",   # Fondo secundario
    "text":    "#e6edf3",   # Texto claro
    "grid":    "#21262d",   # Líneas de grilla
}
```

#### `revenue_over_time(df, granularity)` — Gráfico de línea doble

Muestra dos líneas en el tiempo: ingresos brutos (azul punteado) e ingresos netos (amarillo con área sombreada). El sombreado bajo la línea de netos da sensación de volumen.

#### `sales_by_status(df)` — Gráfico de dona

Torta con hueco central que muestra la distribución de ventas por estado. Cada estado tiene un color fijo definido en `STATUS_COLORS`.

#### `top_products(df, by)` — Barras horizontales

Barras horizontales ordenadas de menor a mayor (para que el más grande quede arriba). Usa un gradiente de color donde las barras más largas son más brillantes. El texto de valor aparece a la derecha de cada barra.

#### `sales_by_province(df)` — Barras horizontales por geografía

Similar a top_products pero para provincias. Muestra las 15 primeras.

#### `cost_waterfall(df)` — Waterfall de desglose financiero

Visualiza cómo los ingresos brutos se convierten en ingresos netos a través de distintos costos. La primera barra es "Ingresos brutos" (valor total positivo), luego vienen barras de costos (negativas: comisión ML, impuestos, envío, descuentos, reembolsos), y la última barra es "Ingreso neto" (total acumulado). Es útil para entender de dónde viene la diferencia entre bruto y neto.

#### `sales_by_weekday(df)` — Barras por día de la semana

Toma el DataFrame temporal (que ya tiene la columna `periodo` con fechas), extrae el día de la semana de cada fecha con `.dt.weekday`, suma las ventas por día (0=Lunes, 6=Domingo) y muestra barras con gradiente.

#### `_apply_base(fig, title)` y `_empty_chart(msg)`

Helpers internos. `_apply_base` aplica el tema oscuro y la tipografía a cualquier figura. `_empty_chart` devuelve una figura vacía con un mensaje cuando no hay datos para mostrar (en lugar de mostrar un gráfico roto).

---

### `pages/1_Dashboard.py` — El dashboard principal

Es la página más compleja de la interfaz. Combina filtros, KPIs y seis gráficos distintos.

**Flujo de ejecución (Streamlit re-ejecuta todo el archivo en cada interacción):**

1. Verifica que haya datos en la sesión. Si no hay, redirige a `app.py`.
2. Consulta las opciones disponibles para los filtros con `get_filter_options()`.
3. Renderiza el sidebar con cuatro filtros: rango de fechas (dos date pickers), estado (multiselect), provincia (multiselect), y granularidad temporal (radio button: día/semana/mes).
4. Construye el diccionario `filters` con los valores seleccionados.
5. Llama a `get_kpis(conn, filters)` y muestra los resultados en métricas de Streamlit.
6. Llama a `get_revenue_over_time()` y muestra el gráfico temporal.
7. En dos columnas: gráfico de dona por estado + barras por día de la semana.
8. Dos pestañas (tabs): top productos por ingresos / por unidades.
9. En dos columnas: ventas por provincia + waterfall de costos.

Cada vez que el usuario mueve un filtro, Streamlit vuelve a ejecutar toda esta secuencia automáticamente, actualizando todos los gráficos y métricas.

---

### `pages/2_Datos.py` — Explorador de datos

Muestra la tabla de ventas filtrable con paginación y descarga CSV.

**Características:**
- Los mismos filtros que el dashboard (fecha, estado, provincia).
- Selector de cuántas filas mostrar por página (50, 100, 200, 500).
- Paginador numérico que permite saltar a cualquier página.
- Tabla interactiva de Streamlit con columnas configuradas (anchos, formatos).
- Botón de descarga que exporta **todas las filas filtradas** (hasta 100.000) como CSV, no solo la página actual.
- Las columnas monetarias se formatean como `$1.234` para facilitar la lectura.

---

### `.streamlit/config.toml` — Configuración de Streamlit

```toml
[theme]
primaryColor = "#FFE600"           # Amarillo ML para botones y acentos
backgroundColor = "#0d1117"        # Fondo oscuro principal
secondaryBackgroundColor = "#161b22"  # Fondo de cards y sidebar
textColor = "#e6edf3"              # Texto claro
font = "sans serif"

[server]
headless = true                    # Necesario para correr en la nube sin abrir browser
maxUploadSize = 50                 # Máximo 50 MB por archivo subido

[browser]
gatherUsageStats = false           # Desactiva telemetría de Streamlit
```

---

## Decisiones de diseño importantes

### Por qué los datos no se guardan entre sesiones

Es una decisión deliberada. Los datos de ventas son sensibles. Al no guardarlos en ningún servidor, el usuario tiene control total: sus datos nunca salen de su navegador. Esto también simplifica el despliegue: no hay base de datos que mantener, no hay backups, no hay costo de almacenamiento.

### Por qué DuckDB en lugar de pandas puro

Con pandas, cada vez que el usuario cambia un filtro habría que volver a cargar el archivo y re-filtrar en Python. DuckDB permite hacer esas operaciones con SQL optimizado, en memoria, en milisegundos incluso con miles de filas. Además, el esquema explícito de DuckDB garantiza que los tipos de datos son correctos antes de hacer cálculos.

### Por qué `dtype=str` en la lectura del Excel

Pandas intenta adivinar los tipos de datos de cada columna cuando lee un Excel. Eso genera problemas: un campo de IDs de venta como `2000012585158951` puede interpretarse como número flotante y perder precisión. Los campos de DNI con valores mixtos (números y espacios) pueden provocar errores de conversión. Al leer todo como string, el parser tiene control total sobre qué y cómo convierte cada campo.

### Por qué `buyer_dni` es VARCHAR y no BIGINT

El DNI es un identificador, no una cantidad. No tiene sentido sumarlo ni promediarlo. Además, el export real de MercadoLibre a veces deja ese campo en blanco (con un espacio `' '`), lo que haría fallar una conversión a entero. Como texto, acepta cualquier valor incluido el vacío.

### Por qué se descarta columnas no mapeadas

El Excel de MercadoLibre tiene columnas que no son útiles para el análisis (texto legal, links de seguimiento secundarios, etc.). El `COLUMN_MAP` actúa como whitelist: solo pasan las columnas que el proyecto sabe manejar. Esto hace el sistema robusto ante cambios futuros en el formato del Excel: si MercadoLibre agrega columnas nuevas, el parser las ignora sin romperse.

---

## Cómo correrlo localmente

```bash
# Activar el entorno virtual
source /ruta/al/venv/bin/activate   # Linux/Mac
# o en Windows:
.venv\Scripts\activate

# Ejecutar la app
cd ml-ventas
streamlit run app.py
```

La app queda en `http://localhost:8501`.

---

## Cómo deployarlo en Streamlit Cloud (gratis)

1. El código tiene que estar en un repositorio público de GitHub.
2. Entrás a [share.streamlit.io](https://share.streamlit.io) con tu cuenta de GitHub.
3. Hacés clic en "New app", seleccionás el repositorio y el archivo `app.py`.
4. Streamlit Cloud instala las dependencias de `requirements.txt` automáticamente.
5. Cada vez que hacés `git push`, la app se redeploya sola en 1-3 minutos.

No hay servidor que configurar, no hay Dockerfile, no hay costos.
