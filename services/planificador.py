"""
services/planificador.py
=========================
Planificador de ingestores activos.

Ejecuta periódicamente el método consultar() de cada ingestor registrado.
Corre como tarea asyncio en segundo plano — no bloquea el servidor FastAPI.

Flujo por ingestor:
    Mientras el servidor esté activo:
        1. Esperar N segundos (intervalo configurado)
        2. Llamar a ingestor.consultar()
        3. Si hay registros → llamar a la función de despacho
        4. Volver al paso 1

Si un ingestor falla, el error se loguea y el ciclo continúa.
Un fallo en un ingestor nunca afecta a los demás.
"""

import asyncio
import logging
from services.estandarizador import RegistroAVL

logger = logging.getLogger(__name__)


class PlanificadorIngestores:
    """
    Gestiona el ciclo de vida de todos los ingestores activos.
    """

    def __init__(self):
        # Registro de ingestores: {nombre → (ingestor, intervalo_segundos)}
        self._ingestores: dict = {}
        # Tareas asyncio en ejecución: {nombre → Task}
        self._tareas: dict[str, asyncio.Task] = {}

    def registrar(self, ingestor, intervalo_segundos: int) -> None:
        """
        Registra un ingestor para ejecución periódica.
        Debe llamarse antes de iniciar(). No arranca el loop inmediatamente.

        Args:
            ingestor:           Instancia del ingestor a registrar.
            intervalo_segundos: Segundos entre cada llamada a consultar().
        """
        self._ingestores[ingestor.nombre] = (ingestor, intervalo_segundos)
        logger.info(
            "[Planificador] Ingestor registrado: '%s' — intervalo: %ds",
            ingestor.nombre, intervalo_segundos,
        )

    async def iniciar(self, funcion_despacho) -> None:
        """
        Inicia una tarea asyncio por cada ingestor registrado.
        Debe llamarse dentro del lifespan de FastAPI (startup).

        Args:
            funcion_despacho: Función async a llamar con los registros obtenidos.
                              Firma: async def funcion_despacho(registros, nombre_proveedor)
        """
        if not self._ingestores:
            logger.info("[Planificador] Sin ingestores registrados.")
            return

        for nombre, (ingestor, intervalo) in self._ingestores.items():
            tarea = asyncio.create_task(
                self._ciclo(ingestor, intervalo, funcion_despacho),
                name=f"ingestor_{nombre}",
            )
            self._tareas[nombre] = tarea
            logger.info("[Planificador] Tarea iniciada para '%s'.", nombre)

    async def detener(self) -> None:
        """
        Cancela todas las tareas activas de forma ordenada.
        Debe llamarse en el shutdown del lifespan de FastAPI.
        """
        for nombre, tarea in self._tareas.items():
            if not tarea.done():
                tarea.cancel()
                try:
                    await tarea
                except asyncio.CancelledError:
                    pass  # Cancelación esperada — no es un error
                logger.info("[Planificador] Tarea '%s' detenida.", nombre)
        self._tareas.clear()

    async def _ciclo(
        self,
        ingestor,
        intervalo_segundos: int,
        funcion_despacho,
    ) -> None:
        """
        Loop infinito para un ingestor individual.

        Espera el primer intervalo antes de ejecutar para no sobrecargar
        el arranque del servidor con múltiples requests simultáneos.

        Args:
            ingestor:          Ingestor a ejecutar periódicamente.
            intervalo_segundos: Segundos entre iteraciones.
            funcion_despacho:  Función de despacho a invocar con los resultados.
        """
        logger.info(
            "[Planificador] Ciclo de '%s' iniciado. Primera consulta en %ds.",
            ingestor.nombre, intervalo_segundos,
        )

        await asyncio.sleep(intervalo_segundos)

        while True:
            try:
                logger.debug("[Planificador] Ejecutando consultar() para '%s'.", ingestor.nombre)
                registros: list[RegistroAVL] = await ingestor.consultar()

                if registros:
                    logger.info(
                        "[Planificador] '%s' obtuvo %d registro(s). Despachando.",
                        ingestor.nombre, len(registros),
                    )
                    await funcion_despacho(registros, ingestor.nombre)
                else:
                    logger.debug("[Planificador] '%s' sin datos nuevos.", ingestor.nombre)

            except asyncio.CancelledError:
                logger.info("[Planificador] Ciclo de '%s' detenido.", ingestor.nombre)
                raise

            except Exception as error:
                logger.error(
                    "[Planificador] Error en ciclo de '%s': %s. Reintento en %ds.",
                    ingestor.nombre, error, intervalo_segundos,
                    exc_info=True,
                )

            await asyncio.sleep(intervalo_segundos)


# Instancia global — usada por main.py
planificador = PlanificadorIngestores()
