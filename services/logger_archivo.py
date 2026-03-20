"""
services/logger_archivo.py
===========================
Sistema de logs en archivo JSON para auditoría del Hub.

Genera un archivo por día en la carpeta logs/:
    logs/hub_2026-03-18.json

Cada línea es un evento JSON independiente (formato JSONL).

Tipos de entradas:
    - ingesta_lote:  resumen del lote (1 línea por ciclo)
    - ingesta:       un registro por placa con todos sus datos
    - despacho:      resultado del envío con idJob
    - error:         fallo en alguna etapa

Rendimiento:
    Toda escritura se hace en una ÚNICA apertura de archivo por llamada.
    Esto evita bloquear el event loop de asyncio cuando hay miles de registros.
    Con 10.000 registros, se abre el archivo una sola vez, se escriben
    todas las líneas en buffer y se cierra — en vez de 10.001 aperturas.

Retención:
    Configurable con LOG_RETENTION_HOURS en .env (por defecto 48 horas).
    Los archivos viejos se eliminan automáticamente al arrancar el servidor.
"""

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

CARPETA_LOGS = Path("logs")


def _ruta_archivo_hoy() -> Path:
    return CARPETA_LOGS / f"hub_{datetime.now().strftime('%Y-%m-%d')}.json"


def _escribir_lineas(lineas: list[str]) -> None:
    """
    Escribe múltiples líneas JSON en el archivo del día actual.
    Abre y cierra el archivo UNA SOLA VEZ para todo el lote.
    Esto es crítico para no bloquear el event loop con miles de registros.
    """
    if not lineas:
        return
    try:
        CARPETA_LOGS.mkdir(exist_ok=True)
        with open(_ruta_archivo_hoy(), "a", encoding="utf-8") as f:
            f.writelines(lineas)
    except Exception as error:
        logger.error("[Logger] Error escribiendo log: %s", error)


def registrar_ingesta(
    proveedor: str,
    cantidad: int,
    modo: str,
    registros: list,
) -> None:
    """
    Registra la llegada de datos — un JSON por placa, en una sola escritura.

    Args:
        proveedor: Nombre del proveedor de origen.
        cantidad:  Total de registros en el lote.
        modo:      "activo" (polling) o "pasivo" (nos envían).
        registros: Lista de RegistroAVL con todos los datos.
    """
    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    lineas: list[str] = []

    # 1 línea de resumen del lote
    lineas.append(json.dumps({
        "timestamp": timestamp,
        "tipo": "ingesta_lote",
        "proveedor": proveedor,
        "modo": modo,
        "cantidad_total": cantidad,
    }, ensure_ascii=False) + "\n")

    # 1 línea por placa con todos sus datos
    for r in registros:
        lineas.append(json.dumps({
            "timestamp": timestamp,
            "tipo": "ingesta",
            "proveedor": proveedor,
            "modo": modo,
            "placa": r.placa,
            "numero_serie": r.numero_serie,
            "latitud": r.latitud,
            "longitud": r.longitud,
            "altitud": r.altitud,
            "velocidad": r.velocidad,
            "rumbo": r.rumbo,
            "direccion": r.direccion,
            "fecha": r.fecha,
            "ignicion": r.ignicion,
            "codigo_evento": r.codigo_evento,
            "alerta": r.alerta,
            "temperatura": r.temperatura,
            "humedad": r.humedad,
            "bateria": r.bateria,
            "odometro": r.odometro,
            "numero_viaje": r.numero_viaje,
            "tipo_vehiculo": r.tipo_vehiculo,
            "marca_vehiculo": r.marca_vehiculo,
            "modelo_vehiculo": r.modelo_vehiculo,
        }, ensure_ascii=False) + "\n")

    # UNA sola apertura de archivo para todo el lote
    _escribir_lineas(lineas)


def registrar_despacho(
    proveedor: str,
    destino: str,
    cantidad: int,
    exitoso: bool,
    id_trabajo: str = "",
    error: str = "",
    registros: list = None,
) -> None:
    """Registra el resultado del envío a un destino."""
    placas = [r.placa for r in (registros or []) if r.placa]
    _escribir_lineas([json.dumps({
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "tipo": "despacho",
        "proveedor": proveedor,
        "destino": destino,
        "cantidad": cantidad,
        "resultado": "exitoso" if exitoso else "fallido",
        "id_trabajo": id_trabajo,
        "error": error,
        "placas": placas[:50],
    }, ensure_ascii=False) + "\n"])


def registrar_error(
    proveedor: str,
    etapa: str,
    mensaje: str,
) -> None:
    """Registra un error en cualquier etapa del proceso."""
    _escribir_lineas([json.dumps({
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "tipo": "error",
        "proveedor": proveedor,
        "etapa": etapa,
        "mensaje": mensaje,
    }, ensure_ascii=False) + "\n"])


def limpiar_logs_viejos(horas_retencion: int = 48) -> None:
    """
    Elimina archivos de log más antiguos que N horas.
    Se llama automáticamente al arrancar el servidor.
    """
    if not CARPETA_LOGS.exists():
        return

    limite = datetime.now() - timedelta(hours=horas_retencion)
    eliminados = 0

    for archivo in CARPETA_LOGS.glob("hub_*.json"):
        try:
            fecha_str = archivo.stem.replace("hub_", "")
            fecha_archivo = datetime.strptime(fecha_str, "%Y-%m-%d")
            if fecha_archivo < limite:
                archivo.unlink()
                eliminados += 1
        except Exception as error:
            logger.warning("[Logger] No se pudo procesar %s: %s", archivo.name, error)

    if eliminados > 0:
        logger.info("[Logger] %d archivo(s) de log eliminados (retención: %dh).",
                    eliminados, horas_retencion)
    else:
        logger.info("[Logger] Logs verificados. Retención: %dh.", horas_retencion)
