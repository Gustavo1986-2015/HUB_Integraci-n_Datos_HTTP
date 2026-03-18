"""
services/logger_archivo.py
===========================
Sistema de logs en archivo JSON para auditoría del Hub.

Genera un archivo por día en la carpeta logs/:
    logs/hub_2026-03-18.json

Cada línea es un evento JSON independiente (formato JSONL).

Hay dos tipos de entradas:
    - "ingesta":  un registro por cada placa recibida con todos sus datos
    - "despacho": resumen del lote enviado al destino con resultado

Esto permite auditar:
    - Qué datos exactos tenía cada placa en cada momento
    - Si el envío fue exitoso o falló
    - Trazabilidad completa: desde el origen hasta el destino

Retención configurable:
    LOG_RETENTION_HOURS en .env (por defecto 48 horas)
    Al arrancar el servidor, borra automáticamente los archivos viejos.
"""

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.estandarizador import RegistroAVL

logger = logging.getLogger(__name__)

CARPETA_LOGS = Path("logs")


def _ruta_archivo_hoy() -> Path:
    """Retorna la ruta del archivo de log del día actual."""
    nombre = f"hub_{datetime.now().strftime('%Y-%m-%d')}.json"
    return CARPETA_LOGS / nombre


def _escribir(evento: dict) -> None:
    """
    Escribe una línea JSON en el archivo del día actual.
    Si la carpeta no existe, la crea automáticamente.
    """
    try:
        CARPETA_LOGS.mkdir(exist_ok=True)
        with open(_ruta_archivo_hoy(), "a", encoding="utf-8") as f:
            f.write(json.dumps(evento, ensure_ascii=False) + "\n")
    except Exception as error:
        logger.error("[Logger] Error escribiendo log: %s", error)


def registrar_ingesta(
    proveedor: str,
    cantidad: int,
    modo: str,
    registros: list,
) -> None:
    """
    Registra la llegada de datos — un registro JSON por cada placa.

    Cada línea del archivo contendrá todos los datos disponibles
    de esa placa en ese momento: posición, velocidad, evento, etc.

    Args:
        proveedor: Nombre del proveedor de origen.
        cantidad:  Total de registros recibidos en el lote.
        modo:      "activo" (polling) o "pasivo" (nos envían).
        registros: Lista de RegistroAVL con todos los datos.
    """
    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    # Un registro de resumen del lote
    _escribir({
        "timestamp": timestamp,
        "tipo": "ingesta_lote",
        "proveedor": proveedor,
        "modo": modo,
        "cantidad_total": cantidad,
    })

    # Un registro por cada placa con todos sus datos
    for r in registros:
        _escribir({
            "timestamp": timestamp,
            "tipo": "ingesta",
            "proveedor": proveedor,
            "modo": modo,
            # Identificación
            "placa": r.placa,
            "numero_serie": r.numero_serie,
            # Posición
            "latitud": r.latitud,
            "longitud": r.longitud,
            "altitud": r.altitud,
            # Movimiento
            "velocidad": r.velocidad,
            "rumbo": r.rumbo,
            "direccion": r.direccion,
            # Estado
            "fecha": r.fecha,
            "ignicion": r.ignicion,
            "codigo_evento": r.codigo_evento,
            "alerta": r.alerta,
            # Sensores
            "temperatura": r.temperatura,
            "humedad": r.humedad,
            "bateria": r.bateria,
            # Odómetro
            "odometro": r.odometro,
            # Viaje
            "numero_viaje": r.numero_viaje,
            # Vehículo
            "tipo_vehiculo": r.tipo_vehiculo,
            "marca_vehiculo": r.marca_vehiculo,
            "modelo_vehiculo": r.modelo_vehiculo,
        })


def registrar_despacho(
    proveedor: str,
    destino: str,
    cantidad: int,
    exitoso: bool,
    id_trabajo: str = "",
    error: str = "",
    registros: list = None,
) -> None:
    """
    Registra el resultado del envío a un destino.

    Guarda un resumen del lote (no repite todos los datos de cada
    placa — eso ya quedó registrado en registrar_ingesta).

    Args:
        proveedor:  Nombre del proveedor de origen.
        destino:    "recurso_confiable" o "simon".
        cantidad:   Cantidad de registros enviados.
        exitoso:    True si el envío fue exitoso.
        id_trabajo: idJob devuelto por RC (si aplica).
        error:      Mensaje de error (si aplica).
        registros:  Lista de RegistroAVL (solo se guarda la placa para referencia).
    """
    placas = [r.placa for r in (registros or []) if r.placa]

    _escribir({
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "tipo": "despacho",
        "proveedor": proveedor,
        "destino": destino,
        "cantidad": cantidad,
        "resultado": "exitoso" if exitoso else "fallido",
        "id_trabajo": id_trabajo,
        "error": error,
        "placas": placas[:50],  # Referencias para cruzar con los registros de ingesta
    })


def registrar_error(
    proveedor: str,
    etapa: str,
    mensaje: str,
) -> None:
    """
    Registra un error en cualquier etapa del proceso.

    Args:
        proveedor: Nombre del proveedor involucrado.
        etapa:     "normalizacion", "despacho_rc", "despacho_simon", etc.
        mensaje:   Descripción del error.
    """
    _escribir({
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "tipo": "error",
        "proveedor": proveedor,
        "etapa": etapa,
        "mensaje": mensaje,
    })


def limpiar_logs_viejos(horas_retencion: int = 48) -> None:
    """
    Elimina archivos de log más antiguos que N horas.
    Se llama automáticamente al arrancar el servidor.

    Args:
        horas_retencion: Archivos más viejos que esto se eliminan.
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
                logger.info("[Logger] Archivo eliminado: %s", archivo.name)
        except Exception as error:
            logger.warning("[Logger] No se pudo procesar %s: %s", archivo.name, error)

    if eliminados > 0:
        logger.info("[Logger] %d archivo(s) de log eliminados (retención: %dh).",
                    eliminados, horas_retencion)
    else:
        logger.info("[Logger] Logs verificados. Retención: %dh.", horas_retencion)
