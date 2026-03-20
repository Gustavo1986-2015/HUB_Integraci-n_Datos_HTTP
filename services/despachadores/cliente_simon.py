"""
services/despachadores/cliente_simon.py
========================================
Cliente REST para Simon 4.0.

Protocolo: API HubReceptor Simon 4.0

Endpoint destino: URL completa configurada en SIMON_BASE_URL
Ejemplo: https://simon-pre-webapi.assistcargo.com/RPAAvlRecord/Add

Diferencias clave con Recurso Confiable:
    - Protocolo REST/JSON (no SOAP/XML)
    - Token Bearer opcional — Simon lo entrega una sola vez, no expira
    - El cuerpo SIEMPRE es una lista JSON, aunque sea un solo registro

Zona horaria:
    Simon requiere fechas en hora LOCAL del prestador (no UTC).
    Se usa SIMON_TIMEZONE_OFFSET del .env (por defecto: -03:00 Argentina).
    El offset se reemplaza en la fecha antes de enviar.

Nota sobre lat/lon = 0:
    Cuando el GPS no tiene señal, se envía 0.0. Simon lo registra
    como evento sin posición. El registro NUNCA se descarta.
"""

import logging
import re
from typing import Optional

import httpx

from services.estandarizador import RegistroAVL

logger = logging.getLogger(__name__)


def _ajustar_fecha_simon(fecha: Optional[str], zona_horaria_simon: str) -> str:
    """
    Convierte la fecha al formato que requiere Simon:
    hora local del prestador con el offset de SIMON_TIMEZONE_OFFSET.

    Simon 4.0 requiere hora local, NO UTC.
    RC requiere UTC. Por eso los offsets son distintos.

    Proceso:
        "2026-03-18T13:00:00+00:00"  →  "2026-03-18T13:00:00-03:00"
        "2026-03-18T13:00:00"        →  "2026-03-18T13:00:00-03:00"

    Args:
        fecha:              Fecha normalizada (ISO 8601).
        zona_horaria_simon: Offset local del prestador (ej: "-03:00").

    Returns:
        Fecha con el offset correcto para Simon.
    """
    if not fecha:
        return ""

    # Eliminar cualquier offset existente y reemplazar con el de Simon
    fecha_sin_offset = re.sub(r"[Zz]$|[+-]\d{2}:\d{2}$", "", str(fecha)).strip()
    return f"{fecha_sin_offset}{zona_horaria_simon}"


def _registro_a_dict_simon(
    registro: RegistroAVL,
    zona_horaria_simon: str = "-03:00",
) -> dict:
    """
    Convierte un RegistroAVL al esquema exacto que espera Simon 4.0.

    Reglas:
    - Latitud y Longitud: float. Si son None → 0.0
    - Todos los demás campos: string. None → ""
    - Date: en hora local con offset SIMON_TIMEZONE_OFFSET
    - Los nombres de campos deben coincidir exactamente con el protocolo Simon
    """

    def a_texto(valor) -> str:
        """None → "" — todo lo demás como string."""
        return str(valor) if valor is not None else ""

    return {
        "Altitude":     a_texto(registro.altitud),
        "Asset":        a_texto(registro.placa),
        "Battery":      a_texto(registro.bateria),
        "Alert":        a_texto(registro.alerta),
        "Code":         a_texto(registro.codigo_evento),
        "Course":       a_texto(registro.rumbo),
        "Date":         _ajustar_fecha_simon(registro.fecha, zona_horaria_simon),
        "Direction":    a_texto(registro.direccion),
        "Humidity":     a_texto(registro.humedad),
        "Ignition":     a_texto(registro.ignicion),
        "Latitude":     registro.latitud if registro.latitud is not None else 0.0,
        "Longitude":    registro.longitud if registro.longitud is not None else 0.0,
        "Odometer":     a_texto(registro.odometro),
        "SerialNumber": a_texto(registro.numero_serie),
        "Shipment":     a_texto(registro.numero_viaje),
        "Speed":        a_texto(registro.velocidad),
        "User_avl":     a_texto(registro.usuario_avl),
        "SourceTag":    a_texto(registro.etiqueta_origen),
    }


async def despachar(
    registros: list[RegistroAVL],
    url_base: str,
    usuario_avl: Optional[str] = None,
    etiqueta_origen: Optional[str] = None,
    token_api: Optional[str] = None,
    zona_horaria_simon: str = "-03:00",
    integration_key: Optional[str] = None,
) -> bool:
    """
    Envía una lista de registros AVL al endpoint REST de Simon 4.0.

    El cuerpo del request es SIEMPRE una lista JSON — incluso para un solo registro.

    Lotes grandes:
        Si hay más de 100 registros, se dividen en bloques de 100
        para evitar timeouts del servidor.

    Args:
        registros:           Lista de RegistroAVL normalizados.
        url_base:            URL completa del endpoint Simon.
                             Ejemplo: https://simon-pre.../RPAAvlRecord/Add
        usuario_avl:         Override para el campo User_avl.
        etiqueta_origen:     Override para el campo SourceTag.
        token_api:           Token Bearer. Incluido en Authorization si presente.
        zona_horaria_simon:  Offset de hora local para las fechas.
                             Simon requiere hora local, no UTC.

    Returns:
        True si todos los bloques se enviaron correctamente, False si alguno falló.
    """
    if not registros:
        logger.warning("[Simon] despachar() llamado con lista vacía.")
        return False

    if not url_base:
        logger.error("[Simon] SIMON_BASE_URL no configurado. Abortando envío.")
        return False

    # La URL configurada ES el endpoint completo — no agregar sufijos
    endpoint = url_base.rstrip("/")

    # Aplicar overrides de metadatos si se proporcionaron
    if usuario_avl or etiqueta_origen:
        registros = [
            r.model_copy(update={
                k: v for k, v in {
                    "usuario_avl": usuario_avl,
                    "etiqueta_origen": etiqueta_origen,
                }.items()
                if v is not None
            })
            for r in registros
        ]

    # Convertir al esquema Simon con el offset correcto
    carga: list[dict] = [
        _registro_a_dict_simon(r, zona_horaria_simon) for r in registros
    ]

    # Dividir en bloques de 100 para lotes grandes
    TAMANIO_BLOQUE = 100
    bloques = [
        carga[i: i + TAMANIO_BLOQUE]
        for i in range(0, len(carga), TAMANIO_BLOQUE)
    ]

    # Construir encabezados
    encabezados: dict = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if token_api:
        encabezados["Authorization"] = f"Bearer {token_api}"
    if integration_key:
        # Simon puede requerir la integration key como header o parámetro
        encabezados["X-Integration-Key"] = integration_key
        encabezados["IntegrationKey"] = integration_key

    todo_exitoso = True

    for numero_bloque, bloque in enumerate(bloques, start=1):
        logger.debug(
            "[Simon] Bloque %d/%d (%d registros) → %s",
            numero_bloque, len(bloques), len(bloque), endpoint,
        )
        try:
            async with httpx.AsyncClient(timeout=30.0) as cliente:
                respuesta = await cliente.post(
                    endpoint, json=bloque, headers=encabezados
                )
                respuesta.raise_for_status()

            logger.info(
                "[Simon] Bloque %d/%d enviado. HTTP %d — %d registro(s).",
                numero_bloque, len(bloques),
                respuesta.status_code, len(bloque),
            )

        except httpx.HTTPStatusError as e:
            logger.error(
                "[Simon] HTTP %d en bloque %d/%d: %s",
                e.response.status_code, numero_bloque, len(bloques),
                e.response.text[:400],
            )
            todo_exitoso = False

        except httpx.RequestError as e:
            logger.error(
                "[Simon] Error de red en bloque %d/%d: %s",
                numero_bloque, len(bloques), e,
            )
            todo_exitoso = False

    if todo_exitoso:
        logger.info(
            "[Simon] Envío completo: %d registro(s) en %d bloque(s). "
            "Offset fecha: %s",
            len(registros), len(bloques), zona_horaria_simon,
        )
    else:
        logger.warning("[Simon] Envío parcial. Revisar logs anteriores.")

    return todo_exitoso
