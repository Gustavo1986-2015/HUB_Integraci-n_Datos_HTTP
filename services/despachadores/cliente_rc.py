"""
services/despachadores/cliente_rc.py
=====================================
Cliente SOAP para Recurso Confiable / Iron Tracking.

Protocolo: D-TI-15 v14 — Especificación Técnica Integración Nativa RC

Flujo de trabajo:
    1. ObtenerToken   → Autenticarse con usuario y clave → devuelve token (24 hs)
    2. EnviarPulsos   → Enviar eventos GPS usando el token obtenido

Caché del token:
    El token dura 24 horas. Se almacena en memoria y se renueva
    automáticamente 30 minutos antes de vencer, para evitar fallos
    en el margen exacto de expiración.

Envío en bloque:
    Si llegan múltiples registros, se envían todos juntos en un único
    envelope SOAP con múltiples nodos <iron:Event>. Es la práctica
    recomendada para flotas de más de 2 vehículos (Anexo 1, D-TI-15).
"""

import logging
import re
import httpx
from datetime import datetime, timedelta
from typing import Optional
from xml.sax.saxutils import escape

from services.estandarizador import RegistroAVL

logger = logging.getLogger(__name__)


# =========================================================================== #
# Caché del token SOAP                                                        #
# =========================================================================== #

class _CacheToken:
    """
    Almacena el token SOAP en memoria para reutilizarlo sin
    autenticarse en cada envío. El token dura 24 horas en RC.
    """

    def __init__(self):
        self._token: Optional[str] = None
        self._obtenido_en: Optional[datetime] = None
        self._horas_validez: int = 23      # Renovar 30 min antes de vencer
        self._minutos_validez: int = 30

    def es_valido(self) -> bool:
        """Retorna True si el token existe y aún no expiró."""
        if not self._token or not self._obtenido_en:
            return False
        vencimiento = self._obtenido_en + timedelta(
            hours=self._horas_validez,
            minutes=self._minutos_validez,
        )
        return datetime.utcnow() < vencimiento

    def guardar(self, token: str) -> None:
        """Almacena el nuevo token y registra el momento de obtención."""
        self._token = token
        self._obtenido_en = datetime.utcnow()
        logger.info(
            "[RC] Token almacenado. Válido por ~%dh%dm.",
            self._horas_validez, self._minutos_validez,
        )

    def obtener(self) -> Optional[str]:
        """Devuelve el token si es válido, o None si expiró."""
        return self._token if self.es_valido() else None

    def invalidar(self) -> None:
        """Fuerza la renovación del token en el próximo envío."""
        self._token = None
        self._obtenido_en = None


# Instancia única compartida por todas las llamadas
_cache_token = _CacheToken()


# =========================================================================== #
# Constructores de XML                                                        #
# =========================================================================== #

def _xml_obtener_token(usuario: str, clave: str) -> str:
    """
    Construye el envelope SOAP para ObtenerToken (GetUserToken).
    Referencia: D-TI-15 p.5.
    """
    return f"""<?xml version="1.0" encoding="utf-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                  xmlns:tem="http://tempuri.org/">
    <soapenv:Header/>
    <soapenv:Body>
        <tem:GetUserToken>
            <tem:userId>{escape(usuario)}</tem:userId>
            <tem:password>{escape(clave)}</tem:password>
        </tem:GetUserToken>
    </soapenv:Body>
</soapenv:Envelope>"""


def _xml_nodo_evento(registro: RegistroAVL) -> str:
    """
    Construye un nodo <iron:Event> para un registro AVL.

    Reglas del protocolo RC (D-TI-15 pp. 7-10):
    - Fecha:     Sin offset de timezone (UTC puro: YYYY-MM-DDTHH:MM:SS)
    - Lat/Lon:   Mínimo 6 decimales. Si es None, enviar 0.000000
    - Ignición:  Booleano XML en minúsculas: true / false
    - Campos vacíos: enviar "" o "0" según el tipo

    Nota sobre lat/lon = 0:
        Cuando el GPS no tiene señal, se envía 0.0. RC lo procesa
        como evento sin posición. El registro NUNCA se descarta.
    """
    # Limpiar offset de timezone para RC (requiere UTC puro)
    # Regex elimina cualquier offset: -03:00, -05:00, +00:00, Z
    fecha_sin_offset = re.sub(r"[Zz]$|[+-]\d{2}:\d{2}$", "", registro.fecha or "").strip()

    # Coordenadas: 0.0 si no hay señal GPS (nunca descartamos el registro)
    lat = f"{(registro.latitud or 0.0):.6f}"
    lon = f"{(registro.longitud or 0.0):.6f}"

    # Ignición: convertir a booleano XML
    ignicion_raw = str(registro.ignicion or "0").lower()
    ignicion_xml = "true" if ignicion_raw in ("1", "true", "si", "yes") else "false"

    def seguro(valor) -> str:
        """Convierte None a cadena vacía, escapando caracteres especiales XML."""
        return escape(str(valor)) if valor is not None else ""

    return f"""            <iron:Event>
                <iron:altitude>{seguro(registro.altitud) or "0"}</iron:altitude>
                <iron:asset>{seguro(registro.placa)}</iron:asset>
                <iron:battery>{seguro(registro.bateria) or "0"}</iron:battery>
                <iron:code>{seguro(registro.codigo_evento) or "1"}</iron:code>
                <iron:course>{seguro(registro.rumbo) or "0"}</iron:course>
                <iron:customer>
                    <iron:id></iron:id>
                    <iron:name></iron:name>
                </iron:customer>
                <iron:date>{seguro(fecha_sin_offset)}</iron:date>
                <iron:direction>{seguro(registro.direccion) or "0"}</iron:direction>
                <iron:humidity>{seguro(registro.humedad) or "0"}</iron:humidity>
                <iron:ignition>{ignicion_xml}</iron:ignition>
                <iron:latitude>{lat}</iron:latitude>
                <iron:longitude>{lon}</iron:longitude>
                <iron:odometer>{seguro(registro.odometro) or "0"}</iron:odometer>
                <iron:serialNumber>{seguro(registro.numero_serie) or "0"}</iron:serialNumber>
                <iron:shipment>{seguro(registro.numero_viaje) or "0"}</iron:shipment>
                <iron:speed>{seguro(registro.velocidad) or "0"}</iron:speed>
                <iron:temperature>{seguro(registro.temperatura) or "0"}</iron:temperature>
                <iron:vehicleType>{seguro(registro.tipo_vehiculo)}</iron:vehicleType>
                <iron:vehicleBrand>{seguro(registro.marca_vehiculo)}</iron:vehicleBrand>
                <iron:vehicleModel>{seguro(registro.modelo_vehiculo)}</iron:vehicleModel>
            </iron:Event>"""


def _xml_enviar_pulsos(token: str, registros: list[RegistroAVL]) -> str:
    """
    Construye el envelope SOAP para GPSAssetTracking con envío en bloque.
    Todos los registros se incluyen como nodos <iron:Event> consecutivos.
    Referencia: D-TI-15 pp. 9-14.
    """
    nodos_eventos = "\n".join(_xml_nodo_evento(r) for r in registros)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                  xmlns:tem="http://tempuri.org/"
                  xmlns:iron="http://schemas.datacontract.org/2004/07/IronTracking">
    <soapenv:Header/>
    <soapenv:Body>
        <tem:GPSAssetTracking>
            <tem:token>{escape(token)}</tem:token>
            <tem:events>
{nodos_eventos}
            </tem:events>
        </tem:GPSAssetTracking>
    </soapenv:Body>
</soapenv:Envelope>"""


# =========================================================================== #
# Parsers de respuesta XML                                                    #
# =========================================================================== #

def _extraer_token_de_respuesta(xml: str) -> Optional[str]:
    """
    Extrae el token del XML de respuesta de GetUserToken.
    Retorna None si la autenticación falló (token nil).
    """
    inicio = xml.find("<a:token>")
    fin = xml.find("</a:token>")
    if inicio == -1 or fin == -1:
        if 'i:nil="true"' in xml and "<a:token" in xml:
            logger.error("[RC] Autenticación fallida. Verificar RC_USER_ID y RC_PASSWORD.")
        return None
    return xml[inicio + len("<a:token>"):fin].strip()


def _extraer_id_trabajo(xml: str) -> Optional[str]:
    """
    Extrae el idJob del XML de respuesta de GPSAssetTracking.
    El idJob es el identificador del pulso en Iron Tracking.
    """
    inicio = xml.find("<a:idJob>")
    fin = xml.find("</a:idJob>")
    if inicio == -1 or fin == -1:
        return None
    return xml[inicio + len("<a:idJob>"):fin].strip()


# =========================================================================== #
# Funciones principales                                                       #
# =========================================================================== #

async def _obtener_token(url: str, usuario: str, clave: str) -> Optional[str]:
    """
    Obtiene el token de autenticación SOAP.
    Reutiliza el token del caché si todavía es válido.
    Intenta hasta 2 veces si falla por error de red.
    """
    token_en_cache = _cache_token.obtener()
    if token_en_cache:
        logger.debug("[RC] Reutilizando token del caché.")
        return token_en_cache

    xml_solicitud = _xml_obtener_token(usuario, clave)
    encabezados = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "http://tempuri.org/IRCService/GetUserToken",
    }

    for intento in range(1, 3):
        try:
            async with httpx.AsyncClient(timeout=30.0) as cliente:
                respuesta = await cliente.post(
                    url,
                    content=xml_solicitud.encode("utf-8"),
                    headers=encabezados,
                )
                respuesta.raise_for_status()

            token = _extraer_token_de_respuesta(respuesta.text)
            if token:
                _cache_token.guardar(token)
                return token

            logger.error("[RC] ObtenerToken intento %d: token no encontrado.", intento)
            return None

        except httpx.HTTPStatusError as e:
            logger.error("[RC] ObtenerToken HTTP %d (intento %d): %s",
                         e.response.status_code, intento, e.response.text[:300])
        except httpx.RequestError as e:
            logger.error("[RC] ObtenerToken error de red (intento %d): %s", intento, e)

    return None


async def despachar(
    registros: list[RegistroAVL],
    url: str,
    usuario: str,
    clave: str,
) -> bool:
    """
    Envía una lista de registros AVL al servicio SOAP de Recurso Confiable.

    Proceso:
        1. Obtener token (del caché o solicitando uno nuevo)
        2. Construir XML en bloque con todos los eventos
        3. Enviar a GPSAssetTracking
        4. Si el token expiró (error de auth), invalidar y reintentar una vez

    Args:
        registros: Lista de RegistroAVL normalizados.
        url:       URL del servicio SOAP de RC.
        usuario:   Credencial de usuario.
        clave:     Credencial de contraseña.

    Returns:
        True si el envío fue exitoso, False si falló.
    """
    if not registros:
        logger.warning("[RC] despachar() llamado con lista vacía.")
        return False

    if not usuario or not clave:
        logger.error("[RC] Faltan credenciales (RC_USER_ID / RC_PASSWORD).")
        return False

    encabezados = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "http://tempuri.org/IRCService/GPSAssetTracking",
    }

    for intento in range(1, 3):
        token = await _obtener_token(url, usuario, clave)
        if not token:
            logger.error("[RC] Sin token. Abortando envío (intento %d).", intento)
            return False

        xml_solicitud = _xml_enviar_pulsos(token, registros)

        try:
            async with httpx.AsyncClient(timeout=60.0) as cliente:
                respuesta = await cliente.post(
                    url,
                    content=xml_solicitud.encode("utf-8"),
                    headers=encabezados,
                )
                respuesta.raise_for_status()

            # RC puede devolver HTTP 200 pero con error de auth en el cuerpo (comportamiento SOAP)
            if "USERUNK" in respuesta.text or (
                "incorrecta" in respuesta.text and "Autent" in respuesta.text
            ):
                logger.warning("[RC] Token inválido en respuesta (intento %d). Renovando.", intento)
                _cache_token.invalidar()
                continue

            id_trabajo = _extraer_id_trabajo(respuesta.text)
            logger.info(
                "[RC] Envío exitoso. %d registro(s). idJob=%s",
                len(registros), id_trabajo or "N/D",
            )
            return True

        except httpx.HTTPStatusError as e:
            logger.error("[RC] HTTP %d (intento %d): %s",
                         e.response.status_code, intento, e.response.text[:400])
            if e.response.status_code in (401, 403):
                _cache_token.invalidar()
                continue
            return False

        except httpx.RequestError as e:
            logger.error("[RC] Error de red (intento %d): %s", intento, e)
            return False

    logger.error("[RC] Todos los intentos fallaron.")
    return False
