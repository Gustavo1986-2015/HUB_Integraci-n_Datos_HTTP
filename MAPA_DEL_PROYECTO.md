# Mapa del Proyecto — ¿Qué hace cada archivo?

## La idea en una línea

El Hub recibe o consulta datos GPS de prestadores, los normaliza
a un modelo único, limpia las placas y los envía a los destinos
configurados. Todo queda registrado en logs para auditoría.

---

## Árbol completo explicado

```
HUB_Integración_Datos_HTTP/
│
│  ► main.py
│    El cerebro del proyecto. Arranca el servidor, recibe los datos,
│    coordina el despacho y expone todos los endpoints.
│    Es el único archivo que "une" todo lo demás.
│
│  ► .env
│    Tus credenciales y configuración real. NUNCA sube a GitHub.
│    Es el único archivo que editás para cambiar el comportamiento
│    del Hub sin tocar código.
│
│  ► .env.example
│    Plantilla vacía del .env. Sí sube a GitHub.
│    Muestra qué variables hay que configurar y para qué sirve cada una.
│
│  ► requirements.txt
│    Lista de librerías Python que el proyecto necesita.
│    Se instala una sola vez: pip install -r requirements.txt
│
│  ► Procfile
│    Le dice a Railway cómo arrancar el servidor.
│    Solo se usa en producción. Ignorar en local.
│
│  ► runtime.txt
│    Le dice a Railway qué versión de Python usar.
│    Solo se usa en producción. Ignorar en local.
│
│  ► test_local.sh
│    Script que prueba automáticamente que el Hub responde bien.
│    Ejecutar una vez después de arrancar para verificar todo.
│
│  ► DOCUMENTACION.md
│    Manual técnico completo: instalación, variables, endpoints,
│    cómo agregar proveedores, errores frecuentes, etc.
│
│  ► MAPA_DEL_PROYECTO.md
│    Este archivo. Visión rápida de qué hace cada script.
│
│  ► README.md
│    Presentación en GitHub. Arranque rápido en 3 pasos.
│
├── core/
│   │
│   └── config.py
│        Lee TODAS las variables del .env y las pone disponibles
│        para el resto del proyecto.
│        Si querés saber qué variable controla qué cosa, mirá acá.
│        También incluye el método de routing: quién va a dónde.
│
├── services/
│   │
│   │  ► estandarizador.py
│   │    Convierte cualquier JSON (de cualquier prestador) al modelo
│   │    único interno: RegistroAVL.
│   │    También limpia las placas: elimina guiones, espacios y
│   │    caracteres especiales antes de enviar a cualquier destino.
│   │    Si un nuevo prestador usa nombres de campos distintos,
│   │    solo hay que agregar sus aliases en ALIASES_CAMPOS.
│   │
│   │  ► metricas.py
│   │    Lleva la cuenta en memoria de todo lo que pasa:
│   │    cuántos registros entraron, se enviaron, fallaron.
│   │    El dashboard lee estos datos cada 5 segundos.
│   │    Se resetea al reiniciar el servidor.
│   │
│   │  ► planificador.py
│   │    Ejecuta los ingestores activos cada N segundos.
│   │    Es el reloj del Hub: "cada 60 segundos, consultá Control Group".
│   │    Si un ingestor falla, el error se loguea y el ciclo continúa.
│   │
│   │  ► logger_archivo.py
│   │    Escribe un archivo JSON por día en la carpeta logs/.
│   │    Guarda UN registro por placa con todos sus datos:
│   │    posición, velocidad, evento, temperatura, etc.
│   │    Permite auditar qué datos exactos tuvo cada vehículo
│   │    en cada momento y si el envío fue exitoso.
│   │    Elimina automáticamente archivos más viejos de N horas.
│   │
│   │  ► dashboard.html
│   │    El panel de monitoreo visual que ves en el navegador.
│   │    Se actualiza automáticamente cada 5 segundos consultando /metricas.
│   │    Muestra: KPIs, estado de destinos, proveedores activos y log.
│   │
│   │  ► configuracion.html
│   │    UI web para configurar el Hub sin editar el .env manualmente.
│   │    Secciones: General, Destinos (RC/Simon), APIs, Routing.
│   │    Protegida con usuario/contraseña (CONFIG_USUARIO / CONFIG_CLAVE).
│   │    El botón Guardar escribe el .env. Reiniciar para aplicar cambios.
│   │
│   ├── despachadores/
│   │   │   Envían los datos normalizados a los destinos finales.
│   │   │   Hay uno por cada destino. Cada uno conoce su propio protocolo.
│   │   │
│   │   ├── cliente_rc.py
│   │   │    Envía a Recurso Confiable usando protocolo SOAP/XML.
│   │   │    Maneja el token de sesión automáticamente (dura 24 horas,
│   │   │    se renueva solo 30 minutos antes de vencer).
│   │   │    Retorna el idJob de RC para trazabilidad en logs.
│   │   │    Referencia: documento D-TI-15 v14.
│   │   │
│   │   └── cliente_simon.py
│   │        Envía a Simon 4.0 usando protocolo REST/JSON.
│   │        Usa un token Bearer fijo que Simon entrega una sola vez.
│   │        Para lotes grandes divide en bloques de 100 automáticamente.
│   │
│   └── ingestores/
│       │   Consultan APIs de prestadores externos (modo activo).
│       │   El planificador llama a consultar() de cada ingestor
│       │   cada N segundos según el intervalo configurado.
│       │
│       ├── base.py
│       │    Define el contrato mínimo que todo ingestor debe cumplir:
│       │    tener un nombre y un método consultar().
│       │    No hace nada por sí solo. Es la plantilla.
│       │
│       └── control_group.py
│            Consulta el Gateway de Control Group cada N segundos.
│            Parsea el XML de respuesta con columnas dinámicas.
│            Si una fila no trae placa, usa el predeterminado de la columna.
│            NUNCA descarta registros aunque no tengan posición GPS.
│
└── logs/
     Carpeta creada automáticamente al primer envío.
     Contiene archivos hub_YYYY-MM-DD.json (uno por día).
     Se eliminan automáticamente según LOG_RETENTION_HOURS.
```

---

## Flujo completo de un dato

```
1. ORIGEN
   Control Group tiene vehículos con GPS reportando eventos

2. OBTENCIÓN (ingestores/control_group.py)
   El Hub consulta el gateway cada 60 segundos en modo INCREMENTAL
   Solo devuelve eventos nuevos desde la última consulta

3. NORMALIZACIÓN (services/estandarizador.py)
   El XML se convierte al modelo único: RegistroAVL
   La placa se limpia: "ABC-123" → "ABC123"

4. ROUTING (core/config.py)
   ¿A dónde van los datos de control_group?
   Lee DESTINOS_CONTROL_GROUP del .env

5. ENVÍO (services/despachadores/)
   "recurso_confiable" → cliente_rc.py   → SOAP/XML → idJob
   "simon"            → cliente_simon.py → REST/JSON

6. LOG DE AUDITORÍA (services/logger_archivo.py)
   Un registro JSON por placa con todos sus datos
   + registro de despacho con idJob y resultado

7. MÉTRICAS (services/metricas.py + dashboard.html)
   Contadores actualizados visibles en tiempo real
```

---

## Regla fundamental

> Ningún registro se descarta aunque no tenga posición GPS.
> Un evento de pánico, batería baja o alarma es información
> valiosa independientemente de si hay señal GPS en ese momento.
> Los despachadores envían latitud/longitud = 0.0 en esos casos.

---

## Seguridad

| Endpoint | Protección |
|---|---|
| `POST /ingresar/{proveedor}` | Bearer token (`HUB_INGEST_TOKEN`) |
| `GET /configuracion` | HTTP Basic Auth (`CONFIG_USUARIO` / `CONFIG_CLAVE`) |
| `GET /dashboard` | Sin autenticación (solo lectura) |
| `GET /estado` | Sin autenticación (health check) |

En desarrollo local dejar vacías las variables de seguridad.
En producción **siempre** configurar ambas.
