"""
Pipeline de ingesta: Massive API -> bronze -> silver -> gold -> Lakebase.

    bronze  JSON crudo tal cual llega de la API, en Delta. Permite reprocesar
            sin volver a gastar llamadas contra la cuota del plan gratuito.
    silver  Normalizado y deduplicado, con Spark.
    gold    Texto troceado y embebido, listo para la búsqueda semántica.

Luego se vuelca a Lakebase, que es lo que consultan la app y el agente.

Todo es idempotente: se puede reejecutar a diario sin duplicar nada.

Ejecución:
    databricks bundle run ingest_market_data -t dev
"""

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (ArrayType, StringType, StructField, StructType,
                               TimestampType)

# El job se despliega con el repo entero, así que lib/ está al lado de jobs/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import lakebase  # noqa: E402
from lib.embeddings import chunk_text, embed_texts, to_pgvector  # noqa: E402
from lib.massive_client import MassiveClient  # noqa: E402

DEFAULT_TICKERS = ["AAPL", "MSFT", "NVDA", "JPM", "XOM"]


# --------------------------------------------------------------------- bronze

def fetch_raw(tickers: list[str], news_since: str) -> tuple[list[dict], list[dict]]:
    """Descarga perfiles y noticias. Es la única parte que toca la red.

    Se hace en el driver porque son pocas llamadas y así se respeta el límite
    de peticiones por minuto del plan gratuito; paralelizarlo en los executors
    solo serviría para provocar 429.
    """
    client = MassiveClient()
    profiles, news = [], []

    for ticker in tickers:
        print(f"[bronze] {ticker}: perfil")
        profile = client.get_company_profile(ticker)
        if profile:
            profiles.append({"ticker": ticker, "payload": profile})

        print(f"[bronze] {ticker}: noticias desde {news_since}")
        articles = client.get_news(ticker, limit=50, published_utc_gte=news_since)
        for article in articles:
            news.append({"ticker": ticker, "payload": article})
        print(f"[bronze] {ticker}: {len(articles)} noticias")

    return profiles, news


def write_bronze(spark: SparkSession, table: str, rows: list[dict], raw_schema) -> None:
    """Guarda el crudo en Delta, particionado por fecha de ingesta."""
    if not rows:
        print(f"[bronze] nada que escribir en {table}")
        return

    import json

    df = spark.createDataFrame(
        [(r["ticker"], json.dumps(r["payload"])) for r in rows],
        schema=raw_schema,
    ).withColumn("ingested_at", F.current_timestamp())

    (df.write.format("delta")
       .mode("append")
       .option("mergeSchema", "true")
       .saveAsTable(table))
    print(f"[bronze] {df.count()} filas -> {table}")


# --------------------------------------------------------------------- silver

def silver_companies(spark: SparkSession, profiles: list[dict]):
    """Perfiles normalizados: una fila por empresa."""
    rows = []
    for item in profiles:
        p = item["payload"]
        rows.append((
            item["ticker"],
            p.get("name"),
            p.get("description"),
            p.get("sic_description") or p.get("sector"),
            p.get("industry"),
            float(p["market_cap"]) if p.get("market_cap") else None,
            p.get("homepage_url"),
        ))

    schema = StructType([
        StructField("ticker", StringType()),
        StructField("name", StringType()),
        StructField("description", StringType()),
        StructField("sector", StringType()),
        StructField("industry", StringType()),
        StructField("market_cap", StringType()),
        StructField("homepage_url", StringType()),
    ])
    # market_cap como string en el schema y casteado después: los JSON de la
    # API mezclan enteros y decimales y Spark se queja al inferir.
    df = spark.createDataFrame(
        [(r[0], r[1], r[2], r[3], r[4], str(r[5]) if r[5] is not None else None, r[6])
         for r in rows],
        schema=schema,
    )
    return df.withColumn("market_cap", F.col("market_cap").cast("decimal(20,2)"))


def silver_news(spark: SparkSession, news: list[dict]):
    """Noticias normalizadas y deduplicadas por id de Massive."""
    rows = []
    for item in news:
        a = item["payload"]
        if not a.get("id") or not a.get("title"):
            continue
        rows.append((
            a["id"],
            item["ticker"],
            a.get("title"),
            a.get("description"),
            a.get("article_url"),
            (a.get("publisher") or {}).get("name"),
            a.get("published_utc"),
        ))

    schema = StructType([
        StructField("id", StringType()),
        StructField("ticker", StringType()),
        StructField("title", StringType()),
        StructField("description", StringType()),
        StructField("article_url", StringType()),
        StructField("publisher", StringType()),
        StructField("published_utc", StringType()),
    ])

    df = spark.createDataFrame(rows, schema=schema)
    return (df
            .withColumn("published_at", F.to_timestamp("published_utc"))
            .drop("published_utc")
            # Una misma noticia puede venir asociada a varios tickers.
            .dropDuplicates(["id"]))


# ----------------------------------------------------------------------- gold

def build_chunks(companies_df, news_df):
    """
    Texto -> fragmentos, en Spark.

    Perfiles y noticias acaban en la misma forma (ticker, doc_type, source_id,
    chunk_index, chunk_text, published_at) para que una sola búsqueda semántica
    cubra las dos fuentes.
    """
    chunk_udf = F.udf(lambda t: chunk_text(t or ""), ArrayType(StringType()))

    profile_chunks = (
        companies_df
        .withColumn("full_text", F.concat_ws(". ",
                                             F.col("name"),
                                             F.col("sector"),
                                             F.col("description")))
        .filter(F.col("description").isNotNull())
        .withColumn("chunks", chunk_udf(F.col("full_text")))
        .select(
            F.col("ticker"),
            F.lit("profile").alias("doc_type"),
            F.col("ticker").alias("source_id"),
            F.posexplode("chunks").alias("chunk_index", "chunk_text"),
            F.lit(None).cast(TimestampType()).alias("published_at"),
        )
    )

    news_chunks = (
        news_df
        .withColumn("full_text", F.concat_ws(". ",
                                             F.col("title"),
                                             F.col("description")))
        .withColumn("chunks", chunk_udf(F.col("full_text")))
        .select(
            F.col("ticker"),
            F.lit("news").alias("doc_type"),
            F.col("id").alias("source_id"),
            F.posexplode("chunks").alias("chunk_index", "chunk_text"),
            F.col("published_at"),
        )
    )

    return profile_chunks.unionByName(news_chunks).filter(F.length("chunk_text") > 50)


def existing_chunk_keys() -> set:
    """Claves ya embebidas, para no volver a pagar por ellas."""
    rows = lakebase.query(
        "SELECT doc_type, source_id, chunk_index FROM document_chunks"
    )
    return {(r["doc_type"], r["source_id"], r["chunk_index"]) for r in rows}


# ------------------------------------------------------------------- lakebase

def load_companies(companies_df) -> int:
    rows = [
        (r["ticker"], r["name"], r["description"], r["sector"], r["industry"],
         r["market_cap"], r["homepage_url"])
        for r in companies_df.collect()
    ]
    return lakebase.upsert(
        "companies",
        ["ticker", "name", "description", "sector", "industry", "market_cap",
         "homepage_url"],
        rows,
        conflict="(ticker)",
        update_columns=["name", "description", "sector", "industry", "market_cap",
                        "homepage_url"],
    )


def load_news(news_df) -> int:
    rows = [
        (r["id"], r["ticker"], r["title"], r["description"], r["article_url"],
         r["publisher"], r["published_at"])
        for r in news_df.collect()
    ]
    return lakebase.upsert(
        "news_articles",
        ["id", "ticker", "title", "description", "article_url", "publisher",
         "published_at"],
        rows,
        conflict="(id)",
    )


def load_chunks(chunks_df) -> int:
    """Embebe solo lo nuevo y lo carga."""
    already = existing_chunk_keys()

    pending = [
        r for r in chunks_df.collect()
        if (r["doc_type"], r["source_id"], r["chunk_index"]) not in already
    ]
    print(f"[gold] {len(pending)} chunks nuevos (ya había {len(already)})")
    if not pending:
        return 0

    vectors = embed_texts([r["chunk_text"] for r in pending])

    rows = [
        (r["ticker"], r["doc_type"], r["source_id"], r["chunk_index"],
         r["chunk_text"], r["published_at"], to_pgvector(v))
        for r, v in zip(pending, vectors)
    ]
    return lakebase.upsert(
        "document_chunks",
        ["ticker", "doc_type", "source_id", "chunk_index", "chunk_text",
         "published_at", "embedding"],
        rows,
        conflict="(doc_type, source_id, chunk_index)",
    )


# ------------------------------------------------------------------------ main

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", default="",
                        help="Lista separada por comas. Si se omite, se leen "
                             "de las watchlists de Lakebase.")
    parser.add_argument("--news-days", type=int, default=14,
                        help="Ventana de noticias a pedir, en días.")
    parser.add_argument("--catalog", default="main")
    parser.add_argument("--schema", default="stock_research")
    args = parser.parse_args()

    spark = SparkSession.builder.getOrCreate()
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {args.catalog}.{args.schema}")
    prefix = f"{args.catalog}.{args.schema}"

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        tickers = lakebase.get_watchlist_tickers() or DEFAULT_TICKERS
    print(f"Tickers: {tickers}")

    news_since = (datetime.now(timezone.utc)
                  - timedelta(days=args.news_days)).strftime("%Y-%m-%d")

    # bronze
    profiles, news = fetch_raw(tickers, news_since)
    raw_schema = StructType([
        StructField("ticker", StringType()),
        StructField("payload", StringType()),
    ])
    write_bronze(spark, f"{prefix}.bronze_profiles", profiles, raw_schema)
    write_bronze(spark, f"{prefix}.bronze_news", news, raw_schema)

    # silver
    companies_df = silver_companies(spark, profiles)
    news_df = silver_news(spark, news)
    companies_df.write.format("delta").mode("overwrite").option(
        "overwriteSchema", "true").saveAsTable(f"{prefix}.silver_companies")
    news_df.write.format("delta").mode("append").option(
        "mergeSchema", "true").saveAsTable(f"{prefix}.silver_news")

    # gold + carga
    chunks_df = build_chunks(companies_df, news_df)
    n_companies = load_companies(companies_df)
    n_news = load_news(news_df)
    n_chunks = load_chunks(chunks_df)

    print(f"\nLakebase: {n_companies} empresas, {n_news} noticias, "
          f"{n_chunks} chunks nuevos")


if __name__ == "__main__":
    main()
