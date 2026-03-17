# Hub de Integración Satelital

Recibe o consulta pulsos GPS de prestadores AVL, los normaliza y los envía a Recurso Confiable (SOAP) y/o Simon 4.0 (REST).

## Arranque rápido

```bash
# 1. Instalar dependencias
pip install -r requirements.txt

# 2. Crear configuración
cp .env.example .env

# 3. Levantar servidor
uvicorn main:app --reload --port 8000
```

El Hub queda disponible en:
- Dashboard: http://localhost:8000/dashboard
- Documentación: http://localhost:8000/docs
- Estado: http://localhost:8000/estado

## Estructura

```
├── main.py                        # Punto de entrada
├── core/config.py                 # Configuración y variables de entorno
├── services/
│   ├── estandarizador.py          # Normalización de datos → RegistroAVL
│   ├── metricas.py                # Métricas en tiempo real
│   ├── planificador.py            # Ejecuta ingestores activos
│   ├── dashboard.html             # Panel de monitoreo
│   ├── despachadores/
│   │   ├── cliente_rc.py          # Envío a Recurso Confiable (SOAP)
│   │   └── cliente_simon.py       # Envío a Simon 4.0 (REST)
│   └── ingestores/
│       ├── base.py                # Contrato base para ingestores
│       └── control_group.py       # Consulta al Gateway de Control Group
```

## Modos de operación

**Pasivo** — el prestador nos envía datos:
```
POST /ingresar/{nombre_proveedor}
Content-Type: application/json
```

**Activo** — nosotros consultamos la API del prestador:
```
Activar en .env: CONTROL_GROUP_ENABLED=true
El Hub consulta automáticamente cada N segundos
```

## Variables principales

| Variable | Descripción |
|---|---|
| `DRY_RUN=true` | Modo prueba — sin envíos reales |
| `CONTROL_GROUP_ENABLED=true` | Activar ingestor Control Group |
| `SEND_TO_RECURSO_CONFIABLE=true` | Activar destino RC |
| `SEND_TO_SIMON=true` | Activar destino Simon 4.0 |
| `DESTINOS_CONTROL_GROUP=simon` | A qué destino van los datos de CG |

Ver `.env.example` para la lista completa.

## Documentación completa

Ver [DOCUMENTACION.md](DOCUMENTACION.md)
