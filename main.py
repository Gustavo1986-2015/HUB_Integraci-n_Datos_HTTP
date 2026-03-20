"""
main.py
=======
Punto de entrada del Hub de Integración Satelital.

Modos de operación:

    PASIVO — El prestador nos envía datos:
        Prestador → POST /ingresar/{proveedor} → normalizar → despachar

    ACTIVO — Nosotros consultamos la API del prestador:
        Planificador → ingestores/control_group.py → normalizar → despachar

    PRUEBA — Sin envíos reales (DRY_RUN=true en .env):
        Igual que los modos anteriores pero sin llamadas HTTP a destinos.

Cola de reintentos:
    Si un envío falla, los registros se guardan en cola/pendientes_*.json.
    En el próximo ciclo se reintenta el envío ANTES de procesar datos nuevos.
    Los archivos de cola persisten aunque el Hub se reinicie.

Endpoints:
    POST /ingresar/{proveedor}   — Recepción de pulsos (modo pasivo)
    GET  /metricas               — Métricas JSON para el dashboard
    GET  /dashboard              — Dashboard de monitoreo
    GET  /configuracion          — UI de configuración (protegida)
    GET  /configuracion/datos    — Leer .env como JSON
    POST /configuracion/guardar  — Guardar nuevas variables en .env
    GET  /estado                 — Health check para Railway
"""

import logging
import os
import sys
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, BackgroundTasks, HTTPException, Request, Depends
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.security import (
    HTTPBearer, HTTPAuthorizationCredentials,
    HTTPBasic, HTTPBasicCredentials,
)

from core.config import obtener_configuracion
from services.estandarizador import normalizar_carga, RegistroAVL
from services.metricas import almacen as almacen_metricas
from services.planificador import planificador
from services.logger_archivo import (
    registrar_ingesta as log_ingesta,
    registrar_despacho as log_despacho,
    registrar_error as log_error,
    limpiar_logs_viejos,
)
from services.cola_pendientes import (
    guardar_pendientes,
    obtener_pendientes,
    limpiar_pendientes,
    contar_pendientes,
)

# =========================================================================== #
# Logging de consola                                                          #
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
# =========================================================================== #

async def despachar(registros: list[RegistroAVL], nombre_proveedor: str) -> None:
    """
    Envía los registros a los destinos configurados para el proveedor.

    Antes de enviar datos nuevos, verifica si hay registros pendientes
    de reintentar de ciclos anteriores. Si los hay, los envía primero.
    Si el envío nuevo falla, guarda en la cola para el próximo ciclo.

    Routing (prioridad):
        1. DESTINOS_{PROVEEDOR} en .env
        2. DESTINOS_DEFAULT en .env
        3. Flags ENVIAR_A_RC / ENVIAR_A_SIMON

    DRY_RUN=true: normaliza, loguea y registra métricas sin enviar.
    """
    if not registros:
        return

    destinos = config.obtener_destinos_del_proveedor(nombre_proveedor)
    placas = [r.placa for r in registros if r.placa]

    # Registrar métricas para ingestores activos (planificador)
    if nombre_proveedor in list(planificador._ingestores.keys()):
        almacen_metricas.registrar_ingesta(
            nombre_proveedor, len(registros), len(registros), placas
        )

    if not destinos:
        logger.warning(
            "[Despacho] '%s': sin destinos configurados. "
            "Setear DESTINOS_%s o DESTINOS_DEFAULT en .env",
            nombre_proveedor,
            nombre_proveedor.upper().replace("-", "_"),
        )
        return

    origen = "activo" if nombre_proveedor in list(planificador._ingestores.keys()) else "pasivo"
    logger.info(
        "[Ingesta] ► Recibido de '%s' — %d registro(s) [modo %s]",
        nombre_proveedor, len(registros), origen,
    )
    logger.info("[Despacho] '%s' → destinos: %s", nombre_proveedor, destinos)

    # Guardar en log de auditoría — un registro completo por placa
    log_ingesta(nombre_proveedor, len(registros), origen, registros)

    # ── Modo prueba ──────────────────────────────────────────────────────
    if config.MODO_PRUEBA:
        logger.warning(
            "[MODO PRUEBA] *** SIMULADO para '%s': %d registros → %s ***",
            nombre_proveedor, len(registros), destinos,
        )
        for destino in destinos:
            if destino in ("recurso_confiable", "simon"):
                almacen_metricas.registrar_despacho(destino, len(registros), True)
                log_despacho(nombre_proveedor, destino, len(registros), True,
                             id_trabajo="SIMULADO", registros=registros)
        return

    # ── Envío real a Recurso Confiable ───────────────────────────────────
    if "recurso_confiable" in destinos:
        await _despachar_con_cola_rc(registros, nombre_proveedor)

    # ── Envío real a Simon 4.0 ───────────────────────────────────────────
    if "simon" in destinos:
        await _despachar_con_cola_simon(registros, nombre_proveedor)


async def _despachar_con_cola_rc(
    registros: list[RegistroAVL],
    nombre_proveedor: str,
) -> None:
    """
    Envía a Recurso Confiable con gestión de cola de reintentos.

    Flujo:
        1. Si hay pendientes en cola → intentar reenviar primero
        2. Enviar los registros nuevos del ciclo actual
        3. Si falla → guardar en cola para el próximo ciclo
    """
    from services.despachadores.cliente_rc import despachar as enviar_rc

    try:
        # Paso 1: Reintentar pendientes de ciclos anteriores
        pendientes, proveedores_pendientes = obtener_pendientes(
            "recurso_confiable",
            max_horas=config.COLA_MAX_HORAS,
        )
        if pendientes:
            logger.info(
                "[Cola→RC] Reintentando %d registro(s) pendientes.",
                len(pendientes),
            )
            exito_reintento, id_reintento = await enviar_rc(
                registros=pendientes,
                url=config.RC_URL_SOAP,
                usuario=config.RC_USUARIO,
                clave=config.RC_CLAVE,
            )
            if exito_reintento:
                limpiar_pendientes("recurso_confiable")
                log_despacho(
                    proveedores_pendientes[0] if proveedores_pendientes else "cola",
                    "recurso_confiable", len(pendientes), True,
                    id_trabajo=id_reintento,
                )
                logger.info(
                    "[Cola→RC] Reintento exitoso: %d registro(s) — idJob=%s",
                    len(pendientes), id_reintento,
                )
                almacen_metricas.registrar_despacho(
                    "recurso_confiable", len(pendientes), True
                )
            else:
                logger.warning(
                    "[Cola→RC] Reintento fallido. Los %d registro(s) siguen en cola.",
                    len(pendientes),
                )

        # Paso 2: Enviar los registros nuevos del ciclo
        exito, id_trabajo = await enviar_rc(
            registros=registros,
            url=config.RC_URL_SOAP,
            usuario=config.RC_USUARIO,
            clave=config.RC_CLAVE,
        )
        almacen_metricas.registrar_despacho(
            "recurso_confiable", len(registros), exito,
            mensaje_error=None if exito else "Ver logs del servidor",
        )

        if exito:
            log_despacho(nombre_proveedor, "recurso_confiable", len(registros),
                         True, id_trabajo=id_trabajo, registros=registros)
            logger.info(
                "[Despacho] RC — ✓ Éxito — idJob=%s", id_trabajo
            )
        else:
            # Fallo: guardar en cola para el próximo ciclo
            guardar_pendientes(registros, "recurso_confiable", nombre_proveedor)
            log_despacho(nombre_proveedor, "recurso_confiable", len(registros),
                         False, registros=registros)
            logger.warning(
                "[Despacho] RC — ✗ Fallo — %d registro(s) encolados para reintento.",
                len(registros),
            )

    except Exception as error:
        # Error inesperado: guardar en cola
        almacen_metricas.registrar_despacho(
            "recurso_confiable", len(registros), False, str(error)
        )
        guardar_pendientes(registros, "recurso_confiable", nombre_proveedor)
        log_error(nombre_proveedor, "despacho_rc", str(error))
        logger.error(
            "[Despacho] Error enviando a RC: %s — %d registro(s) encolados.",
            error, len(registros),
        )


async def _despachar_con_cola_simon(
    registros: list[RegistroAVL],
    nombre_proveedor: str,
) -> None:
    """
    Envía a Simon 4.0 con gestión de cola de reintentos.
    Mismo flujo que RC: reintentar pendientes → enviar nuevos → encolar si falla.
    """
    from services.despachadores.cliente_simon import despachar as enviar_simon

    try:
        # Paso 1: Reintentar pendientes
        pendientes, proveedores_pendientes = obtener_pendientes(
            "simon",
            max_horas=config.COLA_MAX_HORAS,
        )
        if pendientes:
            logger.info(
                "[Cola→Simon] Reintentando %d registro(s) pendientes.",
                len(pendientes),
            )
            exito_reintento = await enviar_simon(
                registros=pendientes,
                url_base=config.SIMON_URL_BASE,
                usuario_avl=config.SIMON_USUARIO_AVL,
                etiqueta_origen=config.SIMON_ETIQUETA_ORIGEN,
                token_api=config.SIMON_TOKEN_API,
                zona_horaria_simon=config.SIMON_ZONA_HORARIA,
                integration_key=config.SIMON_INTEGRATION_KEY,
            )
            if exito_reintento:
                limpiar_pendientes("simon")
                logger.info(
                    "[Cola→Simon] Reintento exitoso: %d registro(s).",
                    len(pendientes),
                )
                almacen_metricas.registrar_despacho("simon", len(pendientes), True)
            else:
                logger.warning(
                    "[Cola→Simon] Reintento fallido. Los %d registro(s) siguen en cola.",
                    len(pendientes),
                )

        # Paso 2: Enviar registros nuevos
        exito = await enviar_simon(
            registros=registros,
            url_base=config.SIMON_URL_BASE,
            usuario_avl=config.SIMON_USUARIO_AVL,
            etiqueta_origen=config.SIMON_ETIQUETA_ORIGEN,
            token_api=config.SIMON_TOKEN_API,
            zona_horaria_simon=config.SIMON_ZONA_HORARIA,
            integration_key=config.SIMON_INTEGRATION_KEY,
        )
        almacen_metricas.registrar_despacho(
            "simon", len(registros), exito,
            mensaje_error=None if exito else "Ver logs del servidor",
        )

        if exito:
            log_despacho(nombre_proveedor, "simon", len(registros),
                         True, registros=registros)
            logger.info("[Despacho] Simon — ✓ Éxito")
        else:
            guardar_pendientes(registros, "simon", nombre_proveedor)
            log_despacho(nombre_proveedor, "simon", len(registros),
                         False, registros=registros)
            logger.warning(
                "[Despacho] Simon — ✗ Fallo — %d registro(s) encolados.",
                len(registros),
            )

    except Exception as error:
        almacen_metricas.registrar_despacho("simon", len(registros), False, str(error))
        guardar_pendientes(registros, "simon", nombre_proveedor)
        log_error(nombre_proveedor, "despacho_simon", str(error))
        logger.error(
            "[Despacho] Error enviando a Simon: %s — %d registro(s) encolados.",
            error, len(registros),
        )


# =========================================================================== #
# Pipeline de ingesta pasiva                                                  #
# =========================================================================== #

async def recibir_y_despachar(datos_crudos: Any, nombre_proveedor: str) -> None:
    """
    Normaliza el payload recibido en /ingresar y lo despacha.
    Corre como BackgroundTask — el proveedor ya recibió su 202.
    """
    cantidad_cruda = len(datos_crudos) if isinstance(datos_crudos, list) else 1
    logger.info(
        "[Ingesta] ► Recibido de '%s' — %d evento(s) [modo pasivo]",
        nombre_proveedor, cantidad_cruda,
    )

    try:
        registros = normalizar_carga(
            datos_crudos,
            zona_horaria=config.ZONA_HORARIA,
            usuario_avl_defecto=config.SIMON_USUARIO_AVL,
            etiqueta_origen_defecto=config.SIMON_ETIQUETA_ORIGEN,
        )
    except Exception as error:
        logger.error("[Ingesta] Error normalizando datos de '%s': %s", nombre_proveedor, error)
        almacen_metricas.registrar_ingesta(nombre_proveedor, cantidad_cruda, 0, [])
        log_error(nombre_proveedor, "normalizacion", str(error))
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
# Lifespan                                                                    #
# =========================================================================== #

@asynccontextmanager
async def ciclo_vida(app: FastAPI):
    """
    Startup:
        - Limpia logs viejos
        - Muestra pendientes en cola (si los hay)
        - Registra ingestores activos
        - Arranca el planificador

    Shutdown:
        - Detiene el planificador limpiamente
    """
    logger.info("=" * 60)
    logger.info("Hub de Integración Satelital — Iniciando...")

    if config.MODO_PRUEBA:
        logger.warning("*** MODO PRUEBA ACTIVO — Sin envíos reales ***")

    # Destinos activos
    logger.info("Destinos configurados:")
    logger.info("  RC:    %s", "✓ Activo" if config.ENVIAR_A_RC else "— Inactivo")
    logger.info("  Simon: %s", "✓ Activo" if config.ENVIAR_A_SIMON else "— Inactivo")

    # Verificar cola de pendientes al arrancar
    for destino in ["recurso_confiable", "simon"]:
        cantidad = contar_pendientes(destino)
        if cantidad > 0:
            logger.warning(
                "  ⚠ Cola '%s': %d registro(s) pendientes de reintento.",
                destino, cantidad,
            )

    # Limpiar logs viejos
    limpiar_logs_viejos(horas_retencion=config.LOG_RETENTION_HOURS)

    # Registrar ingestores activos
    logger.info("Ingestores activos:")
    if config.CG_ACTIVO:
        from services.ingestores.control_group import IngestorControlGroup
        ingestor_cg = IngestorControlGroup(
            url=config.CG_URL,
            usuario=config.CG_USUARIO,
            clave=config.CG_CLAVE,
            zona_horaria="-03:00",
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

    await planificador.iniciar(funcion_despacho=despachar)
    yield
    await planificador.detener()
    logger.info("Hub de Integración Satelital — Detenido.")


# =========================================================================== #
# FastAPI                                                                     #
# =========================================================================== #

app = FastAPI(
    title=config.TITULO_APP,
    version=config.VERSION_APP,
    description=(
        "Hub de Integración Satelital HTTP. "
        "Recibe y/o consulta pulsos GPS de prestadores AVL, "
        "los normaliza y los despacha a Recurso Confiable (SOAP) "
        "y/o Simon 4.0 (REST). Cola de reintentos automática."
    ),
    docs_url=None,
    redoc_url=None,
    lifespan=ciclo_vida,
)

# ── Seguridad — ingesta ──────────────────────────────────────────────────────
seguridad_bearer = HTTPBearer(auto_error=False)
seguridad_basic = HTTPBasic(auto_error=False)


def verificar_token_ingesta(
    credenciales: HTTPAuthorizationCredentials = Depends(seguridad_bearer),
) -> None:
    """Valida el Bearer token del prestador. Libre si TOKEN_INGESTA está vacío."""
    token_esperado = config.TOKEN_INGESTA
    if not token_esperado:
        return
    if not credenciales or credenciales.credentials != token_esperado:
        logger.warning("[Seguridad] Token de ingesta inválido.")
        raise HTTPException(
            status_code=401,
            detail="Token de autenticación inválido o ausente.",
        )


def verificar_acceso_config(
    credenciales: HTTPBasicCredentials = Depends(seguridad_basic),
) -> None:
    """
    Protege /configuracion con HTTP Basic Auth.
    Libre si CONFIG_USUARIO y CONFIG_CLAVE están vacíos (desarrollo local).
    En producción SIEMPRE configurar estas variables.
    """
    usuario_esperado = config.CONFIG_USUARIO
    clave_esperada = config.CONFIG_CLAVE

    if not usuario_esperado and not clave_esperada:
        return  # Sin protección en local

    if not credenciales:
        raise HTTPException(
            status_code=401,
            detail="Acceso denegado.",
            headers={"WWW-Authenticate": "Basic"},
        )

    usuario_ok = secrets.compare_digest(
        credenciales.username.encode(), usuario_esperado.encode()
    )
    clave_ok = secrets.compare_digest(
        credenciales.password.encode(), clave_esperada.encode()
    )

    if not usuario_ok or not clave_ok:
        raise HTTPException(
            status_code=401,
            detail="Usuario o contraseña incorrectos.",
            headers={"WWW-Authenticate": "Basic"},
        )


# =========================================================================== #
# Endpoints                                                                   #
# =========================================================================== #

@app.post("/ingresar/{proveedor}", status_code=202, tags=["Ingesta"],
          summary="Recepción de pulsos GPS")
async def ingresar(
    proveedor: str,
    request: Request,
    tareas_fondo: BackgroundTasks,
    _: None = Depends(verificar_token_ingesta),
):
    """
    Recibe eventos GPS de un prestador (modo pasivo).
    Responde 202 inmediatamente — el procesamiento ocurre en segundo plano.
    """
    try:
        datos_crudos = await request.json()
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="El cuerpo debe ser JSON válido (objeto o lista).",
        )

    cantidad = len(datos_crudos) if isinstance(datos_crudos, list) else 1
    logger.info("[Ingesta] %d evento(s) recibidos de '%s'.", cantidad, proveedor)
    tareas_fondo.add_task(recibir_y_despachar, datos_crudos, proveedor)

    return JSONResponse(status_code=202, content={
        "estado": "aceptado",
        "mensaje": f"{cantidad} evento(s) recibidos. Procesando en segundo plano.",
        "proveedor": proveedor,
        "modo_prueba": config.MODO_PRUEBA,
    })


@app.get("/metricas", tags=["Monitoreo"], summary="Métricas JSON")
async def obtener_metricas():
    """Snapshot de métricas en tiempo real. Consumido por el dashboard cada 5s."""
    snapshot = almacen_metricas.instantanea()
    snapshot["destinos_activos"] = {
        "recurso_confiable": config.ENVIAR_A_RC,
        "simon": config.ENVIAR_A_SIMON,
    }
    snapshot["modo_prueba"] = config.MODO_PRUEBA
    # Incluir estado de la cola para el dashboard
    snapshot["cola_pendientes"] = {
        "recurso_confiable": contar_pendientes("recurso_confiable"),
        "simon": contar_pendientes("simon"),
    }
    return JSONResponse(content=snapshot)


@app.get("/dashboard", response_class=HTMLResponse, tags=["Monitoreo"],
         summary="Dashboard de monitoreo")
async def dashboard():
    """Panel de monitoreo en tiempo real."""
    ruta = os.path.join(os.path.dirname(__file__), "services", "dashboard.html")
    with open(ruta, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.get("/configuracion", response_class=HTMLResponse, tags=["Configuración"],
         summary="UI de configuración")
async def pagina_configuracion(_: None = Depends(verificar_acceso_config)):
    """Interfaz web para configurar el Hub sin editar el .env manualmente."""
    ruta = os.path.join(os.path.dirname(__file__), "services", "configuracion.html")
    with open(ruta, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.get("/configuracion/datos", tags=["Configuración"],
         summary="Leer configuración actual")
async def leer_configuracion(_: None = Depends(verificar_acceso_config)):
    """Lee el .env y devuelve las variables como JSON para la UI."""
    ruta_env = Path(".env")
    datos: dict = {}
    if ruta_env.exists():
        with open(ruta_env, "r", encoding="utf-8") as f:
            for linea in f:
                linea = linea.strip()
                if linea and not linea.startswith("#") and "=" in linea:
                    clave, _, valor = linea.partition("=")
                    datos[clave.strip()] = valor.strip()
    return JSONResponse(content=datos)


@app.post("/configuracion/guardar", tags=["Configuración"],
          summary="Guardar configuración")
async def guardar_configuracion(
    request: Request,
    _: None = Depends(verificar_acceso_config),
):
    """
    Recibe el dict de configuración desde la UI y escribe el .env.
    El servidor debe reiniciarse para aplicar los cambios.
    """
    try:
        nuevos_datos: dict = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="JSON inválido.")

    ruta_env = Path(".env")
    lineas_actuales: list[str] = []
    if ruta_env.exists():
        with open(ruta_env, "r", encoding="utf-8") as f:
            lineas_actuales = f.readlines()

    claves_actualizadas = set()
    nuevas_lineas: list[str] = []

    for linea in lineas_actuales:
        stripped = linea.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            clave = stripped.split("=")[0].strip()
            if clave in nuevos_datos:
                nuevas_lineas.append(f"{clave}={nuevos_datos[clave]}\n")
                claves_actualizadas.add(clave)
            else:
                nuevas_lineas.append(linea)
        else:
            nuevas_lineas.append(linea)

    for clave, valor in nuevos_datos.items():
        if clave not in claves_actualizadas:
            nuevas_lineas.append(f"{clave}={valor}\n")

    with open(ruta_env, "w", encoding="utf-8") as f:
        f.writelines(nuevas_lineas)

    logger.info("[Configuración] .env actualizado con %d variable(s).", len(nuevos_datos))
    return JSONResponse(content={
        "estado": "guardado",
        "mensaje": "Configuración guardada. Reiniciá el servidor para aplicar los cambios.",
        "variables_guardadas": len(nuevos_datos),
    })


@app.get("/estado", tags=["Sistema"], summary="Estado del servicio")
async def estado_servicio():
    """Health check con estado de ingestores y cola de pendientes."""
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
        "cola_pendientes": {
            "recurso_confiable": contar_pendientes("recurso_confiable"),
            "simon": contar_pendientes("simon"),
        },
    }


@app.get("/", include_in_schema=False)
async def raiz():
    return {
        "servicio": config.TITULO_APP,
        "dashboard": "/dashboard",
        "configuracion": "/configuracion",
        "estado": "/estado",
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
