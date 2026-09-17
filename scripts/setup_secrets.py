"""
Crea los secret scopes del proyecto. Se ejecuta UNA vez.

Dos formas, según lo que tengas a mano:

  A) Desde un notebook del workspace (no necesitas instalar nada):
         %run ./scripts/setup_secrets.py
     Aparecen dos widgets arriba. Pega los valores, vuelve a ejecutar la
     celda y BORRA los widgets después (menú del notebook -> Remove all widgets).

  B) En local, con la CLI de Databricks ya configurada:
         python scripts/setup_secrets.py
     Pide los valores por teclado, sin mostrarlos.

Los valores no se escriben nunca en disco ni en el repositorio.

Scopes que crea:
    massive  / api-key       -> la API key de Massive
    database / lakebase-url  -> postgresql://ROL:PASS@HOST:5432/databricks_postgres?sslmode=require
"""

from databricks.sdk import WorkspaceClient
from databricks.sdk.service import workspace

SECRETS = [
    ("massive", "api-key", "API key de Massive"),
    ("database", "lakebase-url", "URL de conexión a Lakebase"),
]


def _in_notebook() -> bool:
    try:
        dbutils  # noqa: F821
        return True
    except NameError:
        return False


def _read_values() -> dict:
    """Pide los valores por widget (notebook) o por teclado (local)."""
    if _in_notebook():
        for scope, key, label in SECRETS:
            dbutils.widgets.text(f"{scope}_{key}", "", label)  # noqa: F821
        values = {
            f"{scope}_{key}": dbutils.widgets.get(f"{scope}_{key}")  # noqa: F821
            for scope, key, _ in SECRETS
        }
        if not all(values.values()):
            raise SystemExit(
                "\nRellena los widgets de arriba con los valores y vuelve a "
                "ejecutar esta celda."
            )
        return values

    import getpass
    return {
        f"{scope}_{key}": getpass.getpass(f"{label}: ")
        for scope, key, label in SECRETS
    }


def main() -> None:
    w = WorkspaceClient()
    values = _read_values()

    for scope, key, label in SECRETS:
        value = values[f"{scope}_{key}"].strip()  # un \n de más provoca un 401
        if not value:
            print(f"  saltado {scope}/{key}: vacío")
            continue

        try:
            w.secrets.create_scope(scope=scope)
            print(f"  scope '{scope}' creado")
        except Exception as exc:
            if "RESOURCE_ALREADY_EXISTS" in str(exc):
                print(f"  scope '{scope}' ya existía")
            else:
                raise

        w.secrets.put_secret(scope=scope, key=key, string_value=value)

        # Para que la app y el job puedan leerlo, no solo tu usuario.
        try:
            w.secrets.put_acl(
                scope=scope,
                principal="users",
                permission=workspace.AclPermission.READ,
            )
        except Exception as exc:
            print(f"  aviso: no se pudo dar permiso de lectura en '{scope}': {exc}")

        print(f"  {scope}/{key} guardado ({len(value)} caracteres)")

    print("\nComprobación:")
    for scope in {s for s, _, _ in SECRETS}:
        keys = [s.key for s in w.secrets.list_secrets(scope=scope)]
        print(f"  {scope}: {keys}")

    print(
        "\nHecho. Ahora ejecuta scripts/smoke_test.py para verificar que los "
        "valores son correctos."
    )
    if _in_notebook():
        print("Y borra los widgets: menú del notebook -> Remove all widgets.")


if __name__ == "__main__":
    main()
