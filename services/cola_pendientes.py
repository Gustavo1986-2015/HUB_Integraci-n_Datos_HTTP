"""
services/cola_pendientes.py
============================
Cola de reintentos para registros que no pudieron enviarse.

¿Para qué sirve?
    Si RC o Simon no están disponibles cuando intentamos enviar,
    los registros NO se pierden. Se guardan en un archivo JSON
    y se reenvían automáticamente en el próximo ciclo.

¿Cómo funciona?

    Ciclo normal (sin fallas):
        1. Revisar cola → sin pendientes
        2. Enviar registros a RC/Simon → éxito

    Ciclo con falla en el envío:
        1. Enviar a RC → FALLA
        2. Guardar en cola/pendientes_recurso_confiable.json
        3. Próximo ciclo:
           a. Detectar pendientes en cola
           b. Intentar reenviar → si éxito, borrar del archivo
           c. Continuar con los registros nuevos del ciclo

    Hub reiniciado:
        Los archivos de cola persisten en disco.
        Al arrancar el servidor, el próximo ciclo detecta los pendientes.

Retención:
    Los pendientes se intentan reenviar hasta COLA_MAX_HORAS.
    Pasado ese tiempo se descartan (datos demasiado viejos para ser útiles).
    Configurable en .env (por defecto: 24 horas).

Archivos generados:
    cola/pendientes_recurso_confiable.json
    cola/pendientes_simon.json
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from services.estandarizador import RegistroAVL

logger = logging.getLogger(__name__)

CARPETA_COLA = Path("cola")


def _ruta_pendientes(destino: str) -> Path:
    """Retorna la ruta del archivo de cola para un destino."""
    return CARPETA_COLA / f"pendientes_{destino}.json"


def guardar_pendientes(
    registros: list[RegistroAVL],
    destino: str,
    proveedor: str,
) -> None:
    """
    Guarda registros fallidos en la cola para reintento posterior.
    Agrega al archivo existente — no reemplaza registros previos.

    Args:
        registros: Lista de RegistroAVL que no pudieron enviarse.
        destino:   "recurso_confiable" o "simon".
        proveedor: Nombre del proveedor de origen (para trazabilidad).
    """
    if not registros:
        return

    CARPETA_COLA.mkdir(exist_ok=True)
    ruta = _ruta_pendientes(destino)

    entrada = {
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "proveedor": proveedor,
        "destino": destino,
        "cantidad": len(registros),
        "registros": [r.model_dump() for r in registros],
    }

    try:
        with open(ruta, "a", encoding="utf-8") as f:
            f.write(json.dumps(entrada, ensure_ascii=False) + "\n")
        logger.warning(
            "[Cola] %d registro(s) guardados en cola → %s",
            len(registros), ruta.name,
        )
    except Exception as error:
        logger.error("[Cola] Error guardando pendientes en '%s': %s", ruta, error)


def obtener_pendientes(
    destino: str,
    max_horas: int = 24,
) -> tuple[list[RegistroAVL], list[str]]:
    """
    Lee los registros pendientes de la cola para un destino.
    Solo devuelve registros dentro del límite de antigüedad.

    Args:
        destino:   "recurso_confiable" o "simon".
        max_horas: Registros más viejos que esto se descartan.

    Returns:
        Tupla (registros: list[RegistroAVL], proveedores: list[str]).
        Listas vacías si no hay pendientes válidos.
    """
    ruta = _ruta_pendientes(destino)
    if not ruta.exists():
        return [], []

    limite = datetime.now() - timedelta(hours=max_horas)
    registros_pendientes: list[RegistroAVL] = []
    proveedores: list[str] = []
    descartados = 0

    try:
        with open(ruta, "r", encoding="utf-8") as f:
            for linea in f:
                linea = linea.strip()
                if not linea:
                    continue
                try:
                    entrada = json.loads(linea)
                    ts = datetime.strptime(entrada["timestamp"], "%Y-%m-%dT%H:%M:%S")

                    if ts < limite:
                        descartados += entrada.get("cantidad", 0)
                        continue

                    for r_dict in entrada.get("registros", []):
                        registros_pendientes.append(RegistroAVL(**r_dict))

                    proveedor = entrada.get("proveedor", "desconocido")
                    if proveedor not in proveedores:
                        proveedores.append(proveedor)

                except (json.JSONDecodeError, KeyError, ValueError) as e:
                    logger.warning("[Cola] Línea inválida ignorada: %s", e)

    except Exception as error:
        logger.error("[Cola] Error leyendo cola '%s': %s", destino, error)
        return [], []

    if descartados > 0:
        logger.warning(
            "[Cola] %d registro(s) descartados por antigüedad (>%dh).",
            descartados, max_horas,
        )

    if registros_pendientes:
        logger.info(
            "[Cola] %d registro(s) pendientes encontrados para '%s'.",
            len(registros_pendientes), destino,
        )

    return registros_pendientes, proveedores


def limpiar_pendientes(destino: str) -> None:
    """
    Elimina el archivo de cola tras un reintento exitoso.

    Args:
        destino: "recurso_confiable" o "simon".
    """
    ruta = _ruta_pendientes(destino)
    if ruta.exists():
        try:
            ruta.unlink()
            logger.info(
                "[Cola] Cola de '%s' eliminada tras reintento exitoso.", destino
            )
        except Exception as error:
            logger.error("[Cola] Error eliminando cola '%s': %s", destino, error)


def contar_pendientes(destino: str) -> int:
    """
    Cuenta los registros pendientes para un destino.
    Usado en el banner de arranque y en el dashboard.

    Args:
        destino: "recurso_confiable" o "simon".

    Returns:
        Total de registros pendientes. 0 si no hay cola.
    """
    ruta = _ruta_pendientes(destino)
    if not ruta.exists():
        return 0

    total = 0
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            for linea in f:
                if linea.strip():
                    try:
                        total += json.loads(linea).get("cantidad", 0)
                    except (json.JSONDecodeError, KeyError):
                        pass
    except Exception:
        pass

    return total
