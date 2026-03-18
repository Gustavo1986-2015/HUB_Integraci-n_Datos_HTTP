# Hub de Integración Satelital — Documentación

## Índice

1. [¿Qué es este Hub?](#1-qué-es-este-hub)
2. [Estructura del proyecto](#2-estructura-del-proyecto)
3. [Instalación local](#3-instalación-local)
4. [Variables de entorno (.env)](#4-variables-de-entorno-env)
5. [Routing — quién va a dónde](#5-routing--quién-va-a-dónde)
6. [Endpoints disponibles](#6-endpoints-disponibles)
7. [Modo Pasivo — el prestador nos envía datos](#7-modo-pasivo--el-prestador-nos-envía-datos)
8. [Modo Activo — nosotros consultamos la API](#8-modo-activo--nosotros-consultamos-la-api)
9. [El modelo RegistroAVL](#9-el-modelo-registroavl)
10. [Limpieza de placas](#10-limpieza-de-placas)
11. [Destino A — Recurso Confiable](#11-destino-a--recurso-confiable)
12. [Destino B — Simon 4.0](#12-destino-b--simon-40)
13. [Ingestor — Control Group](#13-ingestor--control-group)
14. [Dashboard de monitoreo](#14-dashboard-de-monitoreo)
15. [UI de configuración](#15-ui-de-configuración)
16. [Logs en archivo JSON](#16-logs-en-archivo-json)
17. [Modo Prueba (sin envíos reales)](#17-modo-prueba-sin-envíos-reales)
18. [Deploy en Railway](#18-deploy-en-railway)
19. [Agregar un proveedor pasivo](#19-agregar-un-proveedor-pasivo)
20. [Agregar un ingestor activo](#20-agregar-un-ingestor-activo)
21. [Errores frecuentes](#21-errores-frecuentes)

---

## 1. ¿Qué es este Hub?

Un **enrutador inteligente de datos satelitales**. Recibe o consulta pulsos GPS
de prestadores AVL, los convierte a un modelo único y los envía a los destinos
configurados.

```
FUENTES
  ├── Prestadores que nos envían  →  POST /ingresar/{proveedor}
  └── APIs que consultamos        →  polling automático (Control Group, etc.)
                ↓
       HUB DE INTEGRACIÓN
  (normaliza, limpia, enruta, loguea, monitorea)
                ↓
DESTINOS
  ├── Recurso Confiable  →  SOAP/XML
  └── Simon 4.0          →  REST/JSON
```

**Regla fundamental:** ningún registro se descarta aunque no tenga GPS.
Un evento de pánico o alarma es valioso sin coordenadas.

---

## 2. Estructura del proyecto

```
hub_satelital/
│
├── main.py                          # Punto de entrada del servidor
├── core/
│   └── config.py                    # Lee variables del .env
│
├── services/
│   ├── estandarizador.py            # Convierte cualquier JSON → RegistroAVL
│   ├── metricas.py                  # Contadores en memoria para el dashboard
│   ├── planificador.py              # Ejecuta ingestores cada N segundos
│   ├── logger_archivo.py            # Escribe logs JSON diarios en /logs
│   ├── dashboard.html               # Panel de monitoreo visual
│   ├── configuracion.html           # UI web para configurar el Hub
│   │
│   ├── despachadores/
│   │   ├── cliente_rc.py            # Envía a Recurso Confiable (SOAP/XML)
│   │   └── cliente_simon.py         # Envía a Simon 4.0 (REST/JSON)
│   │
│   └── ingestores/
│       ├── base.py                  # Contrato mínimo para ingestores
│       └── control_group.py         # Consulta el Gateway de Control Group
│
├── logs/                            # Creada automáticamente — logs JSON diarios
├── .env                             # Configuración local (NO sube a GitHub)
├── .env.example                     # Plantilla de configuración
├── requirements.txt
├── Procfile                         # Para Railway
├── runtime.txt                      # Para Railway
└── DOCUMENTACION.md
```

---

## 3. Instalación local

```bash
# 1. Instalar dependencias
pip install -r requirements.txt

# 2. Crear configuración
cp .env.example .env
# Editar .env con tus credenciales

# 3. Levantar servidor
uvicorn main:app --reload --port 8000
```

URLs disponibles:
- **Dashboard:**     http://localhost:8000/dashboard
- **Configuración:** http://localhost:8000/configuracion
- **Estado:**        http://localhost:8000/estado

---

## 4. Variables de entorno (.env)

| Variable | Descripción | Por defecto |
|---|---|---|
| `PORT` | Puerto del servidor | `8000` |
| `LOG_LEVEL` | DEBUG, INFO, WARNING, ERROR | `INFO` |
| `LOG_RETENTION_HOURS` | Horas que se conservan los logs en disco | `48` |
| `DRY_RUN` | `true` = sin envíos reales | `false` |
| `HUB_INGEST_TOKEN` | Token de seguridad (vacío = libre) | vacío |
| `TIMEZONE_OFFSET` | Offset de zona horaria para fechas | `-05:00` |
| | | |
| `SEND_TO_RECURSO_CONFIABLE` | Activar destino RC | `false` |
| `RC_SOAP_URL` | URL del servicio SOAP de RC | URL producción |
| `RC_USER_ID` | Usuario SOAP de RC | — |
| `RC_PASSWORD` | Contraseña SOAP de RC | — |
| | | |
| `SEND_TO_SIMON` | Activar destino Simon | `false` |
| `SIMON_BASE_URL` | URL base del HubReceptor Simon | — |
| `SIMON_USER_AVL` | Campo User_avl para Simon | `avl` |
| `SIMON_SOURCE_TAG` | Campo SourceTag para Simon | vacío |
| `SIMON_API_TOKEN` | Bearer token fijo de Simon | — |
| | | |
| `DESTINOS_{PROVEEDOR}` | Destinos para un proveedor específico | — |
| `DESTINOS_DEFAULT` | Destinos fallback para todos | — |
| | | |
| `CONTROL_GROUP_ENABLED` | Activar ingestor Control Group | `false` |
| `CONTROL_GROUP_URL` | URL del gateway CG | URL producción |
| `CONTROL_GROUP_USER` | Usuario del gateway | — |
| `CONTROL_GROUP_PASS` | Contraseña del gateway | — |
| `CONTROL_GROUP_INTERVAL` | Segundos entre consultas | `60` |

---

## 5. Routing — quién va a dónde

Cada proveedor puede enviar sus datos a un destino diferente. Solo variables de entorno, sin tocar código.

**Prioridad:**
```
1. DESTINOS_{NOMBRE_PROVEEDOR}  →  específico para ese proveedor
2. DESTINOS_DEFAULT             →  fallback para todos
3. SEND_TO_RC + SEND_TO_SIMON   →  modo básico
```

**Ejemplos en .env:**
```bash
DESTINOS_CONTROL_GROUP=recurso_confiable
DESTINOS_MI_PROVEEDOR=simon
DESTINOS_OTRO=recurso_confiable,simon
DESTINOS_DEFAULT=simon
```

---

## 6. Endpoints disponibles

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/ingresar/{proveedor}` | Recibir pulsos GPS |
| `GET` | `/metricas` | Métricas JSON en tiempo real |
| `GET` | `/dashboard` | Panel de monitoreo HTML |
| `GET` | `/configuracion` | UI de configuración |
| `GET` | `/configuracion/datos` | Leer .env como JSON |
| `POST` | `/configuracion/guardar` | Guardar nuevas variables en .env |
| `GET` | `/estado` | Health check |

---

## 7. Modo Pasivo — el prestador nos envía datos

El prestador configura su plataforma para enviarnos un POST:
```
POST https://tu-hub.railway.app/ingresar/{nombre_proveedor}
Content-Type: application/json
```

Acepta un evento único `{}` o un lote `[{}, {}, ...]`.

Los campos pueden estar en español o en inglés — el estandarizador los resuelve automáticamente mediante la tabla `ALIASES_CAMPOS` en `estandarizador.py`.

Para agregar soporte a un nuevo prestador: ver sección 19.

---

## 8. Modo Activo — nosotros consultamos la API

Para prestadores que no envían datos. El planificador ejecuta `consultar()` de cada ingestor en intervalos configurables.

Ingestores disponibles: **Control Group** (ver sección 13).

Para agregar un nuevo ingestor: ver sección 20.

---

## 9. El modelo RegistroAVL

Modelo interno único. Todo dato que entra se convierte a `RegistroAVL`.

| Campo | Tipo | Descripción |
|---|---|---|
| `placa` | string | Placa limpia sin caracteres especiales |
| `latitud` | float o None | Latitud decimal. None si no hay GPS |
| `longitud` | float o None | Longitud decimal. None si no hay GPS |
| `fecha` | string | ISO 8601: `YYYY-MM-DDTHH:MM:SS±HH:MM` |
| `velocidad` | string | Velocidad en km/h |
| `codigo_evento` | string | Código del evento AVL |
| `ignicion` | string | `"1"`=encendido, `"0"`=apagado |
| `temperatura` | string | Temperatura en °C |
| `bateria` | string | Nivel de batería 0-100 |
| `numero_serie` | string | Número de serie del GPS |
| `numero_viaje` | string | Número de viaje del embarcador |
| `tipo_vehiculo` | string | Tipo: Tracto, Camión, etc. |
| `marca_vehiculo` | string | Marca del vehículo |
| `modelo_vehiculo` | string | Modelo del vehículo |

---

## 10. Limpieza de placas

Todas las placas se limpian automáticamente antes de ser enviadas a cualquier destino. Función `limpiar_placa()` en `estandarizador.py`.

```
"ABC-123"  →  "ABC123"
"XYZ 456"  →  "XYZ456"
"ÑOP.789"  →  "NOP789"
"A1B 2C3"  →  "A1B2C3"
```

Se aplica tanto a datos recibidos (modo pasivo) como a datos consultados (modo activo). No requiere configuración adicional.

---

## 11. Destino A — Recurso Confiable

**Protocolo:** SOAP/XML — D-TI-15 v14
**URL:** `http://gps.rcontrol.com.mx/Tracking/wcf/RCService.svc`

Flujo: `GetUserToken` → token 24 horas (con caché automático) → `GPSAssetTracking`

Todos los registros del lote se envían en un único envelope SOAP (envío en bloque). Las fechas se envían sin offset de timezone (RC requiere UTC puro).

**Credenciales:** solicitar a soporte@recursoconfiable.com con nombre y RFC de la empresa.

---

## 12. Destino B — Simon 4.0

**Protocolo:** REST/JSON
**Endpoint:** `POST /ReceiveAvlRecords`

Simon entrega un token Bearer fijo (no expira). Se incluye en cada request como `Authorization: Bearer <SIMON_API_TOKEN>`. El body es siempre una lista JSON.

---

## 13. Ingestor — Control Group

**Protocolo:** XML sobre HTTP (NO SOAP)
**URL:** `https://gateway.control-group.com.ar/gateway.asp`

Modo INCREMENTAL: el servidor recuerda la última consulta y solo devuelve eventos nuevos.

La respuesta tiene estructura dinámica — los IDs de columna pueden cambiar. El parser construye el mapa dinámicamente en cada respuesta usando los nombres de columna (que son constantes).

Si una fila no trae el valor de la placa, se usa el **predeterminado** declarado en `<columnas>`. Si tampoco hay predeterminado, se usa el `idRastreable` como fallback.

**Configuración:**
```bash
CONTROL_GROUP_ENABLED=true
CONTROL_GROUP_USER=assist
CONTROL_GROUP_PASS=cargo
CONTROL_GROUP_INTERVAL=60
DESTINOS_CONTROL_GROUP=recurso_confiable
```

---

## 14. Dashboard de monitoreo

Disponible en: `http://localhost:8000/dashboard`

Se actualiza automáticamente cada 5 segundos.

| Sección | Contenido |
|---|---|
| Resumen General | Tiempo activo, ingestados, despachados OK/fallidos |
| Estado de Destinos | Por destino: enviados, fallidos, tasa de éxito |
| Proveedores AVL | Por proveedor: recibidos, normalizados, placas recientes |
| Log de Actividad | Últimas 200 entradas en tiempo real |

---

## 15. UI de configuración

Disponible en: `http://localhost:8000/configuracion`

Permite configurar el Hub sin editar el `.env` manualmente.

Secciones:
- **General:** modo prueba, logs, seguridad
- **Destinos:** RC y Simon con sus credenciales
- **APIs:** ingestores activos y sus credenciales
- **Routing:** a qué destino van los datos de cada proveedor

El botón **Guardar** escribe el `.env` directamente. El servidor debe reiniciarse para aplicar los cambios.

---

## 16. Logs en archivo JSON

El Hub genera un archivo de log por día en la carpeta `logs/`:
```
logs/hub_2026-03-18.json
```

Cada línea es un evento JSON independiente (formato JSONL):
```json
{"timestamp": "2026-03-18T09:44:11", "tipo": "ingesta", "proveedor": "control_group", "modo": "activo", "cantidad": 680, "placas": ["ABC123", "XYZ456"]}
{"timestamp": "2026-03-18T09:44:12", "tipo": "despacho", "proveedor": "control_group", "destino": "recurso_confiable", "cantidad": 680, "resultado": "exitoso", "id_trabajo": "1773834271061"}
```

**Retención:** configurable con `LOG_RETENTION_HOURS` en `.env` (por defecto 48 horas). Los archivos más viejos se eliminan automáticamente al arrancar el servidor.

---

## 17. Modo Prueba (sin envíos reales)

```bash
DRY_RUN=true
```

Con esto activo: normaliza, loguea, registra métricas y escribe logs de archivo, pero **no realiza ninguna llamada HTTP** a RC ni Simon. El dashboard muestra todo como si hubiera envíos reales.

---

## 18. Deploy en Railway

1. Subir el proyecto a GitHub
2. En [railway.app](https://railway.app): **New Project → Deploy from GitHub**
3. En **Variables**, cargar cada variable del `.env`
4. Railway detecta el `Procfile` y despliega automáticamente

Railway inyecta `PORT` automáticamente.

---

## 19. Agregar un proveedor pasivo

Para prestadores que **nos envían** sus datos:

**Paso 1 — Identificar campos del prestador**
```json
{"patente": "ABC123", "lat": -34.6, "lng": -58.4, "vel": 60}
```

**Paso 2 — Agregar aliases en `services/estandarizador.py`**
```python
ALIASES_CAMPOS = {
    "placa":    [..., "patente"],
    "latitud":  [..., "lat"],
    "longitud": [..., "lng"],
    "velocidad":[..., "vel"],
}
```

**Paso 3 — Configurar destino en `.env`**
```bash
DESTINOS_NOMBRE_PROVEEDOR=simon
```

**Paso 4 — Dar URL al prestador**
```
POST https://tu-hub.railway.app/ingresar/nombre_proveedor
```

No se crea ningún archivo de código nuevo.

---

## 20. Agregar un ingestor activo

Para prestadores cuya API **consultamos nosotros**:

**Paso 1 — Crear `services/ingestores/nombre_proveedor.py`**
```python
from services.ingestores.base import IngestorBase
from services.estandarizador import RegistroAVL, limpiar_placa

class IngestorNombreProveedor(IngestorBase):

    @property
    def nombre(self) -> str:
        return "nombre_proveedor"

    async def consultar(self) -> list[RegistroAVL]:
        # 1. Llamar a la API
        # 2. Parsear respuesta
        # 3. Limpiar placa con limpiar_placa()
        # 4. Retornar lista de RegistroAVL
        # NUNCA descartar registros por falta de GPS
        ...
```

**Paso 2 — Agregar variables en `core/config.py` dentro de `__init__`**
```python
self.NUEVO_ACTIVO: bool = os.getenv("NUEVO_ENABLED", "false").lower() == "true"
self.NUEVO_URL: str = os.getenv("NUEVO_URL", "")
self.NUEVO_USUARIO: str = os.getenv("NUEVO_USER", "")
self.NUEVO_CLAVE: str = os.getenv("NUEVO_PASS", "")
self.NUEVO_INTERVALO: int = int(os.getenv("NUEVO_INTERVAL", "60"))
```

**Paso 3 — Registrar en `main.py` dentro del lifespan**
```python
if config.NUEVO_ACTIVO:
    from services.ingestores.nombre_proveedor import IngestorNombreProveedor
    planificador.registrar(
        IngestorNombreProveedor(config.NUEVO_URL, config.NUEVO_USUARIO, config.NUEVO_CLAVE),
        config.NUEVO_INTERVALO
    )
```

**Paso 4 — Configurar en `.env`**
```bash
NUEVO_ENABLED=true
NUEVO_URL=https://api.proveedor.com
NUEVO_USER=usuario
NUEVO_PASS=clave
NUEVO_INTERVAL=60
DESTINOS_NOMBRE_PROVEEDOR=simon
```

---

## 21. Errores frecuentes

| Error en logs | Causa | Solución |
|---|---|---|
| `401` en `/ingresar` | Token de seguridad incorrecto | Verificar `HUB_INGEST_TOKEN` o vaciarlo |
| `400` en `/ingresar` | JSON inválido | Verificar Content-Type y estructura |
| `RC Autenticación fallida` | Credenciales RC incorrectas | Verificar `RC_USER_ID` y `RC_PASSWORD` |
| `RC HTTP 404` | URL con https en vez de http | Usar `http://gps.rcontrol.com.mx/...` |
| `Simon HTTP 401` | Token Simon incorrecto | Verificar `SIMON_API_TOKEN` |
| `CG Error al parsear XML` | Credenciales CG inválidas | Verificar `CONTROL_GROUP_USER` y `CONTROL_GROUP_PASS` |
| `CONTROL_GROUP_ENABLED=false` | `.env` no encontrado | Crear `.env` con `cp .env.example .env` |
| `DRY_RUN activo en producción` | Variable no actualizada | En Railway → Variables → `DRY_RUN=false` |
| `LOG_RETENTION_HOURS not found` | Variable faltante en config.py | Agregar `self.LOG_RETENTION_HOURS` en `__init__` |
