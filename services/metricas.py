"""
services/metricas.py
=====================
Almacén de métricas en memoria para el dashboard de monitoreo.

Las métricas viven en RAM mientras el proceso está activo.
Al reiniciar el servidor (nuevo deploy en Railway), los contadores se resetean.
Esto es suficiente para monitoreo operativo en tiempo real.

El store es un singleton de módulo: se instancia una sola vez al importar.
"""

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

MAXIMO_EVENTOS_RECIENTES = 200


# =========================================================================== #
# Estructuras de datos                                                        #
# =========================================================================== #

@dataclass
class EstadisticasDestino:
    """Contadores de envíos para un destino final (RC o Simon)."""
    nombre: str
    total_enviados: int = 0
    total_fallidos: int = 0
    total_bloques_ok: int = 0
    total_bloques_fallidos: int = 0
    ultimo_envio_ok: Optional[str] = None
    ultimo_envio_fallido: Optional[str] = None
    ultimo_error: Optional[str] = None

    @property
    def tasa_exito(self) -> float:
        """Porcentaje de registros enviados exitosamente."""
        total = self.total_enviados + self.total_fallidos
        if total == 0:
            return 0.0
        return round((self.total_enviados / total) * 100, 1)


@dataclass
class EstadisticasProveedor:
    """Estadísticas acumuladas por proveedor AVL."""
    nombre: str
    total_recibidos: int = 0
    total_normalizados: int = 0
    total_fallidos_normalizacion: int = 0
    primera_vez_visto: Optional[str] = None
    ultima_vez_visto: Optional[str] = None
    placas_recientes: list = field(default_factory=list)


@dataclass
class EntradaActividad:
    """Una entrada del log de actividad del dashboard."""
    timestamp: str
    nivel: str        # "info" | "advertencia" | "error"
    proveedor: str
    mensaje: str
    cantidad_registros: int = 0


# =========================================================================== #
# Store principal                                                             #
# =========================================================================== #

class AlmacenMetricas:
    """
    Almacén central de todas las métricas del Hub.
    Instanciado una sola vez al importar el módulo.
    """

    def __init__(self):
        self.proveedores: dict[str, EstadisticasProveedor] = {}
        self.destinos: dict[str, EstadisticasDestino] = {
            "recurso_confiable": EstadisticasDestino(nombre="Recurso Confiable"),
            "simon":             EstadisticasDestino(nombre="Simon 4.0"),
        }
        self.log_actividad: deque[EntradaActividad] = deque(maxlen=MAXIMO_EVENTOS_RECIENTES)
        self.hub_iniciado_en: str = _ahora()
        self.total_ingestados: int = 0
        self.total_despachados_ok: int = 0
        self.total_despachados_fallidos: int = 0

    def registrar_ingesta(
        self,
        proveedor: str,
        cantidad_recibidos: int,
        cantidad_normalizados: int,
        placas: list[str],
    ) -> None:
        """
        Registra la recepción y normalización de un lote de pulsos.

        Args:
            proveedor:             Nombre del proveedor.
            cantidad_recibidos:    Registros en el payload crudo.
            cantidad_normalizados: Registros que pasaron normalización.
            placas:                Lista de placas presentes en el lote.
        """
        ahora = _ahora()
        fallidos_normalizacion = cantidad_recibidos - cantidad_normalizados

        if proveedor not in self.proveedores:
            self.proveedores[proveedor] = EstadisticasProveedor(
                nombre=proveedor, primera_vez_visto=ahora
            )

        p = self.proveedores[proveedor]
        p.total_recibidos += cantidad_recibidos
        p.total_normalizados += cantidad_normalizados
        p.total_fallidos_normalizacion += fallidos_normalizacion
        p.ultima_vez_visto = ahora

        # Mantener lista de placas recientes (sin duplicados, máximo 10)
        for placa in placas:
            if placa and placa not in p.placas_recientes:
                p.placas_recientes.insert(0, placa)
        p.placas_recientes = p.placas_recientes[:10]

        self.total_ingestados += cantidad_recibidos

        nivel = "advertencia" if fallidos_normalizacion > 0 else "info"
        mensaje = (
            f"{cantidad_normalizados}/{cantidad_recibidos} registros normalizados"
            + (f" ({fallidos_normalizacion} fallidos)" if fallidos_normalizacion > 0 else "")
        )
        self._agregar_actividad(nivel, proveedor, mensaje, cantidad_normalizados)

    def registrar_despacho(
        self,
        destino: str,
        cantidad: int,
        exitoso: bool,
        mensaje_error: Optional[str] = None,
    ) -> None:
        """
        Registra el resultado de un envío a un destino final.

        Args:
            destino:        "recurso_confiable" o "simon".
            cantidad:       Registros en el lote.
            exitoso:        True si el envío fue exitoso.
            mensaje_error:  Detalle del error (solo si exitoso=False).
        """
        ahora = _ahora()
        dest = self.destinos.get(destino)
        if not dest:
            logger.warning("[Métricas] Destino desconocido: %s", destino)
            return

        if exitoso:
            dest.total_enviados += cantidad
            dest.total_bloques_ok += 1
            dest.ultimo_envio_ok = ahora
            self.total_despachados_ok += cantidad
            self._agregar_actividad(
                "info", destino,
                f"✓ {cantidad} registros enviados a {dest.nombre}",
                cantidad,
            )
        else:
            dest.total_fallidos += cantidad
            dest.total_bloques_fallidos += 1
            dest.ultimo_envio_fallido = ahora
            dest.ultimo_error = mensaje_error or "Error desconocido"
            self.total_despachados_fallidos += cantidad
            self._agregar_actividad(
                "error", destino,
                f"✗ Fallo enviando {cantidad} registros a {dest.nombre}: "
                f"{mensaje_error or 'ver logs'}",
                cantidad,
            )

    def instantanea(self) -> dict:
        """
        Devuelve el estado actual completo para el dashboard.
        El dashboard llama a este método cada 5 segundos via /metricas.
        """
        return {
            "hub": {
                "iniciado_en": self.hub_iniciado_en,
                "tiempo_activo": _tiempo_activo(self.hub_iniciado_en),
                "total_ingestados": self.total_ingestados,
                "total_despachados_ok": self.total_despachados_ok,
                "total_despachados_fallidos": self.total_despachados_fallidos,
            },
            "proveedores": [
                {
                    "nombre": p.nombre,
                    "total_recibidos": p.total_recibidos,
                    "total_normalizados": p.total_normalizados,
                    "total_fallidos_normalizacion": p.total_fallidos_normalizacion,
                    "primera_vez_visto": p.primera_vez_visto,
                    "ultima_vez_visto": p.ultima_vez_visto,
                    "placas_recientes": p.placas_recientes,
                }
                for p in self.proveedores.values()
            ],
            "destinos": [
                {
                    "nombre": d.nombre,
                    "clave": k,
                    "total_enviados": d.total_enviados,
                    "total_fallidos": d.total_fallidos,
                    "total_bloques_ok": d.total_bloques_ok,
                    "total_bloques_fallidos": d.total_bloques_fallidos,
                    "tasa_exito": d.tasa_exito,
                    "ultimo_envio_ok": d.ultimo_envio_ok,
                    "ultimo_envio_fallido": d.ultimo_envio_fallido,
                    "ultimo_error": d.ultimo_error,
                }
                for k, d in self.destinos.items()
            ],
            "actividad": [
                {
                    "timestamp": e.timestamp,
                    "nivel": e.nivel,
                    "proveedor": e.proveedor,
                    "mensaje": e.mensaje,
                    "cantidad_registros": e.cantidad_registros,
                }
                for e in reversed(self.log_actividad)
            ],
        }

    def _agregar_actividad(
        self, nivel: str, proveedor: str, mensaje: str, cantidad: int = 0
    ) -> None:
        """Agrega una entrada al log de actividad del dashboard."""
        self.log_actividad.append(
            EntradaActividad(
                timestamp=_ahora(),
                nivel=nivel,
                proveedor=proveedor,
                mensaje=mensaje,
                cantidad_registros=cantidad,
            )
        )


# =========================================================================== #
# Utilidades de tiempo                                                        #
# =========================================================================== #

def _ahora() -> str:
    """Retorna el timestamp actual en formato ISO 8601."""
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _tiempo_activo(iniciado_en: str) -> str:
    """
    Calcula el tiempo transcurrido desde el arranque en formato legible.
    Ejemplos: "5m", "2h 15m", "3d 4h"
    """
    try:
        inicio = datetime.strptime(iniciado_en, "%Y-%m-%dT%H:%M:%SZ")
        delta = datetime.utcnow() - inicio
        segundos_total = int(delta.total_seconds())
        dias, resto = divmod(segundos_total, 86400)
        horas, resto = divmod(resto, 3600)
        minutos, _ = divmod(resto, 60)

        if dias > 0:
            return f"{dias}d {horas}h"
        if horas > 0:
            return f"{horas}h {minutos}m"
        return f"{minutos}m"
    except Exception:
        return "—"


# Instancia global (singleton de módulo)
almacen = AlmacenMetricas()
