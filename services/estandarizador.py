"""
services/estandarizador.py
===========================
Motor de normalización de datos.

Responsabilidad única:
    Recibir un diccionario con cualquier estructura (de cualquier proveedor)
    y convertirlo en una lista de objetos RegistroAVL — el modelo canónico
    interno del Hub.

Por qué es necesario:
    Cada proveedor GPS usa sus propios nombres de campos y formatos.
    Este módulo abstrae esas diferencias para que los despachadores
    siempre trabajen con el mismo modelo, sin importar el origen.

Estrategia de mapeo:
    1. Se busca el campo con el nombre canónico español.
    2. Si no existe, se prueban los aliases definidos en ALIASES_CAMPOS.
    3. Si tampoco existe, el campo queda en None.

Limpieza de placa:
    Todas las placas se limpian antes de ser procesadas.
    Se eliminan espacios, guiones, puntos y caracteres especiales.
    Esto aplica tanto a datos que nos envían como a datos que consultamos.
"""

import logging
import re
import unicodedata
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


# =========================================================================== #
# Limpieza de placa                                                           #
# =========================================================================== #

def limpiar_placa(placa: Any) -> Optional[str]:
    """
    Limpia y normaliza una placa para envío a destinos finales.

    Reglas:
        - Elimina espacios, guiones, puntos, comas y caracteres especiales
        - Elimina acentos y caracteres unicode especiales
        - Convierte a mayúsculas
        - Si el resultado está vacío, retorna None

    Ejemplos:
        "ABC-123"  → "ABC123"
        "XYZ 456"  → "XYZ456"
        "ÑOP.789"  → "NOP789"
        "A1B 2C3"  → "A1B2C3"

    Args:
        placa: Valor crudo de la placa (puede ser string, int, None).

    Returns:
        Placa limpia en mayúsculas, o None si está vacía o es inválida.
    """
    if placa is None:
        return None

    texto = str(placa).strip()
    if not texto:
        return None

    # Normalizar unicode: eliminar acentos y diacríticos
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))

    # Eliminar todo lo que no sea letra o número
    texto = re.sub(r"[^A-Za-z0-9]", "", texto)

    # Convertir a mayúsculas
    texto = texto.upper()

    return texto if texto else None


# =========================================================================== #
# Modelo canónico — RegistroAVL                                               #
# =========================================================================== #

class RegistroAVL(BaseModel):
    """
    Representación estándar de un pulso/evento GPS dentro del Hub.

    Todos los campos son opcionales. Latitud y longitud también pueden ser
    None si el dispositivo no tiene señal GPS en el momento del evento.

    REGLA FUNDAMENTAL DE TELEMETRÍA:
        Nunca se descarta un registro por falta de posición GPS.
        Un evento de pánico, apertura de puerta o batería baja es valioso
        aunque no tenga coordenadas en ese instante.
    """

    # --- Identificación del vehículo ---
    placa: Optional[str] = Field(None, description="Placa limpia sin caracteres especiales")

    # --- Posición GPS (opcionales — ver regla fundamental) ---
    latitud: Optional[float] = Field(None, description="Latitud decimal (ej: -34.541130)")
    longitud: Optional[float] = Field(None, description="Longitud decimal (ej: -58.479980)")

    # --- Fecha y hora del evento ---
    fecha: Optional[str] = Field(
        None, description="Fecha del evento. Formato: YYYY-MM-DDTHH:MM:SS±HH:MM"
    )

    # --- Estado del vehículo ---
    velocidad: Optional[str] = Field(None, description="Velocidad en km/h")
    altitud: Optional[str] = Field(None, description="Altitud en metros")
    rumbo: Optional[str] = Field(None, description="Rumbo en grados (0=Norte, 90=Este...)")
    direccion: Optional[str] = Field(None, description="Dirección en texto o grados")
    ignicion: Optional[str] = Field(None, description="Encendido: '1'=sí, '0'=no")
    odometro: Optional[str] = Field(None, description="Kilómetros en odómetro")

    # --- Dispositivo GPS ---
    numero_serie: Optional[str] = Field(None, description="Número de serie del GPS")
    bateria: Optional[str] = Field(None, description="Nivel de batería 0-100")

    # --- Viaje ---
    numero_viaje: Optional[str] = Field(None, description="Número de viaje del embarcador")

    # --- Sensores adicionales ---
    humedad: Optional[str] = Field(None, description="Humedad relativa 0-100")
    temperatura: Optional[str] = Field(None, description="Temperatura en grados Celsius")

    # --- Evento / alarma ---
    codigo_evento: Optional[str] = Field(None, description="Código del evento del AVL")
    alerta: Optional[str] = Field(None, description="Descripción de la alerta activa")

    # --- Datos del vehículo (campos RC v12+) ---
    tipo_vehiculo: Optional[str] = Field(None, description="Tipo: Tracto, Camión, etc.")
    marca_vehiculo: Optional[str] = Field(None, description="Marca: Ford, Volvo, etc.")
    modelo_vehiculo: Optional[str] = Field(None, description="Modelo: F500, FH, etc.")

    # --- Metadatos para Simon 4.0 ---
    usuario_avl: Optional[str] = Field(None, description="Usuario AVL de la fuente")
    etiqueta_origen: Optional[str] = Field(None, description="Tag de origen para Simon")

    @field_validator("latitud", "longitud", mode="before")
    @classmethod
    def convertir_coordenada(cls, valor):
        """Convierte coordenadas que lleguen como string a float. None si vacío."""
        if valor is None or str(valor).strip() == "":
            return None
        try:
            return float(valor)
        except (TypeError, ValueError):
            return None


# =========================================================================== #
# Tabla de aliases por proveedor                                               #
# =========================================================================== #

# Mapeo: nombre_canónico_español → [nombres alternativos que puede usar el proveedor]
# Ampliar esta tabla para dar soporte a nuevos proveedores sin tocar otra cosa.
ALIASES_CAMPOS: dict[str, list[str]] = {
    "placa":           ["Asset", "asset", "unit", "vehicleId", "device_id",
                        "imei", "nombre", "patente"],
    "latitud":         ["Latitude", "latitude", "lat", "Lat", "latitud"],
    "longitud":        ["Longitude", "longitude", "lon", "lng", "Lon", "longitud"],
    "fecha":           ["Date", "date", "fecha", "timestamp", "event_time", "gps_time"],
    "velocidad":       ["Speed", "speed", "velocidad", "vel"],
    "altitud":         ["Altitude", "altitude", "altitud", "alt"],
    "rumbo":           ["Course", "course", "heading", "rumbo"],
    "direccion":       ["Direction", "direction", "dir", "angle"],
    "ignicion":        ["Ignition", "ignition", "ignicion", "ign"],
    "odometro":        ["Odometer", "odometer", "odometro", "km"],
    "numero_serie":    ["SerialNumber", "serialNumber", "serial",
                        "serial_number", "idRastreable"],
    "bateria":         ["Battery", "battery", "bateria", "bat"],
    "numero_viaje":    ["Shipment", "shipment", "viaje", "trip_id", "orden"],
    "humedad":         ["Humidity", "humidity", "humedad", "hum"],
    "temperatura":     ["Temperature", "temperature", "temperatura", "temp"],
    "codigo_evento":   ["Code", "code", "evento", "event_code",
                        "eventCode", "idTipoEvento"],
    "alerta":          ["Alert", "alert", "alarma", "alarm"],
    "tipo_vehiculo":   ["VehicleType", "vehicleType", "vehicle_type",
                        "tipoVehiculo", "tipo"],
    "marca_vehiculo":  ["VehicleBrand", "vehicleBrand", "vehicle_brand", "marca"],
    "modelo_vehiculo": ["VehicleModel", "vehicleModel", "vehicle_model", "modelo"],
    "usuario_avl":     ["User_avl", "user_avl", "usuarioAvl"],
    "etiqueta_origen": ["SourceTag", "source_tag", "sourceTag"],
}


# =========================================================================== #
# Funciones internas                                                           #
# =========================================================================== #

def _buscar_campo(datos: dict, nombre_canonico: str) -> Any:
    """
    Busca el valor de un campo en el diccionario de datos del proveedor,
    probando primero el nombre canónico y luego todos sus aliases.
    """
    todos_los_nombres = [nombre_canonico] + ALIASES_CAMPOS.get(nombre_canonico, [])
    for nombre in todos_los_nombres:
        if nombre in datos:
            return datos[nombre]
    return None


def _normalizar_fecha(fecha_cruda: Any, zona_horaria: str = "-05:00") -> Optional[str]:
    """
    Convierte cualquier formato de fecha al estándar ISO 8601 con offset.

    Formato de salida: YYYY-MM-DDTHH:MM:SS±HH:MM
    Ejemplo:           2024-01-15T10:30:00-05:00

    Formatos de entrada soportados:
        - ISO con timezone:  2022-09-19T11:43:47-05:00
        - ISO sin timezone:  2020-07-15T10:12:00
        - Con espacio:       2020-07-15 10:12:00  (formato Control Group)
        - Formato latino:    15/07/2020 10:12:00
        - Compacto:          20200715101200
    """
    if fecha_cruda is None:
        return None

    FORMATOS_SOPORTADOS = [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
        "%Y%m%d%H%M%S",
    ]

    texto = str(fecha_cruda).strip()

    for formato in FORMATOS_SOPORTADOS:
        try:
            dt = datetime.strptime(texto, formato)
            return f"{dt.strftime('%Y-%m-%dT%H:%M:%S')}{zona_horaria}"
        except ValueError:
            continue

    logger.warning(
        "[Estandarizador] Fecha '%s' no reconocida. Se enviará sin modificar.",
        fecha_cruda,
    )
    return texto


# =========================================================================== #
# Función principal                                                            #
# =========================================================================== #

def normalizar_carga(
    datos_crudos: Any,
    zona_horaria: str = "-05:00",
    usuario_avl_defecto: str = "avl",
    etiqueta_origen_defecto: str = "",
) -> list[RegistroAVL]:
    """
    Convierte el payload crudo de un proveedor en una lista de RegistroAVL.

    Acepta tanto un objeto único {} como una lista de objetos [{},...].
    Si un registro individual falla, se loguea el error y se continúa.

    La placa siempre se limpia: sin espacios, guiones ni caracteres especiales.

    Args:
        datos_crudos:            Payload recibido (dict o lista de dicts).
        zona_horaria:            Offset de timezone para normalizar fechas.
        usuario_avl_defecto:     Valor de usuario_avl si el proveedor no lo envía.
        etiqueta_origen_defecto: Valor de etiqueta_origen si no viene en el dato.

    Returns:
        Lista de RegistroAVL válidos, listos para despachar.
    """
    if isinstance(datos_crudos, dict):
        registros_crudos = [datos_crudos]
    elif isinstance(datos_crudos, list):
        registros_crudos = datos_crudos
    else:
        raise ValueError(
            f"[Estandarizador] Tipo no soportado: {type(datos_crudos).__name__}. "
            "Se esperaba dict o list."
        )

    resultado: list[RegistroAVL] = []

    for indice, item in enumerate(registros_crudos):
        if not isinstance(item, dict):
            logger.warning(
                "[Estandarizador] Registro #%d ignorado: se recibió %s.",
                indice, type(item).__name__
            )
            continue

        try:
            canonico: dict[str, Any] = {}
            for campo in RegistroAVL.model_fields:
                canonico[campo] = _buscar_campo(item, campo)

            # Limpiar la placa: sin espacios, guiones ni caracteres especiales
            canonico["placa"] = limpiar_placa(canonico.get("placa"))

            # Normalizar la fecha si existe
            if canonico.get("fecha"):
                canonico["fecha"] = _normalizar_fecha(canonico["fecha"], zona_horaria)

            # Inyectar metadatos si no vienen del proveedor
            if not canonico.get("usuario_avl"):
                canonico["usuario_avl"] = usuario_avl_defecto
            if not canonico.get("etiqueta_origen"):
                canonico["etiqueta_origen"] = etiqueta_origen_defecto

            # Convertir campos numéricos a string donde el modelo lo exige
            for campo_str in [
                "velocidad", "altitud", "odometro", "bateria",
                "rumbo", "direccion", "numero_serie",
            ]:
                if canonico.get(campo_str) is not None:
                    canonico[campo_str] = str(canonico[campo_str])

            registro = RegistroAVL(**canonico)
            resultado.append(registro)

            logger.debug(
                "[Estandarizador] Registro #%d → placa=%s lat=%s lon=%s",
                indice, registro.placa, registro.latitud, registro.longitud,
            )

        except Exception as error:
            logger.error(
                "[Estandarizador] Error en registro #%d: %s — datos: %s",
                indice, error, item,
            )
            continue

    logger.info(
        "[Estandarizador] %d/%d registros normalizados correctamente.",
        len(resultado), len(registros_crudos),
    )
    return resultado
