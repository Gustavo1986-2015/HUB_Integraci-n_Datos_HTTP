# Hub de Integración Satelital — Deploy en Railway

## Paso a paso

```
1. railway.app → New Project → Deploy from GitHub
2. Seleccionar repo: HUB_Integraci-n_Datos_HTTP
3. Ir a Variables → agregar todas las de abajo
4. Railway despliega automáticamente al detectar el Procfile
5. Verificar en: https://tu-proyecto.up.railway.app/estado
```

---

## Variables — copiar y completar

### General

| Variable | Valor |
|---|---|
| `LOG_LEVEL` | `INFO` |
| `LOG_RETENTION_HOURS` | `48` |
| `COLA_MAX_HORAS` | `24` |
| `DRY_RUN` | `false` |

> **Nota:** `PORT` NO se configura — Railway lo inyecta automáticamente.

### Seguridad

| Variable | Valor |
|---|---|
| `HUB_INGEST_TOKEN` | *(token que elijas — ej: `hubtoken_2026_abc123`)* |
| `CONFIG_USUARIO` | `admin` |
| `CONFIG_CLAVE` | *(clave que elijas)* |

### Recurso Confiable

| Variable | Valor |
|---|---|
| `SEND_TO_RECURSO_CONFIABLE` | `true` |
| `RC_SOAP_URL` | `http://gps.rcontrol.com.mx/Tracking/wcf/RCService.svc` |
| `RC_USER_ID` | `AC_avl_GustavoAC` |
| `RC_PASSWORD` | `RhVS_467FeNH_4` |
| `RC_TIMEZONE_OFFSET` | `+00:00` |

### Simon 4.0

| Variable | Valor |
|---|---|
| `SEND_TO_SIMON` | `true` |
| `SIMON_BASE_URL` | `https://simon-pre-webapi.assistcargo.com/ReceiveAvlRecords` |
| `SIMON_INTEGRATION_KEY` | `E7qX5fM8rPTq92A4vKHjL3ZynQG2vCdu` |
| `SIMON_API_TOKEN` | *(dejar vacío)* |
| `SIMON_USER_AVL` | `Rusertech` |
| `SIMON_SOURCE_TAG` | *(dejar vacío)* |
| `SIMON_TIMEZONE_OFFSET` | `-03:00` |

### Control Group

| Variable | Valor |
|---|---|
| `CONTROL_GROUP_ENABLED` | `true` |
| `CONTROL_GROUP_URL` | `https://gateway.control-group.com.ar/gateway.asp` |
| `CONTROL_GROUP_USER` | `assist2` |
| `CONTROL_GROUP_PASS` | `gus` |
| `CONTROL_GROUP_INTERVAL` | `60` |

### Routing

| Variable | Valor |
|---|---|
| `DESTINOS_CONTROL_GROUP` | `recurso_confiable,simon` |

> Mientras Simon esté en validación: `DESTINOS_CONTROL_GROUP=recurso_confiable`
> Cuando ambos destinos estén confirmados: `DESTINOS_CONTROL_GROUP=recurso_confiable,simon`

---

## URLs en producción

| Endpoint | URL |
|---|---|
| Health check | `https://tu-proyecto.up.railway.app/estado` |
| Dashboard | `https://tu-proyecto.up.railway.app/dashboard` |
| Métricas | `https://tu-proyecto.up.railway.app/metricas` |
| Ingesta | `https://tu-proyecto.up.railway.app/ingresar/{proveedor}` |

---

## Local vs Railway

| | Local (.exe) | Railway |
|---|---|---|
| Arranque | Doble click en HubSatelital.exe | Automático al hacer push |
| Config | GUI o .env | Panel Variables en railway.app |
| Dashboard | `http://localhost:8000/dashboard` | `https://tu-proyecto.up.railway.app/dashboard` |
| Logs | Ventana de la GUI | Pestaña Logs en railway.app |
| Cola de reintentos | `cola/` en disco local | `cola/` en disco de Railway (efímero) |
| 24/7 | No | Sí |

> **Nota sobre la cola en Railway:** El disco de Railway puede resetearse al redesplegar. Para ambientes de producción con alta criticidad, considerar migrar la cola a Redis o una base de datos.
