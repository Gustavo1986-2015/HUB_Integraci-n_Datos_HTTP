# Hub de Integración Satelital — Variables para Railway

## Cómo cargarlas

1. Ir a [railway.app](https://railway.app) → tu proyecto → pestaña **Variables**
2. Agregar cada variable de la tabla de abajo con su valor
3. Railway reinicia el servidor automáticamente al guardar

---

## Variables requeridas

### Servidor
| Variable | Valor |
|---|---|
| `LOG_LEVEL` | `INFO` |
| `LOG_RETENTION_HOURS` | `48` |
| `COLA_MAX_HORAS` | `24` |
| `DRY_RUN` | `false` |

> **Nota:** `PORT` NO se configura — Railway lo inyecta automáticamente.

---

### Seguridad
| Variable | Valor |
|---|---|
| `HUB_INGEST_TOKEN` | *(token que elijas — ej: `hubtoken_2026_abc123`)* |
| `CONFIG_USUARIO` | `admin` |
| `CONFIG_CLAVE` | *(clave que elijas)* |

---

### Destino — Recurso Confiable (SOAP/XML)
| Variable | Valor |
|---|---|
| `SEND_TO_RECURSO_CONFIABLE` | `true` |
| `RC_SOAP_URL` | `http://gps.rcontrol.com.mx/Tracking/wcf/RCService.svc` |
| `RC_USER_ID` | `AC_avl_GustavoAC` |
| `RC_PASSWORD` | `RhVS_467FeNH_4` |
| `RC_TIMEZONE_OFFSET` | `+00:00` |

---

### Destino — Simon 4.0 (REST/JSON)
| Variable | Valor |
|---|---|
| `SEND_TO_SIMON` | `true` |
| `SIMON_BASE_URL` | `https://simon-pre-webapi.assistcargo.com/RPAAvlRecord/Add` |
| `SIMON_API_TOKEN` | *(dejar vacío — Simon no requiere token en este endpoint)* |
| `SIMON_USER_AVL` | `Rusertech` |
| `SIMON_SOURCE_TAG` | *(dejar vacío)* |
| `SIMON_TIMEZONE_OFFSET` | `-03:00` |

---

### Ingestor — Control Group
| Variable | Valor |
|---|---|
| `CONTROL_GROUP_ENABLED` | `true` |
| `CONTROL_GROUP_URL` | `https://gateway.control-group.com.ar/gateway.asp` |
| `CONTROL_GROUP_USER` | `assist2` |
| `CONTROL_GROUP_PASS` | `gus` |
| `CONTROL_GROUP_INTERVAL` | `60` |

---

### Routing
| Variable | Valor |
|---|---|
| `DESTINOS_CONTROL_GROUP` | `recurso_confiable,simon` |

> Cuando ambos destinos estén confirmados, usar `recurso_confiable,simon`.
> Si querés probar uno por uno: `recurso_confiable` o `simon`.

---

## Pasos para el primer deploy

```
1. Subir código a GitHub (ya lo tenés)
2. railway.app → New Project → Deploy from GitHub
3. Seleccionar el repo HUB_Integración_Datos_HTTP
4. Ir a Variables → agregar todas las de arriba
5. Railway despliega automáticamente
6. La URL del Hub será: https://tu-proyecto.up.railway.app
```

## Verificar que funciona

Una vez deployado, visitar:
```
https://tu-proyecto.up.railway.app/estado
https://tu-proyecto.up.railway.app/dashboard
```

## Diferencia local vs Railway

| | Local (.exe) | Railway |
|---|---|---|
| Arranque | Doble click en HubSatelital.exe | Automático al hacer push a GitHub |
| Configuración | hub_gui.py o .env | Panel Variables en railway.app |
| Dashboard | http://localhost:8000/dashboard | https://tu-proyecto.up.railway.app/dashboard |
| Logs | Ventana de la GUI | Pestaña Logs en railway.app |
| Funciona 24/7 | No (depende de que la PC esté encendida) | Sí |
