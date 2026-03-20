# HUB de datos HTTP — Traductor Rusertech ®

Sistema de integración AVL desarrollado por Rusertech. Recibe o consulta datos GPS de prestadores satelitales, los normaliza a un modelo único y los despacha a Recurso Confiable (SOAP/XML) y/o Simon 4.0 (REST/JSON).

## Inicio rápido

### Local — con GUI (recomendado)

```bash
# 1. Instalar dependencias
pip install -r requirements.txt

# 2. Configurar variables
cp .env.example .env
# Editar .env con credenciales reales

# 3. Ejecutar
python hub_gui.py
```

### Local — sin GUI

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

### Compilar ejecutable .exe

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --icon=hub_icon.ico --distpath . --name "HubSatelital" hub_gui.py
```

El `.exe` queda en la raíz del proyecto junto al `.env`.

## Estructura

```
├── main.py              # FastAPI + despacho + cola de reintentos
├── hub_gui.py           # GUI de escritorio CustomTkinter (Deep Space)
├── hub_icon.ico         # Ícono del .exe
├── core/config.py       # Variables de entorno centralizadas
├── services/
│   ├── cola_pendientes.py      # Cola de reintentos en JSON
│   ├── estandarizador.py       # Normalización al modelo RegistroAVL
│   ├── logger_archivo.py       # Logs de auditoría por placa
│   ├── metricas.py             # Contadores en memoria
│   ├── planificador.py         # Scheduler asyncio
│   ├── despachadores/
│   │   ├── cliente_rc.py       # Envío SOAP a Recurso Confiable
│   │   └── cliente_simon.py    # Envío REST a Simon 4.0
│   └── ingestores/
│       └── control_group.py    # Ingestor activo Control Group Gateway
└── .env                 # Credenciales (NO subir a GitHub)
```

## Endpoints

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/ingresar/{proveedor}` | Recibir datos de un prestador |
| `GET` | `/metricas` | Métricas JSON en tiempo real |
| `GET` | `/dashboard` | Panel de monitoreo |
| `GET` | `/estado` | Health check |

## Destinos soportados

| Destino | Protocolo | Auth |
|---|---|---|
| Recurso Confiable | SOAP/XML (D-TI-15 v14) | Usuario + contraseña |
| Simon 4.0 — `POST /ReceiveAvlRecords` | REST/JSON | `?rpaIntegrationKey=...` en la URL |

## Cola de reintentos

Si un envío falla, los registros se guardan en `cola/pendientes_*.json` y se reenvían automáticamente en el próximo ciclo. Los archivos persisten aunque el Hub se reinicie.

## Recibir datos en local desde Internet (ngrok)

Para que un prestador AVL externo pueda enviarte datos mientras desarrollás en local:

```powershell
# 1. Instalar ngrok (una sola vez)
winget install ngrok.ngrok

# 2. Autenticar (una sola vez)
ngrok config add-authtoken TU_TOKEN  # obtener en ngrok.com

# 3. Con el Hub corriendo, exponer el puerto
ngrok http 8000
```

La GUI detecta automáticamente cuando ngrok está activo y muestra la URL pública.
Un click en la URL la copia al portapapeles para pasarla al prestador.

URL que recibe el prestador:
```
POST https://abc123.ngrok-free.app/ingresar/{nombre_proveedor}
Authorization: Bearer {HUB_INGEST_TOKEN}
```

> La URL cambia cada vez que se reinicia ngrok (plan gratuito). Para URL fija, usar Railway.

## Deploy en Railway

Ver [RAILWAY_VARIABLES.md](RAILWAY_VARIABLES.md) para instrucciones completas.
