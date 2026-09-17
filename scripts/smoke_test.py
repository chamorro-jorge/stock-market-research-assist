"""
Comprobación rápida de que las credenciales y las tablas están bien.

Ejecútalo ANTES del job de ingesta: tarda segundos y te dice exactamente cuál
de las tres piezas falla, en vez de tener que leer la traza de un job Spark.

    %run ./scripts/smoke_test.py      (en un notebook de Databricks)
    python scripts/smoke_test.py      (en local, con .env relleno)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import lakebase  # noqa: E402
from lib.embeddings import EMBEDDING_DIM, embed_texts  # noqa: E402
from lib.massive_client import MassiveClient  # noqa: E402

TICKER = "AAPL"


def check(name: str, fn) -> bool:
    try:
        detail = fn()
        print(f"  OK    {name}: {detail}")
        return True
    except Exception as exc:
        print(f"  FALLO {name}: {type(exc).__name__}: {exc}")
        return False


def main() -> int:
    print("\n1. Massive API")
    client = MassiveClient()
    ok = [
        check("perfil de empresa",
              lambda: (client.get_company_profile(TICKER).get("name") or "sin nombre")),
        check("noticias",
              lambda: f"{len(client.get_news(TICKER, limit=5))} artículos"),
        check("precio previo",
              lambda: f"cierre {client.get_prev_close(TICKER).get('c')}"),
    ]

    print("\n2. Lakebase")
    ok += [
        check("conexión", lambda: lakebase.query("SELECT version() AS v")[0]["v"][:40]),
        check("tablas creadas", lambda: ", ".join(
            r["tablename"] for r in lakebase.query(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                "ORDER BY tablename"))),
        check("extensión pgvector", lambda: lakebase.query(
            "SELECT extversion AS v FROM pg_extension WHERE extname = 'vector'"
        )[0]["v"]),
        check("watchlist sembrada",
              lambda: lakebase.get_watchlist_tickers() or "VACÍA - ver sql/seed.sql"),
    ]

    print("\n3. Embeddings")
    ok.append(check(
        "endpoint de Foundation Model",
        lambda: f"dimensión {len(embed_texts(['prueba de embedding'])[0])} "
                f"(esperada {EMBEDDING_DIM})"))

    fallos = ok.count(False)
    print(f"\n{'Todo correcto.' if not fallos else f'{fallos} comprobacion(es) fallidas.'}")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
