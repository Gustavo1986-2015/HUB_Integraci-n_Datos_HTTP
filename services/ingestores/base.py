"""
services/ingestores/base.py
============================
Contrato base para todos los ingestores activos del Hub.

Un ingestor activo consulta periódicamente la API de un prestador
satelital que no envía datos por su cuenta.

Todo ingestor nuevo debe heredar de IngestorBase e implementar:
    - nombre:  identificador único en minúsculas (ej: "control_group")
    - consultar(): lógica de polling, retorna lista de RegistroAVL

El planificador (planificador.py) llama a consultar() automáticamente
según el intervalo configurado en segundos.
"""

from abc import ABC, abstractmethod
from services.estandarizador import RegistroAVL


class IngestorBase(ABC):
    """Interfaz que deben implementar todos los ingestores activos."""

    @property
    @abstractmethod
    def nombre(self) -> str:
        """
        Nombre único del ingestor en minúsculas con guiones bajos.
        Se usa en logs, métricas y para resolver el destino via
        DESTINOS_{NOMBRE} en el archivo .env.

        Ejemplo: "control_group"
        """
        ...

    @abstractmethod
    async def consultar(self) -> list[RegistroAVL]:
        """
        Consulta la fuente de datos y retorna los registros nuevos.

        Reglas:
            - Retornar lista vacía [] si no hay datos nuevos.
            - Capturar internamente cualquier error de red o parsing.
            - Los RegistroAVL retornados ya deben estar normalizados.
            - NUNCA descartar registros por falta de posición GPS.

        Returns:
            Lista de RegistroAVL listos para despachar.
            Lista vacía si no hay datos nuevos o si ocurrió un error.
        """
        ...
