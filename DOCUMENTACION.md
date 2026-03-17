# Hub de Integración Satelital — Documentación

## Índice

1. [¿Qué es este Hub?](#1-qué-es-este-hub)
2. [Estructura del proyecto](#2-estructura-del-proyecto)
3. [Instalación local](#3-instalación-local)
4. [Variables de entorno](#4-variables-de-entorno)
5. [Cómo elegir el destino por proveedor](#5-cómo-elegir-el-destino-por-proveedor)
6. [Endpoints disponibles](#6-endpoints-disponibles)
7. [Modo Pasivo — El prestador nos envía datos](#7-modo-pasivo--el-prestador-nos-envía-datos)
8. [Modo Activo — Nosotros consultamos la API](#8-modo-activo--nosotros-consultamos-la-api)
9. [El modelo RegistroAVL](#9-el-modelo-registroavl)
10. [Destino A — Recurso Confiable](#10-destino-a--recurso-confiable)
11. [Destino B — Simon 4.0](#11-destino-b--simon-40)
12. [Ingestor — Control Group](#12-ingestor--control-group)
13. [Dashboard de monitoreo](#13-dashboard-de-monitoreo)
14. [Modo Prueba (sin envíos reales)](#14-modo-prueba-sin-envíos-reales)
15. [Deploy en Railway](#15-deploy-en-railway)
16. [Agregar un proveedor que nos envía datos](#16-agregar-un-proveedor-que-nos-envía-datos)
17. [Agregar un ingestor activo nuevo](#17-agregar-un-ingestor-activo-nuevo)
18. [Errores frecuentes](#18-errores-frecuentes)

---

## 1. ¿Qué es este Hub?

Es un **enrutador inteligente de datos satelitales**. Recibe o consulta pulsos GPS de prestadores AVL, los convierte a un formato único y los envía a los destinos configurados.

```
FUENTES (de donde vienen los datos)
    ├── Prestadores que nos envían  →  POST /ingresar/{proveedor}
    └── APIs que consultamos        →  polling automático (Control Group, etc.)
                  ↓
         HUB DE INTEGRACIÓN
    (normaliza, enruta, monitorea)
                  ↓
DESTINOS (a donde van los datos)
    ├── Recurso Confiable  →  protocolo SOAP/XML
    └── Simon 4.0          →  protocolo REST/JSON
```

**Lo que hace que sea un Hub y no un proxy simple:**
- **Normaliza** — convierte cualquier formato de entrada al modelo RegistroAVL
- **Enruta** — cada proveedor puede ir a un destino diferente según configuración
- **No descarta** — ningún registro se pierde, aunque le falte posición GPS
- **Monitorea** — dashboard con métricas en tiempo real
- **Es extensible** — agregar un nuevo proveedor no cambia nada del código existente

---

## 2. Estructura del proyecto

```
hub_satelital/
│
├── main.py                              # Punto de entrada — servidor FastAPI
│
├── core/
│   └── config.py                        # Toda la configuración del Hub
│                                        # Lee variables de entorno (.env)
│
├── services/
│   ├── estandarizador.py                # Convierte cualquier JSON → RegistroAVL
│   ├── metricas.py                      # Contadores en memoria para el dashboard
│   ├── planificador.py                  # Ejecuta ingestores activos cada N segundos
│   ├── dashboard.html                   # Panel de monitoreo (servido por el Hub)
│   │
│   ├── despachadores/                   # Envían datos a los destinos finales
│   │   ├── cliente_rc.py                # → Recurso Confiable (SOAP/XML)
│   │   └── cliente_simon.py             # → Simon 4.0 (REST/JSON)
│   │
│   └── ingestores/                      # Consultan APIs de prestadores externos
│       ├── base.py                      # Contrato que todo ingestor debe cumplir
│       └── control_group.py             # Control Group Gateway (XML sobre HTTP)
│
├── requirements.txt                     # Dependencias Python
├── Procfile                             # Comando de arranque para Railway
├── runtime.txt                          # Versión de Python requerida
├── .env.example                         # Plantilla de variables de entorno
├── test_local.sh                        # Script de pruebas automáticas
└── DOCUMENTACION.md                     # Este archivo
```

---

## 3. Instalación local

```bash
# 1. Entrar a la carpeta del proyecto
cd hub_satelital

# 2. Instalar dependencias (sin entorno virtual)
pip install -r requirements.txt

# 3. Crear el archivo de configuración
cp .env.example .env
# Abrir .env y editar los valores según tu entorno

# 4. Levantar el servidor
uvicorn main:app --reload --port 8000
```

Una vez iniciado, el Hub estará disponible en:
- **Dashboard:**     http://localhost:8000/dashboard
- **Documentación:** http://localhost:8000/docs
- **Estado:**        http://localhost:8000/estado

**Para pruebas sin enviar datos reales**, setear en `.env`:
```
DRY_RUN=true
```

---

## 4. Variables de entorno

| Variable | Descripción | Valor por defecto |
|---|---|---|
| `PORT` | Puerto del servidor | `8000` |
| `LOG_LEVEL` | Detalle de logs: DEBUG, INFO, WARNING, ERROR | `INFO` |
| `DRY_RUN` | `true` = sin envíos reales | `false` |
| `HUB_INGEST_TOKEN` | Token que los prestadores usan para autenticarse | vacío (libre) |
| `TIMEZONE_OFFSET` | Offset de zona horaria para fechas | `-05:00` |
| | | |
| `SEND_TO_RECURSO_CONFIABLE` | Activar destino RC (modo básico) | `false` |
| `RC_SOAP_URL` | URL del servicio SOAP de RC | URL de producción |
| `RC_USER_ID` | Usuario SOAP de Recurso Confiable | — |
| `RC_PASSWORD` | Contraseña SOAP de Recurso Confiable | — |
| | | |
| `SEND_TO_SIMON` | Activar destino Simon (modo básico) | `false` |
| `SIMON_BASE_URL` | URL base del HubReceptor Simon | — |
| `SIMON_USER_AVL` | Campo User_avl para Simon | `avl` |
| `SIMON_SOURCE_TAG` | Campo SourceTag para Simon | vacío |
| `SIMON_API_TOKEN` | Token Bearer fijo de Simon (no expira) | — |
| | | |
| `DESTINOS_{PROVEEDOR}` | Destinos para un proveedor específico | — |
| `DESTINOS_DEFAULT` | Destinos fallback para todos | — |
| | | |
| `CONTROL_GROUP_ENABLED` | Activar ingestor Control Group | `false` |
| `CONTROL_GROUP_URL` | URL del gateway de Control Group | URL de producción |
| `CONTROL_GROUP_USER` | Usuario del gateway | — |
| `CONTROL_GROUP_PASS` | Contraseña del gateway | — |
| `CONTROL_GROUP_INTERVAL` | Segundos entre consultas | `60` |

---

## 5. Cómo elegir el destino por proveedor

Cada proveedor puede enviar sus datos a un destino diferente, sin tocar código.

**Sistema de prioridad (de mayor a menor):**
```
1. DESTINOS_{NOMBRE_PROVEEDOR}  →  específico para ese proveedor
2. DESTINOS_DEFAULT             →  para todos los que no tengan uno específico
3. SEND_TO_RECURSO_CONFIABLE + SEND_TO_SIMON  →  modo básico
```

**Ejemplos en `.env`:**
```bash
# Control Group va solo a Simon
DESTINOS_CONTROL_GROUP=simon

# Un prestador que nos envía va solo a Recurso Confiable
DESTINOS_MI_PROVEEDOR=recurso_confiable

# Otro prestador va a ambos destinos
DESTINOS_OTRO=recurso_confiable,simon

# Todos los demás (sin específico) van a ambos
DESTINOS_DEFAULT=recurso_confiable,simon
```

**¿Cómo se normaliza el nombre?**
El nombre del proveedor se convierte a mayúsculas y los guiones/espacios se reemplazan por guiones bajos:

| URL o nombre del ingestor | Variable buscada |
|---|---|
| `POST /ingresar/control-group` | `DESTINOS_CONTROL_GROUP` |
| `POST /ingresar/mi proveedor` | `DESTINOS_MI_PROVEEDOR` |
| Ingestor `control_group` | `DESTINOS_CONTROL_GROUP` |

---

## 6. Endpoints disponibles

| Método | Ruta | Descripción | Autenticación |
|---|---|---|---|
| `POST` | `/ingresar/{proveedor}` | Recibir pulsos GPS (modo pasivo) | Bearer token (opcional) |
| `GET` | `/metricas` | Métricas en JSON para el dashboard | No |
| `GET` | `/dashboard` | Panel de monitoreo HTML | No |
| `GET` | `/estado` | Estado del Hub (health check) | No |
| `GET` | `/docs` | Documentación Swagger interactiva | No |

**Respuesta de `/ingresar` exitosa (202):**
```json
{
  "estado": "aceptado",
  "mensaje": "3 evento(s) recibidos. Procesando en segundo plano.",
  "proveedor": "mi_proveedor",
  "modo_prueba": false
}
```

---

## 7. Modo Pasivo — El prestador nos envía datos

El prestador configura su plataforma para enviarnos un POST a:
```
https://tu-hub.railway.app/ingresar/{nombre_proveedor}
```

**Formatos aceptados:**

Evento único:
```json
{
  "placa": "ABC-123",
  "latitud": 19.432608,
  "longitud": -99.133209,
  "velocidad": "60",
  "fecha": "2024-03-15T10:30:00",
  "codigo_evento": "1"
}
```

Lote de eventos:
```json
[
  {"placa": "ABC-123", "latitud": 19.43, "longitud": -99.13, ...},
  {"placa": "XYZ-999", "latitud": 20.10, "longitud": -100.5, ...}
]
```

**Campos en inglés también son aceptados** (aliases automáticos):
```json
{"Asset": "ABC-123", "Latitude": 19.43, "Longitude": -99.13, ...}
```

Para agregar soporte para los campos de un nuevo prestador, ver sección 16.

---

## 8. Modo Activo — Nosotros consultamos la API

Para prestadores que no envían datos sino que exponen una API para consultar.
El planificador ejecuta `consultar()` de cada ingestor registrado en intervalos fijos.

```
Al arrancar el servidor:
    → lifespan registra los ingestores activos en el planificador
    → planificador.iniciar() crea una tarea asyncio por ingestor
    → Cada tarea: espera N segundos → consultar() → despachar() → espera N segundos
```

Ingestores activos disponibles:
- **Control Group** (`CONTROL_GROUP_ENABLED=true`) — ver sección 12

---

## 9. El modelo RegistroAVL

Es el modelo interno único del Hub. Cualquier dato que entra (por cualquier vía)
se convierte a `RegistroAVL` antes de ser despachado a los destinos.

| Campo | Tipo | Descripción |
|---|---|---|
| `placa` | string | Placa o ID único del vehículo |
| `latitud` | float o None | Latitud decimal. None si no hay señal GPS |
| `longitud` | float o None | Longitud decimal. None si no hay señal GPS |
| `fecha` | string | Fecha del evento: `YYYY-MM-DDTHH:MM:SS±HH:MM` |
| `velocidad` | string | Velocidad en km/h |
| `altitud` | string | Altitud en metros |
| `rumbo` | string | Rumbo en grados (0=Norte, 90=Este...) |
| `ignicion` | string | `"1"`=encendido, `"0"`=apagado |
| `odometro` | string | Kilómetros en odómetro |
| `numero_serie` | string | Número de serie del GPS |
| `bateria` | string | Nivel de batería 0-100 |
| `numero_viaje` | string | Número de viaje del embarcador |
| `temperatura` | string | Temperatura en °C |
| `humedad` | string | Humedad relativa 0-100 |
| `codigo_evento` | string | Código del evento AVL |
| `alerta` | string | Descripción de la alerta activa |
| `tipo_vehiculo` | string | Tipo: Tracto, Camión, etc. |
| `marca_vehiculo` | string | Marca: Ford, Volvo, etc. |
| `modelo_vehiculo` | string | Modelo: F500, FH, etc. |
| `usuario_avl` | string | Identificador de la fuente (para Simon) |
| `etiqueta_origen` | string | Tag de origen (para Simon) |

**Regla fundamental:** `latitud` y `longitud` pueden ser `None`. Un registro sin posición GPS nunca se descarta — los despachadores envían `0.0` en esos casos.

---

## 10. Destino A — Recurso Confiable

**Protocolo:** SOAP/XML sobre HTTPS
**Referencia:** D-TI-15 v14
**URL de producción:** `https://gps.rcontrol.com.mx/Tracking/wcf/RCService.svc`

**Autenticación:**
```
GetUserToken(usuario, clave) → token válido 24 horas
```
El token se guarda en memoria y se renueva automáticamente 30 minutos antes de vencer.

**Envío:** Todos los registros del lote se envían en un único envelope SOAP con múltiples nodos `<iron:Event>`. RC llama a esto "envío en bloque".

**Fechas:** RC requiere fechas sin offset de timezone (`YYYY-MM-DDTHH:MM:SS`). El Hub elimina cualquier offset automáticamente antes de enviar.

**Coordenadas sin GPS:** Si `latitud` o `longitud` son `None`, se envía `0.000000`. RC procesa el evento sin posición.

---

## 11. Destino B — Simon 4.0

**Protocolo:** REST/JSON sobre HTTPS
**Endpoint:** `POST /ReceiveAvlRecords`

**Autenticación:**
Simon entrega un token fijo que no expira. Se incluye en cada request:
```
Authorization: Bearer <SIMON_API_TOKEN>
```
No hay login previo ni renovación — es diferente al token dinámico de RC.

**Formato del body:** Siempre una lista JSON, aunque sea un solo registro:
```json
[{"Asset": "ABC-123", "Latitude": 19.43, ...}]
```

**Lotes grandes:** Se dividen automáticamente en bloques de 100 registros.

**Coordenadas sin GPS:** Si `latitud` o `longitud` son `None`, se envía `0.0`.

---

## 12. Ingestor — Control Group

**Protocolo:** XML sobre HTTP (NO es SOAP)
**URL:** `https://gateway.control-group.com.ar/gateway.asp`
**Credenciales:** parámetros en la URL (`usuario` y `clave`)

**Solicitud:**
```
GET /gateway.asp?usuario=assist&clave=cargo&modo=INCREMENTAL
```

**Modo INCREMENTAL:** El servidor recuerda cuándo fue la última consulta de este usuario y devuelve solo los eventos nuevos desde entonces. No hace falta gestionar timestamps del lado del Hub.

**Estructura de la respuesta (dinámica):**
```xml
<r cantidad="2" zonaHoraria="-03:00">
  <columnas>
    <i id="A" nombre="idRastreable" predeterminado="1"/>
    <i id="C" nombre="nombre" predeterminado="VJV-247"/>
    <i id="D" nombre="fecha"/>
    <i id="J" nombre="latitud"/>
    <i id="K" nombre="longitud"/>
    <i id="L" nombre="velocidad"/>
  </columnas>
  <filas>
    <i C="ABC-123" D="2024-01-15 10:30:00" J="-34.54" K="-58.47" L="60"/>
  </filas>
</r>
```

Los IDs de columna (A, B, C...) pueden cambiar. Los nombres (latitud, velocidad...) son constantes. El parser los mapea dinámicamente en cada respuesta.

**Mapeo de campos:**

| Campo CG | Campo RegistroAVL |
|---|---|
| `nombre` | `placa` |
| `idRastreable` | `numero_serie` |
| `fecha` | `fecha` (con offset `-03:00`) |
| `latitud` | `latitud` (None si no hay señal) |
| `longitud` | `longitud` (None si no hay señal) |
| `velocidad` | `velocidad` |
| `rumbo` | `rumbo` |
| `temperatura` | `temperatura` |
| `idTipoEvento` | `codigo_evento` |

**Ningún registro se descarta**, aunque le falte latitud y/o longitud.

**Configuración en `.env`:**
```bash
CONTROL_GROUP_ENABLED=true
CONTROL_GROUP_USER=assist
CONTROL_GROUP_PASS=cargo
CONTROL_GROUP_INTERVAL=60
DESTINOS_CONTROL_GROUP=simon
```

---

## 13. Dashboard de monitoreo

Disponible en: `http://localhost:8000/dashboard`

El dashboard se actualiza automáticamente cada 5 segundos consultando `/metricas`.

**Secciones:**

| Sección | Qué muestra |
|---|---|
| Resumen General | Tiempo activo, total ingestados, despachados OK/fallidos, proveedores activos |
| Estado de Destinos | Por destino: enviados, fallidos, tasa de éxito, último error |
| Proveedores AVL | Por proveedor: recibidos, normalizados, fallidos, placas recientes |
| Log de Actividad | Últimas 200 entradas con nivel, proveedor y mensaje |

El banner **"MODO PRUEBA"** aparece en amarillo cuando `DRY_RUN=true`.

---

## 14. Modo Prueba (sin envíos reales)

Activar en `.env`:
```bash
DRY_RUN=true
```

Con esta opción activa:
- El servidor funciona normalmente
- Los datos se reciben y normalizan
- Las métricas se registran (el dashboard funciona)
- **Los despachadores NO realizan llamadas HTTP**
- Los logs muestran `[MODO PRUEBA] *** SIMULADO ***`

**Flujo de prueba recomendado:**
```bash
# 1. Configurar
cp .env.example .env
# Editar: DRY_RUN=true

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Levantar servidor
uvicorn main:app --reload --port 8000

# 4. Ejecutar pruebas automáticas (en otra terminal)
bash test_local.sh

# 5. Ver dashboard
# Abrir http://localhost:8000/dashboard en el navegador

# 6. Probar manualmente
# Abrir http://localhost:8000/docs en el navegador
```

---

## 15. Deploy en Railway

**Pasos:**

1. Crear cuenta en [railway.app](https://railway.app)
2. Subir el proyecto a un repositorio de GitHub
3. En Railway: **New Project → Deploy from GitHub Repo**
4. Seleccionar el repositorio
5. En la sección **Variables**, cargar las variables del `.env.example`
6. Railway detecta el `Procfile` y despliega automáticamente

**Variables mínimas para arrancar:**
```
SEND_TO_RECURSO_CONFIABLE=true
RC_USER_ID=tu_usuario
RC_PASSWORD=tu_clave
```

Railway asigna el PORT automáticamente. No hace falta configurarlo.

La URL del Hub será: `https://tu-proyecto.up.railway.app`

---

## 16. Agregar un proveedor que nos envía datos

Para un prestador que **nos envía** su JSON (modo pasivo):

**Paso 1 — Identificar los nombres de campos del prestador**

El prestador documenta qué JSON envía. Por ejemplo:
```json
{"patente": "ABC123", "lat": -34.6, "lng": -58.4, "vel": 60}
```

**Paso 2 — Agregar aliases en `services/estandarizador.py`**

Abrir el diccionario `ALIASES_CAMPOS` y agregar los nuevos nombres:
```python
ALIASES_CAMPOS = {
    "placa":    [..., "patente"],   # agregar "patente"
    "latitud":  [..., "lat"],       # agregar "lat"
    "longitud": [..., "lng"],       # agregar "lng"
    "velocidad":[..., "vel"],       # agregar "vel"
    ...
}
```

**Paso 3 — Configurar el destino en `.env`**
```bash
DESTINOS_NOMBRE_PROVEEDOR=simon
# o recurso_confiable, o recurso_confiable,simon
```

**Paso 4 — Dar la URL al prestador**
```
POST https://tu-hub.railway.app/ingresar/nombre_proveedor
Content-Type: application/json
Authorization: Bearer <HUB_INGEST_TOKEN>  (si está configurado)
```

No se crea ningún archivo de código nuevo.

---

## 17. Agregar un ingestor activo nuevo

Para un prestador cuya API **debemos consultar nosotros** (modo activo):

**Paso 1 — Crear el archivo del ingestor**

```python
# services/ingestores/nombre_proveedor.py

from services.ingestores.base import IngestorBase
from services.estandarizador import RegistroAVL

class IngestorNombreProveedor(IngestorBase):

    def __init__(self, url: str, api_key: str):
        self._url = url
        self._api_key = api_key

    @property
    def nombre(self) -> str:
        return "nombre_proveedor"  # minúsculas con guiones bajos

    async def consultar(self) -> list[RegistroAVL]:
        # 1. Llamar a la API del prestador
        # 2. Parsear la respuesta
        # 3. Convertir a lista de RegistroAVL
        # 4. NUNCA descartar registros por falta de GPS
        # Si hay error, loguear y retornar []
        ...
```

**Paso 2 — Agregar variables en `core/config.py`**

```python
NOMBRE_PROVEEDOR_ACTIVO: bool = os.getenv("NOMBRE_PROVEEDOR_ENABLED", "false").lower() == "true"
NOMBRE_PROVEEDOR_URL: str = os.getenv("NOMBRE_PROVEEDOR_URL", "")
NOMBRE_PROVEEDOR_API_KEY: str = os.getenv("NOMBRE_PROVEEDOR_API_KEY", "")
NOMBRE_PROVEEDOR_INTERVALO: int = int(os.getenv("NOMBRE_PROVEEDOR_INTERVAL", "60"))
```

**Paso 3 — Registrar en `main.py` dentro del bloque lifespan**

```python
if config.NOMBRE_PROVEEDOR_ACTIVO:
    from services.ingestores.nombre_proveedor import IngestorNombreProveedor
    ingestor = IngestorNombreProveedor(
        url=config.NOMBRE_PROVEEDOR_URL,
        api_key=config.NOMBRE_PROVEEDOR_API_KEY,
    )
    planificador.registrar(ingestor, config.NOMBRE_PROVEEDOR_INTERVALO)
```

**Paso 4 — Configurar en `.env`**

```bash
NOMBRE_PROVEEDOR_ENABLED=true
NOMBRE_PROVEEDOR_URL=https://api.prestador.com
NOMBRE_PROVEEDOR_API_KEY=tu_api_key
NOMBRE_PROVEEDOR_INTERVAL=60
DESTINOS_NOMBRE_PROVEEDOR=simon
```

---

## 18. Errores frecuentes

| Error en logs | Causa | Solución |
|---|---|---|
| `401` en `/ingresar` | `HUB_INGEST_TOKEN` configurado pero no se envía | Agregar header `Authorization: Bearer <token>` o vaciar la variable |
| `400` en `/ingresar` | El body no es JSON válido | Verificar Content-Type y estructura |
| `RC Autenticación fallida` | `RC_USER_ID` o `RC_PASSWORD` incorrectos | Verificar con Recurso Confiable |
| `Simon HTTP 401` | `SIMON_API_TOKEN` incorrecto o vacío | Verificar token con el equipo de Simon |
| `Simon HTTP 400` | Formato de fecha incorrecto | Verificar `TIMEZONE_OFFSET` en `.env` |
| `CG Error al parsear XML` | Gateway devolvió error o HTML | Verificar `CONTROL_GROUP_USER` y `CONTROL_GROUP_PASS` |
| `MODO PRUEBA activo en producción` | Variable no actualizada en Railway | Ir a Railway → Variables → `DRY_RUN=false` y re-deployar |
| Token RC expirado | Venció en exacto el margen de renovación | El Hub lo renueva solo; si falla, invalidar y reiniciar |
