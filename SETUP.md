# SETUP — Credenciales y conexión

Todo lo que tienes que hacer **tú** una vez, antes de que el job y la app puedan arrancar.
Ningún valor de los que introduzcas aquí se guarda en el repositorio.

Datos de este proyecto:

| Cosa | Valor |
|---|---|
| Workspace | `https://dbc-2e2ed7f0-26e7.cloud.databricks.com` |
| Lakebase (proyecto) | `0301d7d2-6972-4cce-a45a-4c3c80734d04` |
| Base de datos | `bootcamp-database` |

---

## 1. CLI de Databricks

Comprueba que la tienes y que apunta a tu workspace:

```powershell
databricks --version          # necesitas v0.2xx o superior
databricks auth login --host https://dbc-2e2ed7f0-26e7.cloud.databricks.com
```

Se abre el navegador, aceptas, y queda un perfil guardado. Verifica:

```powershell
databricks current-user me
```

---

## 2. Clave de la API de Massive

Si aún no tienes clave: date de alta en el plan gratuito de Massive y copia la API key
desde su panel.

> **Si alguna vez has pegado una clave en un chat, un correo o una captura, rótala antes
> de usarla aquí.**

Crea el scope y mete la clave:

```powershell
databricks secrets create-scope massive
databricks secrets put-secret massive api-key
```

El segundo comando abre un editor. Pega **solo la clave**, sin comillas, sin `MASSIVE_API_KEY=`
delante y sin espacios ni línea en blanco al final. Guarda y cierra.

> Si prefieres evitar el editor:
> `databricks secrets put-secret massive api-key --string-value "TU_CLAVE"`
> Ojo: así queda en el historial de PowerShell. Bórralo después con `Clear-History`.

---

## 3. URL de conexión a Lakebase

Necesitas una URL de Postgres estándar. Se saca del propio Lakebase:

1. Entra en tu proyecto de Lakebase:
   <https://dbc-2e2ed7f0-26e7.cloud.databricks.com/lakebase/projects/0301d7d2-6972-4cce-a45a-4c3c80734d04>
2. Busca la sección de **conexión** / *Connect* de `bootcamp-database`.
3. Crea o localiza un **rol de Postgres con contraseña estática**. Es el mismo tipo de rol
   que usaste en el día 2; un token OAuth no sirve aquí porque caduca y el job corre solo.
4. Copia la contraseña en cuanto se muestre: normalmente no se puede volver a ver.

Monta la URL con esta forma:

```
postgresql://ROL:CONTRASEÑA@HOST:5432/databricks_postgres?sslmode=require
```

Si la contraseña lleva caracteres raros (`@`, `/`, `:`, `#`), hay que escaparlos en
porcentaje o la URL se rompe. Por ejemplo `@` se escribe `%40`.

Guárdala como secreto:

```powershell
databricks secrets create-scope database
databricks secrets put-secret database lakebase-url
```

---

## 4. Comprobar que ha quedado bien

```powershell
databricks secrets list-scopes
databricks secrets list-secrets massive
databricks secrets list-secrets database
```

Deben aparecer los scopes `massive` y `database`, con las claves `api-key` y `lakebase-url`.
El valor no se puede leer desde la CLI: es lo normal y lo deseable.

---

## 5. Crear las tablas

Con la URL ya en el secreto, se ejecuta el esquema una vez. Desde un notebook del workspace
o con `psql`:

```powershell
psql "postgresql://ROL:CONTRASEÑA@HOST:5432/databricks_postgres?sslmode=require" -f sql/schema.sql
```

Si no tienes `psql` instalado, pega el contenido de `sql/schema.sql` en el editor SQL de
Lakebase y ejecútalo. Es idempotente: se puede lanzar varias veces sin romper nada.

---

## 6. Desarrollo local (opcional)

Solo si quieres ejecutar cosas desde tu portátil sin pasar por Databricks:

```powershell
copy .env.example .env
notepad .env
```

`.env` está en `.gitignore` y nunca se sube. En Databricks no hace falta: allí los valores
salen de los secret scopes.

---

## Resumen de lo que necesita el código

| Scope | Clave | Contenido | Lo usa |
|---|---|---|---|
| `massive` | `api-key` | La API key de Massive | `lib/massive_client.py` |
| `database` | `lakebase-url` | URL Postgres completa | `lib/lakebase.py` |
