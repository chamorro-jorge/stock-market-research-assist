"""
Cliente de la Massive API.

La API key vive en un secret scope de Databricks (ver SETUP.md) y se resuelve en
tiempo de ejecución; nunca en el código, en .env versionados ni en app.yaml.

En local, si no hay workspace disponible, cae a la variable de entorno
MASSIVE_API_KEY para poder probar desde el portátil.
"""

import base64
import os
import time
from typing import Any

import requests

_SCOPE = os.environ.get("MASSIVE_SECRET_SCOPE", "massive")
_KEY = os.environ.get("MASSIVE_SECRET_KEY", "api-key")
_BASE_URL = os.environ.get("MASSIVE_API_BASE_URL", "https://api.massive.com")

_DEFAULT_TIMEOUT = 30
_MAX_RETRIES = 4


def _get_api_key() -> str:
    """Lee la API key del secret scope; si no hay workspace, del entorno."""
    try:
        from databricks.sdk import WorkspaceClient

        secret = WorkspaceClient().secrets.get_secret(scope=_SCOPE, key=_KEY)
        return base64.b64decode(secret.value).decode("utf-8").strip()
    except Exception:
        key = os.environ.get("MASSIVE_API_KEY", "").strip()
        if not key:
            raise RuntimeError(
                f"No hay API key: falta el secreto {_SCOPE}/{_KEY} en Databricks "
                "y tampoco está MASSIVE_API_KEY en el entorno. Ver SETUP.md."
            )
        return key


class MassiveClient:
    """Envoltorio fino sobre la Massive API, con reintentos ante 429."""

    def __init__(self, base_url: str | None = None, timeout: int = _DEFAULT_TIMEOUT):
        self.base_url = (base_url or _BASE_URL).rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {_get_api_key()}",
                "Content-Type": "application/json",
            }
        )

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        """GET con reintento exponencial ante 429 y errores 5xx.

        El plan gratuito limita las peticiones por minuto, así que un 429 es
        esperable en cuanto se ingieren varios tickers seguidos.
        """
        url = f"{self.base_url}{path}"
        for attempt in range(_MAX_RETRIES):
            resp = self._session.get(url, params=params, timeout=self.timeout)

            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == _MAX_RETRIES - 1:
                    resp.raise_for_status()
                wait = 2 ** attempt * 5
                print(f"  {resp.status_code} en {path}; reintento en {wait}s")
                time.sleep(wait)
                continue

            if resp.status_code == 401:
                raise RuntimeError(
                    "401 de Massive: la API key no es válida. Revisa que el secreto "
                    f"{_SCOPE}/{_KEY} contenga solo la clave, sin comillas ni salto "
                    "de línea final."
                )

            resp.raise_for_status()
            return resp.json()

        raise RuntimeError(f"No se pudo completar la petición a {path}")

    # ------------------------------------------------------------------ perfiles

    def get_company_profile(self, ticker: str) -> dict:
        """Perfil de la empresa: nombre, descripción, sector, capitalización.

        La descripción es el texto no estructurado que luego se embebe.
        """
        data = self.get(f"/v3/reference/tickers/{ticker}")
        return data.get("results", {}) or {}

    def get_financials(self, ticker: str, limit: int = 4) -> list[dict]:
        """Fundamentales de los últimos periodos (origen: informes 10-K/10-Q)."""
        data = self.get(
            "/vX/reference/financials",
            params={"ticker": ticker, "limit": limit, "order": "desc"},
        )
        return data.get("results", []) or []

    # -------------------------------------------------------------------- news

    def get_news(
        self,
        ticker: str,
        limit: int = 50,
        published_utc_gte: str | None = None,
    ) -> list[dict]:
        """Noticias recientes de un ticker.

        Cada elemento trae: id, title, description, article_url, publisher,
        published_utc. `published_utc_gte` (ISO) permite la ingesta incremental:
        pedir solo lo publicado desde la última ejecución.
        """
        params: dict[str, Any] = {
            "ticker": ticker,
            "limit": limit,
            "order": "desc",
            "sort": "published_utc",
        }
        if published_utc_gte:
            params["published_utc.gte"] = published_utc_gte

        data = self.get("/v2/reference/news", params=params)
        return data.get("results", []) or []

    # ------------------------------------------------------------------ precios

    def get_daily_bars(self, ticker: str, date_from: str, date_to: str) -> list[dict]:
        """Barras diarias entre dos fechas (YYYY-MM-DD).

        Cada barra: t (epoch ms), o, h, l, c, v.
        """
        data = self.get(
            f"/v2/aggs/ticker/{ticker}/range/1/day/{date_from}/{date_to}",
            params={"adjusted": "true", "sort": "asc", "limit": 50000},
        )
        return data.get("results", []) or []

    def get_prev_close(self, ticker: str) -> dict:
        """Cierre de la sesión anterior, en una sola llamada."""
        data = self.get(f"/v2/aggs/ticker/{ticker}/prev")
        results = data.get("results", []) or []
        return results[0] if results else {}

    def ticker_exists(self, ticker: str) -> bool:
        """¿Existe el ticker? Lo usa add_to_watchlist antes de escribir (M2)."""
        try:
            return bool(self.get_company_profile(ticker))
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                return False
            raise
