"""
services/despachadores/cliente_simon.py
========================================
Cliente REST para Simon 4.0.

Protocolo: API HubReceptor Simon 4.0 — Alta de AvlRecords

Endpoint destino: POST /ReceiveAvlRecords

Diferencias clave con Recurso Confiable:
    - Protocolo REST/JSON (no SOAP/XML)
    - Token fijo Bearer — Simon lo entrega una sola vez, no expira
    - El cuerpo SIEMPRE es una lista JSON, aunque sea un solo registro
    - Campos adicionales: Alert, User_avl, SourceTag

Nota sobre lat/lon = 0:
    Cuando el GPS no tiene señal, se envía 0.0. Simon lo registra
    como evento sin posición. El registro NUNCA se descarta.
"""

import logging
from typing import Optional

import httpx

from services.estandarizador import RegistroAVL

logger = logging.getLogger(__name__)


def _registro_a_dict_simon(registro: RegistroAVL) -> dict:
    """
    Convierte un RegistroAVL al esquema exacto que espera Simon 4.0.

    Reglas de conversión (esquema Simon pp. 2-3):
    - Latitud y Longitud: float (number/$double). Si son None → 0.0
    - Todos los demás campos: string. None → cadena vacía ""
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
        "Date":         a_texto(registro.fecha),
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
) -> bool:
    """
    Envía una lista de registros AVL al endpoint REST de Simon 4.0.

    El cuerpo del request es SIEMPRE una lista JSON — requerimiento
    explícito del protocolo (p.3), incluso para un solo registro.

    Lotes grandes:
        Si hay más de 100 registros, se dividen en bloques de 100
        para evitar timeouts del servidor.

    Args:
        registros:       Lista de RegistroAVL normalizados.
        url_base:        URL base del HubReceptor Simon (sin /ReceiveAvlRecords).
        usuario_avl:     Override para el campo User_avl de todos los registros.
        etiqueta_origen: Override para el campo SourceTag de todos los registros.
        token_api:       Token Bearer fijo de Simon. Se incluye en el header
                         Authorization si está presente.

    Returns:
        True si todos los bloques se enviaron exitosamente, False si alguno falló.
    """
    if not registros:
        logger.warning("[Simon] despachar() llamado con lista vacía.")
        return False

    if not url_base:
        logger.error("[Simon] SIMON_BASE_URL no configurado. Abortando envío.")
        return False

    endpoint = f"{url_base.rstrip('/')}/ReceiveAvlRecords"

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

    # Convertir al esquema Simon
    carga: list[dict] = [_registro_a_dict_simon(r) for r in registros]

    # Dividir en bloques de 100 para lotes grandes
    TAMANIO_BLOQUE = 100
    bloques = [
        carga[i: i + TAMANIO_BLOQUE]
        for i in range(0, len(carga), TAMANIO_BLOQUE)
    ]

    # Construir encabezados HTTP — incluir Bearer si hay token configurado
    encabezados: dict = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if token_api:
        encabezados["Authorization"] = f"Bearer {token_api}"

    todo_exitoso = True

    for numero_bloque, bloque in enumerate(bloques, start=1):
        logger.debug(
            "[Simon] Enviando bloque %d/%d (%d registros) → %s",
            numero_bloque, len(bloques), len(bloque), endpoint,
        )
        try:
            async with httpx.AsyncClient(timeout=30.0) as cliente:
                respuesta = await cliente.post(endpoint, json=bloque, headers=encabezados)
                respuesta.raise_for_status()

            logger.info(
                "[Simon] Bloque %d/%d enviado. HTTP %d — %d registro(s).",
                numero_bloque, len(bloques), respuesta.status_code, len(bloque),
            )

        except httpx.HTTPStatusError as e:
            logger.error(
                "[Simon] HTTP %d en bloque %d/%d: %s",
                e.response.status_code, numero_bloque, len(bloques), e.response.text[:400],
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
            "[Simon] Envío completo: %d registro(s) en %d bloque(s).",
            len(registros), len(bloques),
        )
    else:
        logger.warning("[Simon] Envío parcial. Revisar logs anteriores.")

    return todo_exitoso
