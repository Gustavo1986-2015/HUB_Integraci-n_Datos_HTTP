# Mapa del Proyecto — HUB de datos HTTP / Traductor Rusertech ® — ¿Qué hace cada archivo?

## La idea en una línea

El Hub recibe o consulta datos GPS de prestadores, los normaliza a un modelo único, limpia las placas y los envía a los destinos configurados. Si un envío falla, los datos esperan en cola y se reintenta automáticamente.

---

## Árbol completo explicado

```
HUB_Integración_Datos_HTTP/
│
│  ► main.py
│    El cerebro del proyecto. Arranca el servidor FastAPI, recibe los datos,
│    coordina el despacho, maneja la cola de reintentos y expone todos los endpoints.
│
│  ► hub_gui.py
│    Interfaz gráfica de escritorio (CustomTkinter — tema Deep Space).
│    Doble click → Login → Monitor en vivo + Configuración.
│    Arranca uvicorn dentro del mismo proceso (sin ventana extra).
│    Detecta ngrok automáticamente (localhost:4040) y muestra la URL pública.
│    Compilar: pyinstaller --onefile --windowed --icon=hub_icon.ico --distpath . --name "HubSatelital" hub_gui.py
│
│  ► hub_icon.ico
│    Ícono del .exe con el satélite. Necesario para la compilación.
│
│  ► .env
│    Tus credenciales y configuración real. NUNCA sube a GitHub.
│
│  ► .env.example.new
│    Plantilla vacía. Copiar como .env y completar.
│
│  ► requirements.txt / runtime.txt / Procfile
│    Dependencias Python y configuración de arranque para Railway.
│
│  ► RAILWAY_VARIABLES.md
│    Guía completa de deploy en Railway con todas las variables.
│
├── core/
│   └── config.py
│        Lee TODAS las variables del .env al arrancar.
│        Un solo lugar para cambiar cualquier parámetro del sistema.
│
├── services/
│   │
│   │  ► cola_pendientes.py
│   │    Cola de reintentos en archivos JSON.
│   │    Si RC o Simon no responden, los registros se guardan aquí
│   │    y se reenvían en el próximo ciclo automáticamente.
│   │    Persiste en disco aunque el Hub se reinicie.
│   │    Archivos: cola/pendientes_recurso_confiable.json | cola/pendientes_simon.json
│   │
│   │  ► estandarizador.py
│   │    Convierte cualquier JSON o XML al modelo único RegistroAVL.
│   │    También limpia las placas: elimina guiones, espacios y caracteres
│   │    especiales antes de enviar a cualquier destino.
│   │    "ABC-123" → "ABC123"
│   │
│   │  ► metricas.py
│   │    Lleva la cuenta en memoria de todo lo que pasa:
│   │    ingestados, enviados, fallidos. El dashboard y la GUI
│   │    leen estos datos cada 5 segundos.
│   │
│   │  ► planificador.py
│   │    Ejecuta los ingestores activos cada N segundos.
│   │    Si un ingestor falla, el error se loguea y el ciclo continúa.
│   │
│   │  ► logger_archivo.py
│   │    Escribe un archivo JSON por día en logs/.
│   │    Una línea por placa con todos sus datos + resultado del envío.
│   │    Escritura en BATCH: una sola apertura de archivo por lote
│   │    (crítico para no bloquear el event loop con miles de registros).
│   │    Retención configurable con LOG_RETENTION_HOURS en .env.
│   │
│   │  ► dashboard.html / configuracion.html
│   │    Interfaces web de monitoreo y configuración (acceso por navegador).
│   │
│   ├── despachadores/
│   │   │   Envían los datos normalizados a los destinos finales.
│   │   │
│   │   ├── cliente_rc.py
│   │   │    Recurso Confiable — SOAP/XML (Protocolo D-TI-15 v14).
│   │   │    Token de sesión automático (renueva 30 min antes de vencer).
│   │   │    Retorna el idJob de RC para trazabilidad.
│   │   │    URL: http:// (no https) — RC no usa SSL en este endpoint.
│   │   │
│   │   └── cliente_simon.py
│   │        Simon 4.0 — REST/JSON.
│   │        La integration key va como ?rpaIntegrationKey=... en la URL.
│   │        Ajusta el timezone de las fechas a hora local del prestador.
│   │        Endpoint: POST /ReceiveAvlRecords?rpaIntegrationKey=XXX
│   │
│   └── ingestores/
│       │   Consultan APIs de prestadores externos (modo activo).
│       │
│       ├── base.py
│       │    Contrato mínimo: nombre + consultar().
│       │
│       └── control_group.py
│            Consulta el Gateway de Control Group cada N segundos.
│            Parsea XML con columnas dinámicas usando un diccionario:
│              mapa_columnas = {id_letra: {nombre, predeterminado}}
│            Si una fila no trae un campo → usa el predeterminado del dict.
│            NUNCA descarta registros aunque no tengan posición GPS.
│
└── cola/         ← archivos de reintentos (se crean automáticamente)
└── logs/         ← archivos de auditoría diarios (se crean automáticamente)
```

---

## Flujo de un dato

```
1. ORIGEN
   Control Group, Samsara, u otro prestador tiene vehículos reportando eventos

2. OBTENCIÓN / RECEPCIÓN
   Activo:  Hub consulta la API cada 60s → ingestores/control_group.py
   Pasivo:  Prestador hace POST /ingresar/{nombre} → main.py recibe

3. NORMALIZACIÓN (services/estandarizador.py)
   XML o JSON → RegistroAVL. Placa limpiada: "ABC-123" → "ABC123"

4. ROUTING (core/config.py)
   ¿A dónde van los datos de este proveedor?
   Lee DESTINOS_{PROVEEDOR} del .env

5. ENVÍO (services/despachadores/)
   "recurso_confiable" → cliente_rc.py   → SOAP/XML → idJob
   "simon"            → cliente_simon.py → REST/JSON → ?rpaIntegrationKey=...

6. COLA (services/cola_pendientes.py)
   Si el envío falla → cola/pendientes_*.json
   Próximo ciclo → reintenta antes de enviar datos nuevos

7. AUDITORÍA (services/logger_archivo.py)
   Un registro JSON por placa. Escritura en batch, sin bloquear el event loop.
```

---

## Regla fundamental

> Ningún registro se descarta aunque no tenga posición GPS.
> Los despachadores envían latitud/longitud = 0.0 cuando son None.

---

## Recibir datos en local — ngrok

Para exponer el Hub local a Internet y recibir datos de prestadores externos:

```powershell
winget install ngrok.ngrok           # instalar
ngrok config add-authtoken TU_TOKEN  # autenticar (ngrok.com)
ngrok http 8000                      # exponer el Hub
```

La GUI detecta la URL activa automáticamente. Ver `DOCUMENTACION.md` para el flujo completo.

---

## Variables importantes del .env

| Variable | Para qué sirve |
|---|---|
| `DRY_RUN=true` | Simular envíos sin contactar destinos reales |
| `CONTROL_GROUP_ENABLED=true` | Activar ingestor de Control Group |
| `DESTINOS_CONTROL_GROUP=recurso_confiable` | A dónde van sus datos |
| `SIMON_BASE_URL` | URL base de Simon (sin la integration key) |
| `SIMON_INTEGRATION_KEY` | clave que se agrega como ?rpaIntegrationKey=... |
| `RC_TIMEZONE_OFFSET=+00:00` | RC requiere UTC |
| `SIMON_TIMEZONE_OFFSET=-03:00` | Simon requiere hora local |
| `COLA_MAX_HORAS=24` | Cuánto tiempo esperar antes de descartar pendientes |
