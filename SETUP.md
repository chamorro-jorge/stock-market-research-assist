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

## 1. CLI de Databricks (opcional)

**No hace falta para nada de lo que viene abajo**: todo se puede hacer desde un notebook
del workspace. Instálala solo si prefieres trabajar desde el portátil.

```powershell
winget install Databricks.DatabricksCLI
```

Si la usas, autentícate contra tu workspace:

```powershell
databricks --version          # necesitas v0.2xx o superior
databricks auth login --host https://dbc-2e2ed7f0-26e7.cloud.databricks.com
```

Se abre el navegador, aceptas, y queda un perfil guardado. Verifica:

```powershell
databricks current-user me
```

---

## 2. Crear los secretos (la vía fácil: sin instalar nada)

Abre un notebook en tu carpeta git del workspace y ejecuta:

```python
%pip install databricks-sdk --upgrade
%run ./scripts/setup_secrets.py
```

Aparecen dos widgets arriba del notebook. Pega en ellos:

| Widget | Valor |
|---|---|
| `massive_api-key` | Tu API key de Massive |
| `database_lakebase-url` | `postgresql://ROL:PASS@HOST:5432/databricks_postgres?sslmode=require` |

Vuelve a ejecutar la celda. El script crea los scopes `massive` y `database`, guarda los
valores y da permiso de lectura al grupo `users` para que el job y la app puedan leerlos.

**Después, borra los widgets**: menú del notebook -> *Remove all widgets*. Si no, los
valores quedan visibles en el notebook.

> **Si alguna vez has pegado una clave en un chat, un correo o una captura, rótala antes
> de usarla aquí.**

### De dónde sale la URL de Lakebase

1. Entra en tu proyecto de Lakebase:
   <https://dbc-2e2ed7f0-26e7.cloud.databricks.com/lakebase/projects/0301d7d2-6972-4cce-a45a-4c3c80734d04>
2. Busca la sección de conexión de `bootcamp-database`.
3. Necesitas un **rol de Postgres con contraseña estática**, no un token OAuth: el job corre
   desatendido y un token caducaría.
4. Copia la contraseña en cuanto se muestre; normalmente no se puede volver a ver.
5. Si la contraseña lleva `@`, `/`, `:` o `#`, escápalos en porcentaje (`@` es `%40`) o la
   URL se rompe.

---

## 3. Alternativa: con la CLI de Databricks

Solo si prefieres hacerlo desde tu portátil. Requiere instalar la CLI:

```powershell
winget install Databricks.DatabricksCLI
databricks auth login --host https://dbc-2e2ed7f0-26e7.cloud.databricks.com
python scripts/setup_secrets.py
```

O a mano:

```powershell
databricks secrets create-scope massive
databricks secrets put-secret massive api-key
databricks secrets create-scope database
databricks secrets put-secret database lakebase-url
```

El editor que se abre espera **solo el valor**: sin comillas, sin `MASSIVE_API_KEY=` delante
y sin salto de línea al final. Un salto de línea de más es la causa habitual de un 401
que parece inexplicable.

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
