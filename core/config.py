"""
core/config.py
==============
Configuración central del Hub.

Todas las credenciales y URLs se leen desde variables de entorno.
Nunca se escriben directamente en el código.

Uso:
    from core.config import obtener_configuracion
    cfg = obtener_configuracion()
    print(cfg.RC_USUARIO)
"""

import os
import logging
from functools import lru_cache

logger = logging.getLogger(__name__)


class Configuracion:
    """
    Contiene todas las variables de configuración del Hub.
    Cada atributo lee su valor desde el entorno (os.getenv).
    Si la variable no existe, usa el valor por defecto indicado.
    """

    # ------------------------------------------------------------------
    # Servidor
    # ------------------------------------------------------------------
    PUERTO: int = int(os.getenv("PORT", "8000"))
    NIVEL_LOG: str = os.getenv("LOG_LEVEL", "INFO")
    TITULO_APP: str = "Hub de Integración Satelital"
    VERSION_APP: str = "2.0.0"

    # ------------------------------------------------------------------
    # Modo prueba local
    # true  = normaliza y loguea, pero NO envía a RC ni Simon
    # false = operación normal
    # ------------------------------------------------------------------
    MODO_PRUEBA: bool = os.getenv("DRY_RUN", "false").lower() == "true"

    # ------------------------------------------------------------------
    # Seguridad
    # Token que los proveedores deben enviar para autenticarse con el Hub
    # Dejar vacío para deshabilitar (solo desarrollo local)
    # ------------------------------------------------------------------
    TOKEN_INGESTA: str = os.getenv("HUB_INGEST_TOKEN", "")

    # ------------------------------------------------------------------
    # Zona horaria para normalización de fechas
    # ------------------------------------------------------------------
    ZONA_HORARIA: str = os.getenv("TIMEZONE_OFFSET", "-05:00")

    # ------------------------------------------------------------------
    # Destino A — Recurso Confiable (SOAP/XML)
    # ------------------------------------------------------------------
    ENVIAR_A_RC: bool = (
        os.getenv("SEND_TO_RECURSO_CONFIABLE", "false").lower() == "true"
    )
    RC_URL_SOAP: str = os.getenv(
        "RC_SOAP_URL",
        "https://gps.rcontrol.com.mx/Tracking/wcf/RCService.svc",
    )
    RC_USUARIO: str = os.getenv("RC_USER_ID", "")
    RC_CLAVE: str = os.getenv("RC_PASSWORD", "")

    # ------------------------------------------------------------------
    # Destino B — Simon 4.0 (REST/JSON)
    # ------------------------------------------------------------------
    ENVIAR_A_SIMON: bool = (
        os.getenv("SEND_TO_SIMON", "false").lower() == "true"
    )
    SIMON_URL_BASE: str = os.getenv("SIMON_BASE_URL", "")
    SIMON_USUARIO_AVL: str = os.getenv("SIMON_USER_AVL", "avl")
    SIMON_ETIQUETA_ORIGEN: str = os.getenv("SIMON_SOURCE_TAG", "")
    # Token fijo que Simon entrega una sola vez — no expira, no hay login
    SIMON_TOKEN_API: str = os.getenv("SIMON_API_TOKEN", "")

    # ------------------------------------------------------------------
    # Ingestor activo — Control Group Gateway
    # ------------------------------------------------------------------
    CG_ACTIVO: bool = (
        os.getenv("CONTROL_GROUP_ENABLED", "false").lower() == "true"
    )
    CG_URL: str = os.getenv(
        "CONTROL_GROUP_URL",
        "https://gateway.control-group.com.ar/gateway.asp",
    )
    CG_USUARIO: str = os.getenv("CONTROL_GROUP_USER", "")
    CG_CLAVE: str = os.getenv("CONTROL_GROUP_PASS", "")
    # Segundos entre cada consulta al gateway (mínimo recomendado: 60)
    CG_INTERVALO: int = int(os.getenv("CONTROL_GROUP_INTERVAL", "60"))

    def obtener_destinos_del_proveedor(self, nombre_proveedor: str) -> list[str]:
        """
        Devuelve la lista de destinos activos para un proveedor específico.

        Sistema de prioridad (de mayor a menor):
          1. DESTINOS_{NOMBRE_PROVEEDOR}  →  configuración específica
             Ejemplos en .env:
               DESTINOS_CONTROL_GROUP=simon
               DESTINOS_MI_PROVEEDOR=recurso_confiable
               DESTINOS_OTRO=recurso_confiable,simon
          2. DESTINOS_DEFAULT  →  fallback para todos los proveedores
          3. Flags ENVIAR_A_RC / ENVIAR_A_SIMON  →  modo básico

        Args:
            nombre_proveedor: Nombre tal como llega en la URL o del ingestor.

        Returns:
            Lista con los destinos activos: ["recurso_confiable"], ["simon"],
            o ["recurso_confiable", "simon"] si van a ambos.
        """
        # Normalizar nombre: mayúsculas, guiones y espacios → guiones bajos
        clave_env = (
            "DESTINOS_"
            + nombre_proveedor.upper().replace("-", "_").replace(" ", "_")
        )
        valor = os.getenv(clave_env, "") or os.getenv("DESTINOS_DEFAULT", "")

        if valor:
            return [d.strip().lower() for d in valor.split(",") if d.strip()]

        # Modo básico: usar los flags individuales
        destinos = []
        if self.ENVIAR_A_RC:
            destinos.append("recurso_confiable")
        if self.ENVIAR_A_SIMON:
            destinos.append("simon")
        return destinos

    def validar(self) -> None:
        """
        Verifica que los destinos activos tengan sus credenciales.
        Emite advertencias en el log si falta algún valor crítico.
        """
        if self.MODO_PRUEBA:
            logger.warning(
                "[Configuración] *** MODO PRUEBA ACTIVO — "
                "No se enviarán datos a ningún destino ***"
            )
        if self.ENVIAR_A_RC:
            if not self.RC_USUARIO or not self.RC_CLAVE:
                logger.warning(
                    "[Configuración] RC activo pero faltan RC_USER_ID o RC_PASSWORD."
                )
        if self.ENVIAR_A_SIMON:
            if not self.SIMON_URL_BASE:
                logger.warning(
                    "[Configuración] Simon activo pero falta SIMON_BASE_URL."
                )
            if not self.SIMON_TOKEN_API:
                logger.warning(
                    "[Configuración] Simon activo pero falta SIMON_API_TOKEN. "
                    "Se enviará sin autenticación Bearer."
                )
        if self.CG_ACTIVO:
            if not self.CG_USUARIO or not self.CG_CLAVE:
                logger.warning(
                    "[Configuración] Control Group activo pero faltan "
                    "CONTROL_GROUP_USER o CONTROL_GROUP_PASS."
                )


@lru_cache(maxsize=1)
def obtener_configuracion() -> Configuracion:
    """
    Devuelve la instancia única de Configuracion.
    Se crea una sola vez al primer llamado (patrón singleton).
    """
    cfg = Configuracion()
    cfg.validar()
    return cfg
