"""
core/config.py
==============
Configuración central del Hub.

Todas las credenciales y URLs se leen desde variables de entorno.
Nunca se escriben directamente en el código.

Por qué usamos __init__:
    Python evalúa los atributos de clase al momento de importar el módulo.
    Si las variables se definen como atributos de clase (fuera del __init__),
    se leen ANTES de que load_dotenv() pueda cargar el archivo .env.
    Al moverlas dentro del __init__, se leen cuando se instancia la clase,
    que ocurre DESPUÉS de load_dotenv() — garantizando que el .env
    ya esté cargado sin importar el sistema operativo o entorno.

    Este mecanismo funciona igual para cualquier cantidad de proveedores
    o destinos que se agreguen en el futuro.

Uso:
    from core.config import obtener_configuracion
    cfg = obtener_configuracion()
    print(cfg.RC_USUARIO)
"""

import os
import logging
from functools import lru_cache
from dotenv import load_dotenv

# Cargar variables del archivo .env antes de instanciar la configuración
# Esto garantiza que os.getenv() encuentre las variables en cualquier entorno
load_dotenv()

logger = logging.getLogger(__name__)


class Configuracion:
    """
    Contiene todas las variables de configuración del Hub.

    Cada atributo lee su valor desde el entorno (os.getenv) dentro del
    __init__, lo que garantiza que load_dotenv() ya las haya cargado.
    Si la variable no existe en el entorno, se usa el valor por defecto.

    Para agregar un nuevo proveedor o destino:
        1. Agregar sus variables aquí en el __init__
        2. Agregar las variables en .env.example con su documentación
        3. Registrar el ingestor en main.py si es modo activo
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
        # Modo prueba local
        # true  = normaliza y loguea, pero NO envía a RC ni Simon
        # false = operación normal
        # ------------------------------------------------------------------
        self.MODO_PRUEBA: bool = os.getenv("DRY_RUN", "false").lower() == "true"

        # ------------------------------------------------------------------
        # Seguridad
        # Token que los prestadores deben enviar para autenticarse con el Hub
        # Formato del header: Authorization: Bearer <token>
        # Dejar vacío para deshabilitar (solo desarrollo local)
        # ------------------------------------------------------------------
        self.TOKEN_INGESTA: str = os.getenv("HUB_INGEST_TOKEN", "")

        # ------------------------------------------------------------------
        # Zona horaria para normalización de fechas
        # Se agrega a las fechas al normalizarlas
        # Ejemplos: -05:00 (México Centro), -03:00 (Argentina)
        # ------------------------------------------------------------------
        self.ZONA_HORARIA: str = os.getenv("TIMEZONE_OFFSET", "-05:00")

        # ------------------------------------------------------------------
        # Destino A — Recurso Confiable (SOAP/XML)
        # Protocolo: D-TI-15 v14
        # ------------------------------------------------------------------
        self.ENVIAR_A_RC: bool = (
            os.getenv("SEND_TO_RECURSO_CONFIABLE", "false").lower() == "true"
        )
        self.RC_URL_SOAP: str = os.getenv(
            "RC_SOAP_URL",
            "https://gps.rcontrol.com.mx/Tracking/wcf/RCService.svc",
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

        # ------------------------------------------------------------------
        # Ingestor activo — Control Group Gateway
        # Protocolo: XML sobre HTTP (NO SOAP). Revisión: 26/01/2024
        # El Hub consulta el gateway cada CG_INTERVALO segundos
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
        # Segundos entre cada consulta al gateway (mínimo recomendado: 60)
        self.CG_INTERVALO: int = int(os.getenv("CONTROL_GROUP_INTERVAL", "60"))

        # ------------------------------------------------------------------
        # PLANTILLA PARA NUEVO INGESTOR ACTIVO
        # Copiar este bloque y completar para cada nuevo prestador
        # ------------------------------------------------------------------
        # self.NUEVO_ACTIVO: bool = (
        #     os.getenv("NUEVO_ENABLED", "false").lower() == "true"
        # )
        # self.NUEVO_URL: str = os.getenv("NUEVO_URL", "")
        # self.NUEVO_API_KEY: str = os.getenv("NUEVO_API_KEY", "")
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

        Este método funciona igual para cualquier cantidad de proveedores.
        No requiere modificación de código al agregar nuevos proveedores —
        solo agregar la variable DESTINOS_{NOMBRE} en el .env.

        Args:
            nombre_proveedor: Nombre del proveedor (URL o nombre del ingestor).

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
        Se ejecuta automáticamente al instanciar via obtener_configuracion().
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
    La validación de credenciales se ejecuta automáticamente.
    """
    cfg = Configuracion()
    cfg.validar()
    return cfg