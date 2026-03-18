# Hub de Integración Satelital

Recibe o consulta pulsos GPS de prestadores AVL, los normaliza y los envía a Recurso Confiable (SOAP) y/o Simon 4.0 (REST).

## Arranque rápido

```bash
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Disponible en:
- **Dashboard:**      http://localhost:8000/dashboard
- **Configuración:**  http://localhost:8000/configuracion
- **Estado:**         http://localhost:8000/estado

## Estructura

```
├── main.py                          # Punto de entrada
├── core/config.py                   # Configuración y variables de entorno
├── services/
│   ├── estandarizador.py            # Normalización → RegistroAVL
│   ├── metricas.py                  # Métricas en tiempo real
│   ├── planificador.py              # Ejecuta ingestores activos
│   ├── logger_archivo.py            # Logs JSON diarios en /logs
│   ├── dashboard.html               # Panel de monitoreo
│   ├── configuracion.html           # UI de configuración
│   ├── despachadores/
│   │   ├── cliente_rc.py            # → Recurso Confiable (SOAP)
│   │   └── cliente_simon.py         # → Simon 4.0 (REST/JSON)
│   └── ingestores/
│       ├── base.py                  # Contrato base
│       └── control_group.py         # Control Group Gateway
```

## Modos de operación

**Pasivo** — el prestador nos envía datos:
```
POST /ingresar/{nombre_proveedor}
Content-Type: application/json
```

**Activo** — nosotros consultamos la API del prestador:
```
CONTROL_GROUP_ENABLED=true  →  consulta automática cada N segundos
```

## Variables principales (.env)

| Variable | Descripción |
|---|---|
| `DRY_RUN=true` | Modo prueba — sin envíos reales |
| `SEND_TO_RECURSO_CONFIABLE=true` | Activar destino RC |
| `SEND_TO_SIMON=true` | Activar destino Simon 4.0 |
| `CONTROL_GROUP_ENABLED=true` | Activar ingestor Control Group |
| `DESTINOS_CONTROL_GROUP=simon` | A qué destino van los datos de CG |
| `LOG_RETENTION_HOURS=48` | Horas que se conservan los logs |

Ver `.env.example` para la lista completa.

## Documentación completa

Ver [DOCUMENTACION.md](DOCUMENTACION.md)
