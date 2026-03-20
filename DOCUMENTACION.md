# Documentación Técnica — HUB de datos HTTP — Traductor Rusertech ® v2.1

## Arquitectura

```
FUENTES → HUB → DESTINOS

Modo activo:  Planificador → ingestores/control_group.py → normalizar → despachar
Modo pasivo:  POST /ingresar/{proveedor} → normalizar → despachar
Cola:         Si falla → cola/pendientes_*.json → reintento próximo ciclo
```

---

## Instalación local

```bash
# Clonar el repositorio
git clone https://github.com/Gustavo1986-2015/HUB_Integraci-n_Datos_HTTP
cd HUB_Integraci-n_Datos_HTTP

# Instalar dependencias
pip install -r requirements.txt

# Configurar
cp .env.example.new .env
# Editar .env con los valores reales

# Ejecutar con GUI
python hub_gui.py

# O ejecutar sin GUI
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

---

## Compilar el ejecutable (.exe)

El `.exe` debe quedar en la raíz del proyecto, junto al `.env`:

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --icon=hub_icon.ico --distpath . --name "HubSatelital" hub_gui.py
```

La carpeta `build/` se puede borrar después. El `.spec` también.

---

## Variables de entorno (.env)

### General

| Variable | Default | Descripción |
|---|---|---|
| `PORT` | `8000` | Puerto del servidor (Railway lo inyecta automáticamente) |
| `LOG_LEVEL` | `INFO` | INFO / DEBUG / WARNING / ERROR |
| `LOG_RETENTION_HOURS` | `48` | Horas de retención de archivos de log |
| `COLA_MAX_HORAS` | `24` | Horas máximas de espera en la cola de reintentos |
| `DRY_RUN` | `false` | `true` = simular sin enviar |

### Seguridad

| Variable | Descripción |
|---|---|
| `HUB_INGEST_TOKEN` | Bearer token para `POST /ingresar/{proveedor}`. Vacío = sin autenticación |
| `CONFIG_USUARIO` | Usuario para el login de la GUI y la UI web `/configuracion` |
| `CONFIG_CLAVE` | Contraseña del login |

### Recurso Confiable

| Variable | Descripción |
|---|---|
| `SEND_TO_RECURSO_CONFIABLE` | `true` / `false` |
| `RC_SOAP_URL` | `http://gps.rcontrol.com.mx/Tracking/wcf/RCService.svc` |
| `RC_USER_ID` | Usuario de RC |
| `RC_PASSWORD` | Contraseña de RC |
| `RC_TIMEZONE_OFFSET` | `+00:00` — RC requiere UTC |

### Simon 4.0

| Variable | Descripción |
|---|---|
| `SEND_TO_SIMON` | `true` / `false` |
| `SIMON_BASE_URL` | URL base: `https://simon-pre-webapi.assistcargo.com/ReceiveAvlRecords` |
| `SIMON_INTEGRATION_KEY` | Clave de integración — se agrega como `?rpaIntegrationKey=...` |
| `SIMON_USER_AVL` | Usuario AVL dentro de Simon |
| `SIMON_TIMEZONE_OFFSET` | `-03:00` — Simon requiere hora local Argentina |

### Control Group

| Variable | Descripción |
|---|---|
| `CONTROL_GROUP_ENABLED` | `true` / `false` |
| `CONTROL_GROUP_URL` | `https://gateway.control-group.com.ar/gateway.asp` |
| `CONTROL_GROUP_USER` | Usuario del gateway |
| `CONTROL_GROUP_PASS` | Contraseña del gateway |
| `CONTROL_GROUP_INTERVAL` | Segundos entre consultas (mínimo recomendado: 60) |

### Routing

| Variable | Valores posibles | Descripción |
|---|---|---|
| `DESTINOS_CONTROL_GROUP` | `recurso_confiable` / `simon` / `recurso_confiable,simon` | A dónde van los datos de CG |
| `DESTINOS_{NOMBRE}` | idem | A dónde van los datos del proveedor pasivo `{nombre}` |
| `DESTINOS_DEFAULT` | idem | Fallback para proveedores sin configuración específica |

---

## Endpoints

### POST /ingresar/{proveedor}

Recibe eventos GPS de un prestador en modo pasivo.

**Autenticación:** `Authorization: Bearer {HUB_INGEST_TOKEN}` (opcional si la variable está vacía)

**Body:** JSON — objeto o lista de objetos con campos AVL

```json
{
  "placa": "ABC123",
  "latitud": -34.54113,
  "longitud": -58.47998,
  "velocidad": "60",
  "fecha": "2024-03-15T10:30:00",
  "codigo_evento": "1"
}
```

**Respuesta:** `202 Accepted` — el procesamiento ocurre en segundo plano.

### GET /metricas

Métricas en tiempo real. Consumido por la GUI y el dashboard cada 5s.

### GET /estado

Health check. Retorna estado del Hub, ingestores activos y cola de pendientes.

### GET /dashboard

Panel de monitoreo visual (navegador).

### GET /configuracion

UI de configuración web (requiere HTTP Basic Auth con CONFIG_USUARIO/CONFIG_CLAVE).

---

## Cola de reintentos

Si un envío a RC o Simon falla:
1. Los registros se guardan en `cola/pendientes_{destino}.json`
2. En el próximo ciclo, el Hub reintenta **antes** de procesar datos nuevos
3. Si el reintento es exitoso, el archivo de cola se elimina
4. Si los registros tienen más de `COLA_MAX_HORAS` horas, se descartan

El archivo de cola persiste en disco aunque el Hub se reinicie.

---

## Control Group — Protocolo XML

El gateway devuelve una estructura dinámica:

```xml
<r cantidad="N" zonaHoraria="-03:00">
  <columnas>
    <i id="A" nombre="idRastreable" predeterminado="123456"/>
    <i id="C" nombre="nombre" predeterminado="VJV-247"/>
    <i id="D" nombre="fecha"/>
    <i id="J" nombre="latitud"/>
    <i id="K" nombre="longitud"/>
  </columnas>
  <filas>
    <i C="ABC123" D="2024-01-15 10:30:00" J="-34.54" K="-58.47"/>
  </filas>
</r>
```

El ingestor construye un diccionario `{id_letra: {nombre, predeterminado}}` con las columnas, y lo usa para resolver cada fila. Si la fila no trae un campo, se aplica el predeterminado del diccionario.

---

## Simon 4.0 — Protocolo REST/JSON

**Endpoint:** `POST /ReceiveAvlRecords?rpaIntegrationKey={SIMON_INTEGRATION_KEY}`

**Cuerpo:** lista JSON (siempre, aunque sea un solo registro)

```json
[
  {
    "Asset": "ABC123",
    "Latitude": -34.54113,
    "Longitude": -58.47998,
    "Speed": "60",
    "Date": "2024-03-15T10:30:00-03:00",
    "Code": "1",
    "User_avl": "Rusertech"
  }
]
```

Las fechas se envían en hora local Argentina (`-03:00`), no en UTC.

---

## Recurso Confiable — Protocolo SOAP/XML

Protocolo D-TI-15 v14. Envío en batch (todos los registros en un envelope).

- URL: `http://` (sin SSL) — `http://gps.rcontrol.com.mx/Tracking/wcf/RCService.svc`
- Token de sesión automático: se renueva 30 min antes de vencer
- Retorna un `idJob` por envío para trazabilidad

---

## Agregar un nuevo proveedor pasivo

1. Abrir la GUI → Configuración → **Proveedores pasivos** → `+ Agregar`
2. Nombre: el que usará en la URL (ej: `samsara`)
3. Destino: elegir a dónde ir sus datos
4. Guardar → Detener y Reiniciar el Hub
5. El prestador debe hacer `POST http://tu-servidor:8000/ingresar/samsara`

---

## Agregar un nuevo ingestor activo

Por ahora solo Control Group está implementado como ingestor activo. Para agregar otro:
1. Crear `services/ingestores/mi_proveedor.py` extendiendo `IngestorBase`
2. Implementar `nombre` y `consultar()`
3. Registrar en `main.py` dentro del lifespan
4. Agregar sus variables al `.env`

---

## Deploy en Railway

Ver [RAILWAY_VARIABLES.md](RAILWAY_VARIABLES.md) para el paso a paso completo.

---

## Recibir datos en local desde Internet (ngrok)

Para que un prestador AVL externo pueda enviarte datos mientras desarrollás en local, necesitás exponer tu Hub a Internet. La herramienta más simple es **ngrok**.

### Instalar ngrok (Windows)

```powershell
# Opción 1 — winget
winget install ngrok

# Opción 2 — descargar .exe desde https://ngrok.com/download
```

### Exponer el Hub local

Con el Hub corriendo en el puerto 8000, en otra terminal:

```bash
ngrok http 8000
```

ngrok muestra algo así:

```
Forwarding  https://abc123.ngrok-free.app -> http://localhost:8000
```

### URL que le das al prestador AVL

```
POST https://abc123.ngrok-free.app/ingresar/{nombre_proveedor}
Authorization: Bearer {HUB_INGEST_TOKEN}
Content-Type: application/json
```

El prestador envía datos a esa URL pública → ngrok los reenvía al Hub local → el Hub los procesa normalmente.

### Importante

- La URL de ngrok **cambia** cada vez que lo reiniciás (plan gratuito)
- Para URL fija: usar ngrok con dominio estático (plan pago) o deployar en Railway
- El Hub en local debe estar corriendo **antes** de que llegue cualquier dato
- El token `HUB_INGEST_TOKEN` aplica igual que en producción
