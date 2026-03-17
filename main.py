"""
main.py
=======
Punto de entrada del Hub de Integración Satelital.

¿Qué hace este Hub?
    Recibe o consulta pulsos GPS de prestadores satelitales,
    los normaliza a un modelo único (RegistroAVL) y los envía
    a los destinos configurados (Recurso Confiable y/o Simon 4.0).

Dos modos de operación (pueden correr simultáneamente):

    MODO PASIVO — El prestador nos envía los datos:
        Prestador GPS
            → POST /ingresar/{nombre_proveedor}
            → Estandarizador → RegistroAVL
            → Destinos configurados para ese proveedor

    MODO ACTIVO — Nosotros consultamos la API del prestador:
        PlanificadorIngestores (loop asyncio cada N segundos)
            → ingestores/control_group.py → consultar()
            → RegistroAVL
            → Destinos configurados para ese proveedor

    MODO PRUEBA — Sin envíos reales (DRY_RUN=true en .env):
        Igual que los modos anteriores pero el despacho final
        no ocurre. Solo normaliza, loguea y registra métricas.

Endpoints disponibles:
    POST /ingresar/{proveedor}  — Recepción de pulsos (modo pasivo)
    GET  /metricas              — Métricas JSON para el dashboard
    GET  /dashboard             — Dashboard de monitoreo en tiempo real
    GET  /estado                — Estado del servicio (health check)
    GET  /docs                  — Documentación Swagger automática
"""

import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI, BackgroundTasks, HTTPException, Request, Depends
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from core.config import obtener_configuracion
from services.estandarizador import normalizar_carga, RegistroAVL
from services.metricas import almacen as almacen_metricas
from services.planificador import planificador

# =========================================================================== #
# Logging                                                                     #
# =========================================================================== #

config = obtener_configuracion()

logging.basicConfig(
    level=getattr(logging, config.NIVEL_LOG.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


# =========================================================================== #
# Función central de despacho                                                 #
# Usada por modo pasivo (/ingresar) y modo activo (planificador)              #
# =========================================================================== #

async def despachar(registros: list[RegistroAVL], nombre_proveedor: str) -> None:
    """
    Envía los registros a los destinos configurados para el proveedor dado.

    Routing (prioridad de mayor a menor):
        1. DESTINOS_{NOMBRE_PROVEEDOR} en .env  →  específico por proveedor
           Ejemplos:
             DESTINOS_CONTROL_GROUP=simon
             DESTINOS_MI_PROVEEDOR=recurso_confiable
             DESTINOS_OTRO=recurso_confiable,simon
        2. DESTINOS_DEFAULT en .env             →  fallback para todos
        3. Flags ENVIAR_A_RC / ENVIAR_A_SIMON   →  modo básico

    Modo prueba (DRY_RUN=true):
        No realiza ningún envío real. Solo loguea y registra en métricas.

    Args:
        registros:        Lista de RegistroAVL normalizados.
        nombre_proveedor: Nombre del proveedor (para routing y métricas).
    """
    if not registros:
        return

    destinos = config.obtener_destinos_del_proveedor(nombre_proveedor)

    if not destinos:
        logger.warning(
            "[Despacho] '%s': sin destinos configurados. "
            "Setear DESTINOS_%s o DESTINOS_DEFAULT en .env",
            nombre_proveedor,
            nombre_proveedor.upper().replace("-", "_"),
        )
        return

    logger.info(
        "[Despacho] '%s': %d registro(s) → destinos: %s",
        nombre_proveedor, len(registros), destinos,
    )

    # ── Modo prueba: simular sin enviar ─────────────────────────────────
    if config.MODO_PRUEBA:
        logger.warning(
            "[MODO PRUEBA] *** SIMULADO para '%s': %d registros "
            "habrían ido a %s ***",
            nombre_proveedor, len(registros), destinos,
        )
        for destino in destinos:
            if destino in ("recurso_confiable", "simon"):
                almacen_metricas.registrar_despacho(destino, len(registros), True)
        return

    # ── Envío real a Recurso Confiable ───────────────────────────────────
    if "recurso_confiable" in destinos:
        try:
            from services.despachadores.cliente_rc import despachar as enviar_rc
            exito = await enviar_rc(
                registros=registros,
                url=config.RC_URL_SOAP,
                usuario=config.RC_USUARIO,
                clave=config.RC_CLAVE,
            )
            almacen_metricas.registrar_despacho(
                "recurso_confiable", len(registros), exito,
                mensaje_error=None if exito else "Ver logs del servidor",
            )
            logger.info("[Despacho] RC — %s", "✓ Éxito" if exito else "✗ Fallo")
        except Exception as error:
            almacen_metricas.registrar_despacho(
                "recurso_confiable", len(registros), False, str(error)
            )
            logger.error("[Despacho] Error inesperado enviando a RC: %s", error)

    # ── Envío real a Simon 4.0 ───────────────────────────────────────────
    if "simon" in destinos:
        try:
            from services.despachadores.cliente_simon import despachar as enviar_simon
            exito = await enviar_simon(
                registros=registros,
                url_base=config.SIMON_URL_BASE,
                usuario_avl=config.SIMON_USUARIO_AVL,
                etiqueta_origen=config.SIMON_ETIQUETA_ORIGEN,
                token_api=config.SIMON_TOKEN_API,
            )
            almacen_metricas.registrar_despacho(
                "simon", len(registros), exito,
                mensaje_error=None if exito else "Ver logs del servidor",
            )
            logger.info("[Despacho] Simon — %s", "✓ Éxito" if exito else "✗ Fallo")
        except Exception as error:
            almacen_metricas.registrar_despacho(
                "simon", len(registros), False, str(error)
            )
            logger.error("[Despacho] Error inesperado enviando a Simon: %s", error)


# =========================================================================== #
# Pipeline de ingesta pasiva (se ejecuta como BackgroundTask)                 #
# =========================================================================== #

async def recibir_y_despachar(datos_crudos: Any, nombre_proveedor: str) -> None:
    """
    Normaliza el payload recibido en /ingresar y llama a despachar().
    Corre como BackgroundTask — el proveedor ya recibió su respuesta 202.

    Args:
        datos_crudos:     Payload JSON tal como llegó en el request.
        nombre_proveedor: Nombre del proveedor (parámetro de la URL).
    """
    cantidad_cruda = len(datos_crudos) if isinstance(datos_crudos, list) else 1

    try:
        registros = normalizar_carga(
            datos_crudos,
            zona_horaria=config.ZONA_HORARIA,
            usuario_avl_defecto=config.SIMON_USUARIO_AVL,
            etiqueta_origen_defecto=config.SIMON_ETIQUETA_ORIGEN,
        )
    except Exception as error:
        logger.error("[Ingesta] Error normalizando datos de '%s': %s",
                     nombre_proveedor, error)
        almacen_metricas.registrar_ingesta(nombre_proveedor, cantidad_cruda, 0, [])
        return

    placas = [r.placa for r in registros if r.placa]
    almacen_metricas.registrar_ingesta(
        nombre_proveedor, cantidad_cruda, len(registros), placas
    )

    if not registros:
        logger.warning("[Ingesta] Ningún registro válido de '%s'.", nombre_proveedor)
        return

    await despachar(registros, nombre_proveedor)


# =========================================================================== #
# Lifespan — arranque y cierre del servidor                                   #
# =========================================================================== #

@asynccontextmanager
async def ciclo_vida(app: FastAPI):
    """
    Startup:  Registra los ingestores activos y arranca el planificador.
    Shutdown: Detiene el planificador de forma ordenada.

    Para agregar un nuevo ingestor activo:
        1. Crear services/ingestores/nuevo_proveedor.py
        2. Agregar las variables de config en core/config.py
        3. Registrar aquí siguiendo el mismo patrón que Control Group
    """
    # ── Banner de arranque ────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("Hub de Integración Satelital — Iniciando...")
    if config.MODO_PRUEBA:
        logger.warning("*** MODO PRUEBA ACTIVO — Sin envíos reales ***")
    logger.info("Ingestores activos:")

    # ── Registrar ingestores activos ─────────────────────────────────────
    # Para agregar uno nuevo: copiar el bloque if/else de abajo
    if config.CG_ACTIVO:
        from services.ingestores.control_group import IngestorControlGroup
        ingestor_cg = IngestorControlGroup(
            url=config.CG_URL,
            usuario=config.CG_USUARIO,
            clave=config.CG_CLAVE,
            zona_horaria="-03:00",  # Control Group usa hora local Argentina
        )
        planificador.registrar(ingestor_cg, config.CG_INTERVALO)
        logger.info(
            "  ✓ Control Group — cada %ds → destinos: %s",
            config.CG_INTERVALO,
            config.obtener_destinos_del_proveedor("control_group"),
        )
    else:
        logger.info("  — Control Group (desactivado — CONTROL_GROUP_ENABLED=false)")

    logger.info("=" * 60)

    # Iniciar el planificador pasando la función de despacho
    await planificador.iniciar(funcion_despacho=despachar)

    yield  # El servidor corre aquí

    # ── Cierre ordenado ───────────────────────────────────────────────────
    await planificador.detener()
    logger.info("Hub de Integración Satelital — Detenido.")


# =========================================================================== #
# Aplicación FastAPI                                                          #
# =========================================================================== #

app = FastAPI(
    title=config.TITULO_APP,
    version=config.VERSION_APP,
    description=(
        "Hub de Integración Satelital HTTP. "
        "Recibe y/o consulta pulsos GPS de prestadores AVL, "
        "los normaliza y los despacha a Recurso Confiable (SOAP) "
        "y/o Simon 4.0 (REST)."
    ),
    lifespan=ciclo_vida,
)


# =========================================================================== #
# Seguridad                                                                   #
# =========================================================================== #

seguridad = HTTPBearer(auto_error=False)


def verificar_token_ingesta(
    credenciales: HTTPAuthorizationCredentials = Depends(seguridad),
) -> None:
    """
    Valida el token Bearer del proveedor que nos envía datos.
    Si TOKEN_INGESTA está vacío, la validación se omite (modo desarrollo).
    """
    token_esperado = config.TOKEN_INGESTA
    if not token_esperado:
        return  # Sin token configurado = acceso libre (solo desarrollo local)

    if not credenciales or credenciales.credentials != token_esperado:
        logger.warning("[Seguridad] Token inválido — acceso denegado.")
        raise HTTPException(
            status_code=401,
            detail="Token de autenticación inválido o ausente.",
        )


# =========================================================================== #
# Endpoints                                                                   #
# =========================================================================== #

@app.post(
    "/ingresar/{proveedor}",
    status_code=202,
    summary="Recepción de pulsos GPS",
    description=(
        "Recibe eventos GPS de un prestador (modo pasivo). "
        "Responde 202 inmediatamente y procesa en segundo plano. "
        "El destino se resuelve por DESTINOS_{PROVEEDOR} en .env."
    ),
    tags=["Ingesta"],
)
async def ingresar(
    proveedor: str,
    request: Request,
    tareas_fondo: BackgroundTasks,
    _: None = Depends(verificar_token_ingesta),
):
    """
    Endpoint principal de recepción pasiva.

    El parámetro {proveedor} en la URL:
    - Identifica al prestador en los logs y el dashboard
    - Determina a qué destino(s) van sus datos (via DESTINOS_{PROVEEDOR})

    Acepta JSON en dos formatos:
        Evento único:     { "placa": "ABC123", "latitud": -34.5, ... }
        Lote de eventos:  [ {...}, {...}, {...} ]
    """
    try:
        datos_crudos = await request.json()
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="El cuerpo debe ser JSON válido (objeto o lista de objetos).",
        )

    cantidad = len(datos_crudos) if isinstance(datos_crudos, list) else 1
    logger.info("[Ingesta] %d evento(s) recibidos de '%s'.", cantidad, proveedor)

    # Responder 202 inmediatamente — el procesamiento ocurre en segundo plano
    tareas_fondo.add_task(recibir_y_despachar, datos_crudos, proveedor)

    return JSONResponse(
        status_code=202,
        content={
            "estado": "aceptado",
            "mensaje": f"{cantidad} evento(s) recibidos. Procesando en segundo plano.",
            "proveedor": proveedor,
            "modo_prueba": config.MODO_PRUEBA,
        },
    )


@app.get(
    "/metricas",
    summary="Métricas del Hub (JSON)",
    description="Estado en tiempo real. El dashboard lo consulta cada 5 segundos.",
    tags=["Monitoreo"],
)
async def obtener_metricas():
    """Devuelve el estado completo del almacén de métricas."""
    instantanea = almacen_metricas.instantanea()
    instantanea["destinos_activos"] = {
        "recurso_confiable": config.ENVIAR_A_RC,
        "simon": config.ENVIAR_A_SIMON,
    }
    instantanea["modo_prueba"] = config.MODO_PRUEBA
    return JSONResponse(content=instantanea)


@app.get(
    "/dashboard",
    response_class=HTMLResponse,
    summary="Dashboard de Monitoreo",
    description="Interfaz web de monitoreo en tiempo real.",
    tags=["Monitoreo"],
)
async def dashboard():
    """Sirve el dashboard HTML directamente desde el Hub."""
    ruta_dashboard = os.path.join(
        os.path.dirname(__file__), "services", "dashboard.html"
    )
    with open(ruta_dashboard, "r", encoding="utf-8") as archivo:
        contenido_html = archivo.read()
    return HTMLResponse(content=contenido_html)


@app.get(
    "/estado",
    summary="Estado del servicio",
    description="Health check para Railway y balanceadores de carga.",
    tags=["Sistema"],
)
async def estado_servicio():
    """Retorna el estado del Hub y los ingestores activos."""
    return {
        "estado": "activo",
        "servicio": config.TITULO_APP,
        "version": config.VERSION_APP,
        "modo_prueba": config.MODO_PRUEBA,
        "ingestores_activos": list(planificador._ingestores.keys()),
        "destinos": {
            "recurso_confiable": config.ENVIAR_A_RC,
            "simon": config.ENVIAR_A_SIMON,
        },
    }


@app.get("/", include_in_schema=False)
async def raiz():
    """Página raíz con links de navegación."""
    return {
        "servicio": config.TITULO_APP,
        "documentacion": "/docs",
        "estado": "/estado",
        "dashboard": "/dashboard",
    }


# =========================================================================== #
# Arranque local                                                              #
# =========================================================================== #

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=config.PUERTO,
        reload=False,
        log_level=config.NIVEL_LOG.lower(),
    )
