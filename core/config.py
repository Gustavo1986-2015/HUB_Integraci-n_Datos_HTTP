"""
core/config.py
==============
Configuración central del Hub.

Todas las credenciales y URLs se leen desde variables de entorno.
Nunca se escriben directamente en el código.

Por qué usamos __init__:
    Python evalúa los atributos de clase al importar el módulo,
    ANTES de que load_dotenv() cargue el .env.
    Al leerlos en __init__, se leen al instanciar la clase,
    garantizando que el .env ya esté disponible.
    Funciona igual para cualquier cantidad de proveedores futuros.
"""

import os
import logging
from functools import lru_cache
from dotenv import load_dotenv

# Cargar .env antes de instanciar la configuración
load_dotenv()

logger = logging.getLogger(__name__)


class Configuracion:
    """
    Contiene todas las variables de configuración del Hub.
    Se leen en __init__ para garantizar que load_dotenv() ya las haya cargado.
    """

    def __init__(self):

        # ------------------------------------------------------------------
        # Servidor
        # ------------------------------------------------------------------
        self.PUERTO: int = int(os.getenv("PORT", "8000"))
        self.NIVEL_LOG: str = os.getenv("LOG_LEVEL", "INFO")
        self.TITULO_APP: str = "Hub de Integración Satelital"
        self.VERSION_APP: str = "2.0.0"

        # ------------------------------------------------------------------
        # Logs en archivo
        # Horas que se conservan los archivos de log antes de eliminarse
        # ------------------------------------------------------------------
        self.LOG_RETENTION_HOURS: int = int(os.getenv("LOG_RETENTION_HOURS", "48"))

        # ------------------------------------------------------------------
        # Modo prueba local
        # true  = normaliza y loguea, pero NO envía a RC ni Simon
        # false = operación normal
        # ------------------------------------------------------------------
        self.MODO_PRUEBA: bool = os.getenv("DRY_RUN", "false").lower() == "true"

        # ------------------------------------------------------------------
        # Seguridad — ingesta
        # Token que los prestadores deben enviar al enviarnos datos.
        # Formato del header: Authorization: Bearer <token>
        # Dejar vacío para deshabilitar (solo desarrollo local)
        # ------------------------------------------------------------------
        self.TOKEN_INGESTA: str = os.getenv("HUB_INGEST_TOKEN", "")

        # ------------------------------------------------------------------
        # Seguridad — UI de configuración (/configuracion)
        # Usuario y contraseña para acceder al panel de configuración.
        # Dejar vacíos en desarrollo local (sin autenticación).
        # En producción SIEMPRE configurar estos valores.
        # ------------------------------------------------------------------
        self.CONFIG_USUARIO: str = os.getenv("CONFIG_USUARIO", "")
        self.CONFIG_CLAVE: str = os.getenv("CONFIG_CLAVE", "")

        # ------------------------------------------------------------------
        # Zona horaria para normalización de fechas
        #
        # RC_TIMEZONE_OFFSET:
        #   RC requiere fechas en UTC puro (sin offset).
        #   Default: +00:00 (UTC)
        #
        # SIMON_TIMEZONE_OFFSET:
        #   Simon requiere fechas en hora local del prestador.
        #   Default: -03:00 (Argentina)
        #
        # Los ingestores y el estandarizador usan RC_TIMEZONE_OFFSET
        # para normalizar fechas. El cliente de Simon aplica su propio
        # offset antes de enviar.
        # ------------------------------------------------------------------
        self.ZONA_HORARIA: str = os.getenv("RC_TIMEZONE_OFFSET", "+00:00")
        self.SIMON_ZONA_HORARIA: str = os.getenv("SIMON_TIMEZONE_OFFSET", "-03:00")

        # ------------------------------------------------------------------
        # Destino A — Recurso Confiable (SOAP/XML)
        # Protocolo: D-TI-15 v14
        # Credenciales: solicitar a soporte@recursoconfiable.com
        # ------------------------------------------------------------------
        self.ENVIAR_A_RC: bool = (
            os.getenv("SEND_TO_RECURSO_CONFIABLE", "false").lower() == "true"
        )
        self.RC_URL_SOAP: str = os.getenv(
            "RC_SOAP_URL",
            "http://gps.rcontrol.com.mx/Tracking/wcf/RCService.svc",
        )
        self.RC_USUARIO: str = os.getenv("RC_USER_ID", "")
        self.RC_CLAVE: str = os.getenv("RC_PASSWORD", "")

        # ------------------------------------------------------------------
        # Destino B — Simon 4.0 (REST/JSON)
        # Token Bearer fijo: Simon lo entrega una sola vez, no expira
        # ------------------------------------------------------------------
        self.ENVIAR_A_SIMON: bool = (
            os.getenv("SEND_TO_SIMON", "false").lower() == "true"
        )
        self.SIMON_URL_BASE: str = os.getenv("SIMON_BASE_URL", "")
        self.SIMON_USUARIO_AVL: str = os.getenv("SIMON_USER_AVL", "avl")
        self.SIMON_ETIQUETA_ORIGEN: str = os.getenv("SIMON_SOURCE_TAG", "")
        self.SIMON_TOKEN_API: str = os.getenv("SIMON_API_TOKEN", "")
        # Clave de integración que algunos endpoints de Simon requieren
        self.SIMON_INTEGRATION_KEY: str = os.getenv("SIMON_INTEGRATION_KEY", "")
        # Zona horaria para las fechas enviadas a Simon (hora local del prestador)
        # Simon 4.0 requiere hora local, no UTC
        self.SIMON_ZONA_HORARIA: str = os.getenv("SIMON_TIMEZONE_OFFSET", "-03:00")

        # ------------------------------------------------------------------
        # Ingestor activo — Control Group Gateway
        # Protocolo: XML sobre HTTP (NO SOAP). Revisión: 26/01/2024
        # Consulta automática cada CG_INTERVALO segundos
        # ------------------------------------------------------------------
        self.CG_ACTIVO: bool = (
            os.getenv("CONTROL_GROUP_ENABLED", "false").lower() == "true"
        )
        self.CG_URL: str = os.getenv(
            "CONTROL_GROUP_URL",
            "https://gateway.control-group.com.ar/gateway.asp",
        )
        self.CG_USUARIO: str = os.getenv("CONTROL_GROUP_USER", "")
        self.CG_CLAVE: str = os.getenv("CONTROL_GROUP_PASS", "")
        self.CG_INTERVALO: int = int(os.getenv("CONTROL_GROUP_INTERVAL", "60"))

        # ------------------------------------------------------------------
        # Cola de reintentos
        # Horas máximas que un registro puede esperar en cola para reenvío.
        # Pasado este tiempo se descarta (datos demasiado viejos).
        # ------------------------------------------------------------------
        self.COLA_MAX_HORAS: int = int(os.getenv("COLA_MAX_HORAS", "24"))

        # ------------------------------------------------------------------
        # PLANTILLA PARA NUEVO INGESTOR ACTIVO
        # Copiar este bloque para cada nuevo prestador cuya API consultamos
        # ------------------------------------------------------------------
        # self.NUEVO_ACTIVO: bool = os.getenv("NUEVO_ENABLED", "false").lower() == "true"
        # self.NUEVO_URL: str = os.getenv("NUEVO_URL", "")
        # self.NUEVO_USUARIO: str = os.getenv("NUEVO_USER", "")
        # self.NUEVO_CLAVE: str = os.getenv("NUEVO_PASS", "")
        # self.NUEVO_INTERVALO: int = int(os.getenv("NUEVO_INTERVAL", "60"))

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

        No requiere modificación de código al agregar nuevos proveedores.
        Solo agregar DESTINOS_{NOMBRE} en el .env.
        """
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
        Verifica que los destinos activos tengan credenciales configuradas.
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
        if self.CONFIG_USUARIO or self.CONFIG_CLAVE:
            logger.info(
                "[Configuración] UI de configuración protegida con usuario/clave."
            )
        else:
            logger.warning(
                "[Configuración] UI de configuración SIN protección. "
                "Configurar CONFIG_USUARIO y CONFIG_CLAVE para producción."
            )


@lru_cache(maxsize=1)
def obtener_configuracion() -> Configuracion:
    """
    Devuelve la instancia única de Configuracion (patrón singleton).
    La validación de credenciales se ejecuta automáticamente.
    """
    cfg = Configuracion()
    cfg.validar()
    return cfg
