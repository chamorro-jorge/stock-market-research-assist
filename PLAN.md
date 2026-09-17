# Capstone — Agente de análisis de watchlist de acciones

Un usuario mantiene una watchlist de tickers, plantea una tesis o pregunta de inversión,
y un agente consulta datos reales de mercado, resume fundamentales y noticias, y registra
el análisis.

## Requisitos del bootcamp y dónde se cumplen

| Requisito | Dónde | Hito |
|---|---|---|
| Pipeline de datos en Spark | `jobs/ingest_*` — job Databricks | M1 |
| API de terceros | Massive API (precios, perfiles, noticias, fundamentales) | M1 |
| Datos no estructurados | Texto de noticias y perfiles → chunks → embeddings | M1 |
| Databricks App con frontend | `app/` — chat + vista de watchlist | M1 |
| Agente con herramientas (lectura **y escritura**) | `mcp_server/` + `tools/` | M2 |

> **Al terminar M2 el proyecto ya es entregable.** M3 en adelante es profundidad.

## Decisiones tomadas (no revisitar sin motivo)

1. **El agente existe desde M1**, con una sola herramienta (`search_context`). El RAG es la
   primera herramienta, no una fase previa. Evita reescribir el bucle al añadir herramientas.
2. **Modelo de embeddings: `databricks-gte-large-en` (1024 dimensiones).** Fijado ahora
   porque cambiarlo obliga a regenerar todos los vectores y a migrar la columna.
3. **Una sola tabla de vectores**, `document_chunks`, con `doc_type` para distinguir
   noticia / perfil / filing / earnings. Una búsqueda cubre todas las fuentes.
4. **La lógica de las herramientas son funciones Python puras** en `tools/`, testeables con
   pytest sin LLM. El MCP server es una capa fina encima.
5. **El `user_id` sale de la sesión de la app, nunca de la LLM.** Si la LLM lo elige,
   cualquiera modifica la watchlist de otro con un prompt.
6. **La ingesta es idempotente e incremental** desde M1: upsert por id y marca de tiempo.
   El job corre muchas veces; si no, duplica datos y quema llamadas a la API.
7. **`users.last_visit_at` se actualiza desde M1**, aunque no se use hasta M4. Ese histórico
   no se puede recuperar después.
8. **Filings (SEC EDGAR) y earnings calls van al final** (M5) y son opcionales. Massive no
   da ese texto; requieren una segunda fuente y son lo más caro por lo que aportan.
9. **Universo: AAPL, MSFT, NVDA, JPM, XOM.** Cinco tickers de sectores distintos. Con uno
   solo la búsqueda semántica no demuestra nada (todo devuelve el mismo), y el coste de
   pasar de 1 a 5 es una lista en vez de una cadena. Descartado `CBOT:ZW1`: es un futuro,
   no tiene perfil de empresa, fundamentales ni earnings, así que no hay texto que embeber.

## Hitos

### M0 — Cimientos `[en curso]`
- [x] `git init` + `.gitignore` (los `.env` de day-2 quedan fuera)
- [x] `PLAN.md` y esquema SQL
- [ ] `databricks.yml` (Databricks Asset Bundle)
- [ ] Secret scope con la API key de Massive (reutilizar el patrón de `massive_client.py`)
- [ ] Crear tablas en Lakebase + sembrar 1 usuario y la watchlist (AAPL, MSFT, NVDA, JPM, XOM)

### M1 — Esqueleto vertical `[pendiente]`
El corte más fino que atraviesa **todas** las capas y queda desplegado.
- [ ] Job Spark: Massive → bronze (JSON crudo) → silver (limpio, chunked) → gold (embeddings)
- [ ] Carga en Lakebase: `companies`, `news_articles`, `document_chunks`
- [ ] Solo esos 5 tickers y solo noticias + perfiles de empresa
- [ ] `tools/search_context.py` — búsqueda vectorial con filtros
- [ ] App desplegada: chat con agente que tiene esa única herramienta
- [ ] **Set de evaluación**: 10-15 preguntas con los chunks que deberían salir; medir acierto en top-5

*Criterio de "hecho": la app desplegada responde a "¿qué empresas tienen exposición a tipos
de interés?" citando chunks reales, y el set de evaluación pasa por encima del umbral fijado.*

### M2 — Primeras escrituras → entregable `[pendiente]`
- [ ] `get_watchlist(user)` — lectura trivial; valida el tool-calling aislado de la lógica
- [ ] `add_to_watchlist` / `remove_from_watchlist` — primera escritura
      - validar que el ticker existe contra Massive
      - idempotente (añadir dos veces no duplica)
      - `user_id` desde la sesión
- [ ] Un ticker nuevo entra en la ingesta en la siguiente ejecución del job
- [ ] Tests pytest de cada herramienta

### M3 — Precios y comparación `[pendiente]`
- [ ] El job carga `price_snapshots` (aggregates diarios)
- [ ] `get_price_history(ticker, range)` — rendimiento, máximo/mínimo, volatilidad
- [ ] `compare_tickers(tickers, metrics)` — fundamentales y precio
- [ ] La app muestra la watchlist con precios, no solo el chat

### M4 — Memoria y avisos `[pendiente]`
- [ ] `save_research_note` / `save_analysis_report` — el agente encadena buscar → comparar → guardar
- [ ] `get_changes_since_last_visit(user)` — define "notable": umbral de % y noticias nuevas
- [ ] Job programado (schedule diario) e ingesta incremental verificada

### M5 — Enriquecer el contexto (opcional) `[pendiente]`
- [ ] SEC EDGAR: 10-K/10-Q → secciones "Risk Factors" y "MD&A" → chunks
- [ ] Resúmenes de earnings generados con LLM a partir de fundamentales + noticias
- [ ] Pulir la interfaz, README y vídeo/capturas de la entrega

## Riesgos conocidos

- **El tiempo se va en despliegue, no en lógica.** Por eso la app se despliega en M1.
- **Límites del plan gratuito de Massive.** Comprobar cuota antes de ampliar el número de
  tickers; cachear en bronze para no repetir llamadas.
- **Deriva de calidad del RAG.** Cada cambio de chunking o de filtros se valida contra el
  set de evaluación antes de darlo por bueno.
