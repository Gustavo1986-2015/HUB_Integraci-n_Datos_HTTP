"""
services/ingestores/control_group.py
=====================================
Ingestor activo para el Gateway de Control Group.

Protocolo: XML sobre HTTP (NO SOAP) — Revisión: 26 de Enero de 2024
URL:       https://gateway.control-group.com.ar/gateway.asp
Auth:      Parámetros en la URL: ?usuario=X&clave=Y

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CÓMO FUNCIONA EL GATEWAY DE CONTROL GROUP
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Solicitud: GET /gateway.asp?usuario=X&clave=Y&modo=INCREMENTAL

Modo INCREMENTAL:
    El servidor recuerda el último evento entregado por usuario.
    Cada llamada devuelve SOLO los eventos nuevos desde la anterior.

Estructura XML dinámica:
    <r cantidad="N" zonaHoraria="-03:00">
      <columnas>
        <i id="A" nombre="idRastreable" predeterminado="123456"/>
        <i id="C" nombre="nombre" predeterminado="VJV-247"/>
        <i id="D" nombre="fecha"/>
        <i id="J" nombre="latitud"/>
        <i id="K" nombre="longitud"/>
      </columnas>
      <filas>
        <i C="ABC123" D="2024-01-15 10:30:00" J="-34.54" K="-58.47"/>
      </filas>
    </r>

    IMPORTANTE — IDs dinámicos:
    Los IDs de columna (A, B, C...) pueden cambiar entre versiones.
    Los NOMBRES (nombre, latitud, velocidad...) son constantes.
    El parser construye el mapa dinámicamente en cada respuesta.

    IMPORTANTE — Valores predeterminados:
    Si una fila no trae un atributo, se usa el predeterminado
    declarado en <columnas>. El campo "nombre" (placa) NUNCA es nulo
    según el manual — siempre tiene predeterminado.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REGLA FUNDAMENTAL — NUNCA DESCARTAR REGISTROS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Todos los eventos se procesan y envían aunque:
  - Latitud o longitud sean nulas (GPS sin señal)
  - Las coordenadas sean (0, 0) (fix GPS no válido)

Un evento de pánico, batería baja o alarma es valioso
independientemente de si hay posición GPS en ese momento.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MAPEO: Campos Control Group → RegistroAVL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

 nombre          → placa          (limpia, sin caracteres especiales)
 idRastreable    → numero_serie   (fallback si nombre está vacío)
 fecha           → fecha          (con offset -03:00)
 latitud         → latitud        (None si no hay señal — no descarta)
 longitud        → longitud       (None si no hay señal — no descarta)
 velocidad       → velocidad      (puede ser None)
 rumbo           → rumbo          (puede ser None)
 temperatura     → temperatura    (puede ser None)
 idTipoEvento    → codigo_evento  (0=POSICIÓN, 1=PÁNICO, etc.)
"""

import logging
import xml.etree.ElementTree as ET
from typing import Optional

import httpx

from services.ingestores.base import IngestorBase
from services.estandarizador import RegistroAVL, limpiar_placa

logger = logging.getLogger(__name__)


class IngestorControlGroup(IngestorBase):
    """
    Consulta el Gateway de Control Group en modo INCREMENTAL
    y convierte los eventos al modelo RegistroAVL.
    """

    def __init__(
        self,
        url: str,
        usuario: str,
        clave: str,
        zona_horaria: str = "-03:00",
    ):
        """
        Args:
            url:          URL del gateway
            usuario:      Usuario de acceso
            clave:        Contraseña de acceso
            zona_horaria: Offset del servidor. CG usa -03:00 (hora Argentina)
        """
        self._url = url
        self._usuario = usuario
        self._clave = clave
        self._zona_horaria = zona_horaria

    @property
    def nombre(self) -> str:
        return "control_group"

    async def consultar(self) -> list[RegistroAVL]:
        """
        Ciclo completo de consulta:
            1. GET al gateway en modo INCREMENTAL
            2. Parsear XML con columnas dinámicas
            3. Convertir TODOS los eventos a RegistroAVL
            4. Retornar la lista para despachar
        """
        try:
            xml_texto = await self._pedir_datos()
            if not xml_texto:
                return []

            filas_crudas = self._parsear_xml(xml_texto)
            if not filas_crudas:
                return []

            registros = self._filas_a_registros(filas_crudas)
            logger.info("[CG] Consulta completa: %d registro(s) obtenidos.", len(registros))
            return registros

        except Exception as error:
            logger.error("[CG] Error inesperado en consultar(): %s", error, exc_info=True)
            return []

    # ------------------------------------------------------------------ #
    # Red                                                                 #
    # ------------------------------------------------------------------ #

    async def _pedir_datos(self) -> Optional[str]:
        """
        GET al gateway en modo INCREMENTAL.
        Solo devuelve eventos nuevos desde la última consulta de este usuario.
        """
        parametros = {
            "usuario": self._usuario,
            "clave":   self._clave,
            "modo":    "INCREMENTAL",
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as cliente:
                respuesta = await cliente.get(self._url, params=parametros)
                respuesta.raise_for_status()
            logger.debug("[CG] GET exitoso. HTTP %d — %d bytes.",
                         respuesta.status_code, len(respuesta.content))
            return respuesta.text

        except httpx.HTTPStatusError as e:
            logger.error("[CG] HTTP %d al consultar gateway: %s",
                         e.response.status_code, e.response.text[:300])
        except httpx.RequestError as e:
            logger.error("[CG] Error de red al consultar gateway: %s", e)

        return None

    # ------------------------------------------------------------------ #
    # Parsing XML dinámico                                                #
    # ------------------------------------------------------------------ #

    def _parsear_xml(self, xml_texto: str) -> list[dict]:
        """
        Parsea la respuesta XML con estructura de columnas dinámica.

        Algoritmo:
            1. Leer <columnas> → construir mapa {id_letra → {nombre, predeterminado}}
            2. Leer <filas> → resolver atributos usando el mapa
            3. Si la fila no trae un atributo → usar el predeterminado de la columna
        """
        try:
            raiz = ET.fromstring(xml_texto.strip())
        except ET.ParseError as error:
            logger.error("[CG] Error al parsear XML: %s. Inicio: %s",
                         error, xml_texto[:200])
            return []

        if raiz.get("advertencia") == "1":
            logger.warning("[CG] Advertencia del servidor: %s",
                           raiz.get("mensaje", "sin detalle"))

        cantidad = int(raiz.get("cantidad", "0"))
        if cantidad == 0:
            logger.debug("[CG] Sin eventos nuevos (cantidad=0).")
            return []

        zona_horaria = raiz.get("zonaHoraria", self._zona_horaria)

        # Paso 1: Mapa {id_letra → {nombre, predeterminado}}
        mapa_columnas: dict[str, dict] = {}
        elemento_columnas = raiz.find("columnas")
        if elemento_columnas is None:
            logger.error("[CG] Elemento <columnas> no encontrado.")
            return []

        for columna in elemento_columnas.findall("i"):
            id_col = columna.get("id")
            nombre_col = columna.get("nombre")
            defecto_col = columna.get("predeterminado")  # Puede ser None si no se declaró
            if id_col and nombre_col:
                mapa_columnas[id_col] = {
                    "nombre": nombre_col,
                    "predeterminado": defecto_col,
                }

        logger.debug("[CG] Columnas mapeadas: %s",
                     {k: v["nombre"] for k, v in mapa_columnas.items()})

        # Paso 2: Parsear filas
        elemento_filas = raiz.find("filas")
        if elemento_filas is None:
            logger.warning("[CG] Elemento <filas> no encontrado.")
            return []

        filas: list[dict] = []
        for fila in elemento_filas.findall("i"):
            registro_fila: dict = {}
            for id_col, info_col in mapa_columnas.items():
                # Si la fila no trae el atributo → usar predeterminado de columna
                # Si tampoco hay predeterminado → None (según manual CG)
                valor = fila.get(id_col, info_col["predeterminado"])
                registro_fila[info_col["nombre"]] = valor
            registro_fila["_zona_horaria"] = zona_horaria
            filas.append(registro_fila)

        return filas

    # ------------------------------------------------------------------ #
    # Conversión a RegistroAVL                                           #
    # ------------------------------------------------------------------ #

    def _filas_a_registros(self, filas: list[dict]) -> list[RegistroAVL]:
        """
        Convierte los dicts crudos del gateway a instancias RegistroAVL.

        REGLA FUNDAMENTAL: NUNCA se descarta un registro.

        Placa:
            1. Intentar usar el campo "nombre" (patente/dominio)
            2. Si está vacío, usar "idRastreable" como fallback
            3. Limpiar la placa: sin espacios, guiones ni caracteres especiales

        Lat/Lon:
            Si son None o inválidos → se asigna None (no se descarta el registro)
            Los despachadores enviarán 0.0 al destino final en esos casos.
        """
        resultado: list[RegistroAVL] = []

        for indice, fila in enumerate(filas):

            # --- Placa: nombre → idRastreable → None ---
            # "nombre" es NUNCA NULO según el manual, pero por seguridad
            # usamos idRastreable como fallback si nombre está vacío
            placa_cruda = fila.get("nombre") or fila.get("idRastreable")
            placa_limpia = limpiar_placa(placa_cruda)

            if not placa_limpia:
                logger.debug(
                    "[CG] Fila %d: sin placa identificable (nombre='%s', id='%s'). "
                    "Se usará 'SIN_PLACA'.",
                    indice, fila.get("nombre"), fila.get("idRastreable"),
                )
                placa_limpia = "SINPLACA"

            # --- Latitud y Longitud: None si no hay señal (NO descarta) ---
            lat_cruda = fila.get("latitud")
            lon_cruda = fila.get("longitud")

            try:
                latitud = float(lat_cruda) if lat_cruda is not None else None
            except (ValueError, TypeError):
                logger.debug("[CG] Fila %d: latitud '%s' inválida → None.", indice, lat_cruda)
                latitud = None

            try:
                longitud = float(lon_cruda) if lon_cruda is not None else None
            except (ValueError, TypeError):
                logger.debug("[CG] Fila %d: longitud '%s' inválida → None.", indice, lon_cruda)
                longitud = None

            if latitud is None or longitud is None:
                logger.debug(
                    "[CG] Fila %d (placa=%s): sin posición GPS. El registro se procesa igual.",
                    indice, placa_limpia,
                )

            # --- Fecha con zona horaria del servidor ---
            fecha_formateada = self._formatear_fecha(
                fila.get("fecha", ""),
                fila.get("_zona_horaria", self._zona_horaria),
            )

            try:
                registro = RegistroAVL(
                    placa=placa_limpia,
                    numero_serie=str(fila.get("idRastreable") or ""),
                    latitud=latitud,
                    longitud=longitud,
                    fecha=fecha_formateada,
                    velocidad=str(fila["velocidad"]) if fila.get("velocidad") is not None else None,
                    rumbo=str(fila["rumbo"]) if fila.get("rumbo") is not None else None,
                    temperatura=str(fila["temperatura"]) if fila.get("temperatura") is not None else None,
                    codigo_evento=str(fila.get("idTipoEvento", "0")),
                    usuario_avl="control_group",
                    etiqueta_origen="cg_gateway",
                )
                resultado.append(registro)

            except Exception as error:
                logger.warning("[CG] Error creando RegistroAVL para fila %d: %s", indice, error)

        return resultado

    # ------------------------------------------------------------------ #
    # Utilidad de fechas                                                  #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _formatear_fecha(fecha_cruda: str, zona_horaria: str) -> Optional[str]:
        """
        Convierte la fecha del gateway CG al formato ISO 8601 con offset.

        CG devuelve fechas con ESPACIO: "2024-01-15 10:30:00"
        Resultado:                      "2024-01-15T10:30:00-03:00"
        """
        if not fecha_cruda or not str(fecha_cruda).strip():
            return None

        fecha_iso = str(fecha_cruda).strip().replace(" ", "T")

        # Agregar offset si la fecha tiene exactamente 19 caracteres (sin timezone)
        if len(fecha_iso) == 19:
            fecha_iso = f"{fecha_iso}{zona_horaria}"

        return fecha_iso
