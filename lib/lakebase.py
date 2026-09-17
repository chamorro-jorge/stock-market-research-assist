"""
Conexión a Lakebase (Postgres gestionado por Databricks).

La URL completa vive en el secret scope `database`, clave `lakebase-url`
(ver SETUP.md). Mismo patrón que en day-3.
"""

import base64
import os
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor, execute_values

_SCOPE = os.environ.get("LAKEBASE_SECRET_SCOPE", "database")
_KEY = os.environ.get("LAKEBASE_SECRET_KEY", "lakebase-url")


def lakebase_url() -> str:
    """URL de conexión, desde el secret scope o, en local, del entorno."""
    try:
        from databricks.sdk import WorkspaceClient

        secret = WorkspaceClient().secrets.get_secret(scope=_SCOPE, key=_KEY)
        return base64.b64decode(secret.value).decode("utf-8").strip()
    except Exception:
        url = os.environ.get("LAKEBASE_URL", "").strip()
        if not url:
            raise RuntimeError(
                f"No hay URL de Lakebase: falta el secreto {_SCOPE}/{_KEY} y "
                "tampoco está LAKEBASE_URL en el entorno. Ver SETUP.md."
            )
        return url


@contextmanager
def get_connection():
    """Conexión con transacción: commit al salir, rollback si hay excepción."""
    conn = psycopg2.connect(lakebase_url(), cursor_factory=RealDictCursor)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def query(sql: str, params: tuple | None = None) -> list[dict]:
    """Ejecuta un SELECT y devuelve la lista de filas como diccionarios."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]


def upsert(table: str, columns: list[str], rows: list[tuple], conflict: str,
           update_columns: list[str] | None = None) -> int:
    """
    Inserta filas resolviendo conflictos, en un solo viaje a la base.

    La ingesta se reejecuta a diario, así que todas las escrituras tienen que
    ser idempotentes: `conflict` es la clave que identifica el duplicado.

    Args:
        table: nombre de la tabla
        columns: columnas a insertar
        rows: tuplas de valores, en el orden de `columns`
        conflict: columnas de la restricción, p.ej. "(ticker, snapshot_date)"
        update_columns: columnas a refrescar si la fila ya existía.
                        Si es None, el conflicto se ignora (DO NOTHING).

    Returns:
        Número de filas realmente insertadas o actualizadas.
    """
    if not rows:
        return 0

    cols = ", ".join(columns)
    if update_columns:
        sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_columns)
        action = f"DO UPDATE SET {sets}"
    else:
        action = "DO NOTHING"

    sql = (
        f"INSERT INTO {table} ({cols}) VALUES %s "
        f"ON CONFLICT {conflict} {action}"
    )

    with get_connection() as conn:
        with conn.cursor() as cur:
            execute_values(cur, sql, rows, page_size=500)
            return cur.rowcount


def get_watchlist_tickers(user_email: str | None = None) -> list[str]:
    """
    Tickers que hay que ingerir: los de las watchlists.

    Es lo que hace que un ticker añadido por el agente en M2 entre solo en la
    siguiente ejecución del job.
    """
    if user_email:
        sql = """
            SELECT DISTINCT wt.ticker
            FROM watchlist_tickers wt
            JOIN watchlists w ON w.id = wt.watchlist_id
            JOIN users u ON u.id = w.user_id
            WHERE u.email = %s
            ORDER BY 1
        """
        rows = query(sql, (user_email,))
    else:
        rows = query("SELECT DISTINCT ticker FROM watchlist_tickers ORDER BY 1")

    return [r["ticker"] for r in rows]
