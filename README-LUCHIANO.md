# Garmin Coach MCP seguro para Luciano

Esta variante mantiene `server.py` como servidor funcional original y coloca
`secure_server.py` delante de él. El despliegue de Railway arranca la capa segura,
que aplica autenticación al transporte MCP y desactiva por defecto las herramientas
que escriben en Garmin.

## Arquitectura

```text
ChatGPT
  |  HTTPS + Authorization: Bearer <MCP_API_TOKEN>
  v
Railway / secure_server.py
  |-- /health              publico para el health check
  |-- /mcp y /mcp/*        autenticacion Bearer obligatoria
  |-- filtro read-only     oculta y rechaza tools mutativas
  v
server.py / FastMCP 3.2.4
  v
garminconnect 0.3.11 -> Garmin Connect

/data -> tokens y configuracion persistentes del servicio
```

`secure_server.py` importa el objeto `mcp` ya definido en `server.py`; no duplica
las herramientas ni cambia su lógica. Antes de importar el servidor aplica los
valores recomendados para Chile. Las variables definidas explícitamente en Railway
siempre tienen prioridad.

## Seguridad

- `/mcp` y cualquier subruta `/mcp/*` requieren exactamente un encabezado
  `Authorization: Bearer <token>`.
- El token se compara con `secrets.compare_digest`.
- Si `MCP_API_TOKEN` falta, está vacío o contiene solo espacios, MCP queda bloqueado
  con HTTP `401`; no existe modo anónimo.
- `/health` es público para que Railway pueda comprobar el servicio.
- `MCP_READ_ONLY=1` está activo por defecto. Las herramientas mutativas no aparecen
  en el catálogo y FastMCP rechaza también una llamada directa.
- El servidor no necesita `GARMIN_EMAIL` ni `GARMIN_PASSWORD` permanentes. El email,
  la contraseña y el MFA solo se usan durante el login para generar tokens.
- `GARMIN_TOKENS_JSON`, `MCP_API_TOKEN`, `ADMIN_TOKEN` y `RAILWAY_API_TOKEN` son
  secretos. No deben guardarse en Git ni pegarse en logs, issues o capturas.

La autenticación Bearer descrita aquí cubre el endpoint MCP. `server.py` conserva
sus rutas web originales (panel, login y utilidades); configura también un
`ADMIN_TOKEN` largo para proteger el panel y el asistente una vez terminado el
primer login.

## Variables de Railway

Configura estas variables en **Railway -> Service -> Variables**:

| Variable | Valor recomendado | Uso |
|---|---:|---|
| `MCP_API_TOKEN` | secreto aleatorio largo | Obligatorio; autoriza `/mcp` |
| `MCP_READ_ONLY` | `1` | Bloquea escrituras en Garmin |
| `GARMIN_TIMEZONE` | `America/Santiago` | Zona horaria chilena |
| `GARMIN_LANGUAGE` | `es` | Salida en español |
| `CACHE_MINUTES` | `10` | Vigencia del caché |
| `ACTIVITY_LIMIT` | `20` | Actividades incluidas en el caché |
| `AUTO_SYNC_TOKENS` | `1` | Sincroniza tokens rotados a Railway |
| `AUTO_SYNC_INTERVAL_SECONDS` | `43200` | Sincronización cada 12 horas |
| `GARMIN_TOKENS_JSON` | generado por el login | Token Garmin; nunca usar credenciales aquí |
| `ADMIN_TOKEN` | otro secreto aleatorio largo | Protege el panel/login web |
| `RAILWAY_API_TOKEN` | token de Railway | Opcional; permite persistencia y auto-sync |

Railway inyecta automáticamente `RAILWAY_PROJECT_ID`,
`RAILWAY_ENVIRONMENT_ID` y `RAILWAY_SERVICE_ID`. El volumen permanece montado en
`/data` mediante `railway.toml`.

Genera secretos independientes, por ejemplo:

```bash
openssl rand -hex 32
```

No reutilices la contraseña de Garmin como `MCP_API_TOKEN` ni como `ADMIN_TOKEN`.

## Despliegue en Railway

1. Conecta este repositorio y la rama `main` a un servicio Railway.
2. Railway detectará `railway.toml` y construirá el `Dockerfile` con
   `python:3.12-slim`.
3. Confirma que el volumen persistente esté montado en `/data`.
4. Crea primero `MCP_API_TOKEN` y las variables recomendadas de la tabla.
5. Genera un dominio público para el servicio.
6. Comprueba `https://TU-DOMINIO/health`; debe responder sin Bearer.
7. Comprueba que `https://TU-DOMINIO/mcp` responda `401` sin Bearer.

El contenedor copia `server.py` y `secure_server.py`, e inicia:

```text
python secure_server.py
```

## Login de Garmin y persistencia de tokens

No configures `GARMIN_EMAIL` ni `GARMIN_PASSWORD` en Railway.

Hay dos formas de generar los tokens:

### Asistente web existente

1. Abre `https://TU-DOMINIO/login`.
2. Introduce email, contraseña y el código MFA de Garmin cuando se solicite.
3. El asistente genera `garmin_tokens.json` y lo guarda en el volumen `/data`.
4. Si configuraste `RAILWAY_API_TOKEN`, el asistente puede guardar también
   `GARMIN_TOKENS_JSON` en Railway para recuperación y sincronización.
5. Configura un `ADMIN_TOKEN` largo y conserva las credenciales solo en tu gestor
   de contraseñas.

### Login local

Con Python 3.12 y las dependencias instaladas:

```bash
python login_once.py
```

El script solicita las credenciales de forma interactiva, genera
`~/.garminconnect/garmin_tokens.json` y muestra el JSON que puede guardarse como
variable secreta `GARMIN_TOKENS_JSON`. No guardes ese JSON en archivos versionados.

## Conectar ChatGPT a `/mcp`

Usa esta URL como endpoint del conector:

```text
https://TU-DOMINIO.up.railway.app/mcp
```

Configura la autenticación Bearer del conector con el valor de `MCP_API_TOKEN`.
La petición debe incluir:

```http
Authorization: Bearer <MCP_API_TOKEN>
```

Prueba manual mínima:

```bash
curl -i https://TU-DOMINIO.up.railway.app/mcp
curl -i -H "Authorization: Bearer TU_TOKEN" \
  https://TU-DOMINIO.up.railway.app/mcp
```

La primera llamada debe devolver `401`. La segunda debe atravesar la capa de
autenticación; una petición GET simple puede recibir una respuesta del protocolo
distinta de `200`, pero no debe recibir `401` por token inválido.

## Modo solo lectura

Con `MCP_READ_ONLY=1` quedan bloqueadas estas herramientas auditadas:

- `add_weigh_in`
- `delete_weigh_in`
- `delete_weigh_ins`
- `schedule_workout`
- `set_gear_default`
- `unschedule_workout`
- `upload_activity`

Las herramientas `get_*`, las descargas y la actualización del caché siguen
disponibles. `refresh_snapshot` vuelve a consultar datos, pero no modifica datos de
la cuenta Garmin.

## Habilitar escritura en el futuro

Solo si aceptas que ChatGPT pueda modificar la cuenta Garmin:

1. Cambia `MCP_READ_ONLY` a `0` en Railway.
2. Redespliega o reinicia el servicio; la visibilidad se decide al arrancar.
3. Verifica el catálogo de herramientas y realiza primero una operación de bajo
   impacto.

Para volver al modo seguro, restaura `MCP_READ_ONLY=1` y redespliega.

## Rotar `MCP_API_TOKEN`

1. Genera un token aleatorio nuevo.
2. Sustituye `MCP_API_TOKEN` en Railway y redespliega el servicio.
3. Actualiza el secreto Bearer del conector de ChatGPT.
4. Confirma que el token nuevo entra y que el antiguo recibe `401`.
5. Elimina cualquier copia temporal del token anterior.

La rotación invalida el token anterior en cuanto el proceso de Railway arranca con
la nueva variable.
