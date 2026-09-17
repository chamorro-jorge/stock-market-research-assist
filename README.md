# Stock Market Research Assistant

Capstone del bootcamp *Rise of the AI Data Engineer*.

Un usuario mantiene una watchlist de tickers, plantea una pregunta o tesis de inversión, y
un agente consulta datos reales de mercado, resume fundamentales y noticias mediante
búsqueda semántica, y registra el análisis en la base de datos.

**Universo inicial:** AAPL, MSFT, NVDA, JPM, XOM — cinco sectores distintos, para que la
recuperación semántica tenga que discriminar de verdad.

## Cómo cumple los requisitos

| Requisito | Implementación |
|---|---|
| Pipeline de datos en Spark | `jobs/ingest_market_data.py` — bronze → silver → gold, como job de Databricks |
| API de terceros | [Massive API](https://massive.com) — precios, perfiles de empresa, noticias, fundamentales |
| Datos no estructurados | Texto de noticias y perfiles → chunks → embeddings en pgvector |
| Databricks App con frontend | `app/` — chat con el agente y vista de la watchlist |
| Agente con herramientas | `tools/` expuestas por `mcp_server/`: búsqueda semántica (lectura) y alta/baja en watchlist y guardado de informes (escritura) |

## Estructura

```
jobs/        pipeline Spark de ingesta
lib/         cliente de Massive, conexión a Lakebase, embeddings
tools/       lógica de las herramientas del agente (funciones puras, testeables)
mcp_server/  expone las herramientas al agente
app/         Databricks App (frontend + chat)
sql/         esquema de Lakebase
tests/       pytest de las herramientas, sin LLM
```

## Puesta en marcha

1. Credenciales y tablas: ver **[SETUP.md](SETUP.md)** (se hace una vez).
2. Despliegue: `databricks bundle deploy -t dev`
3. Ingesta: `databricks bundle run ingest_market_data -t dev`

Estado y hitos en [PLAN.md](PLAN.md).

## Configuración

La clave de la API de Massive **nunca** va en el código ni en el repositorio. Se lee de un
secret scope de Databricks:

```bash
databricks secrets create-scope massive
databricks secrets put-secret massive api-key
```

Para desarrollo local, copia `.env.example` a `.env` (ignorado por git).
