"""
watch_and_build.py
==================
Watcher que detecta cambios en hub_gui.py y recompila automáticamente.

Uso:
    python watch_and_build.py

Qué hace:
    1. Monitorea hub_gui.py cada 2 segundos
    2. Si detecta un cambio (fecha de modificación distinta)
       → ejecuta PyInstaller automáticamente
       → el nuevo .exe queda en la raíz del proyecto
    3. Muestra el resultado en consola con colores

Requisito:
    pip install pyinstaller
"""

import subprocess
import sys
import time
from pathlib import Path

ARCHIVO   = Path("hub_gui.py")
ICONO     = Path("hub_icon.ico")
NOMBRE    = "HubSatelital"
INTERVALO = 2  # segundos entre verificaciones

# Colores ANSI para consola Windows (funciona en Windows Terminal)
VERDE   = "\033[92m"
ROJO    = "\033[91m"
AMARILLO= "\033[93m"
CYAN    = "\033[96m"
RESET   = "\033[0m"
BOLD    = "\033[1m"

def compilar() -> bool:
    """Ejecuta PyInstaller y retorna True si tuvo éxito."""
    icono_arg = ["--icon", str(ICONO)] if ICONO.exists() else []

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        "--distpath", ".",
        "--name", NOMBRE,
        "--noconfirm",          # No preguntar si sobreescribir
        "--clean",              # Limpiar cache antes de compilar
        *icono_arg,
        str(ARCHIVO),
    ]

    print(f"\n{CYAN}{'─' * 52}{RESET}")
    print(f"{BOLD}{CYAN}  Compilando {ARCHIVO.name} → {NOMBRE}.exe...{RESET}")
    print(f"{CYAN}{'─' * 52}{RESET}")

    inicio = time.time()
    resultado = subprocess.run(cmd, capture_output=True, text=True)
    duracion = time.time() - inicio

    if resultado.returncode == 0:
        exe = Path(f"{NOMBRE}.exe")
        tamanio = f"{exe.stat().st_size // 1024 // 1024}MB" if exe.exists() else "?"
        print(f"{VERDE}{BOLD}  ✓ Compilado en {duracion:.0f}s — {NOMBRE}.exe ({tamanio}){RESET}")
        return True
    else:
        print(f"{ROJO}{BOLD}  ✗ Error de compilación:{RESET}")
        # Mostrar solo las últimas líneas del error (sin el spam de PyInstaller)
        lineas_error = [l for l in resultado.stdout.split("\n")
                        if "ERROR" in l or "error" in l.lower()][-5:]
        for linea in lineas_error:
            print(f"{ROJO}    {linea}{RESET}")
        return False


def main():
    if not ARCHIVO.exists():
        print(f"{ROJO}Error: {ARCHIVO} no encontrado en {Path.cwd()}{RESET}")
        sys.exit(1)

    try:
        subprocess.run([sys.executable, "-m", "PyInstaller", "--version"],
                       capture_output=True, check=True)
    except subprocess.CalledProcessError:
        print(f"{ROJO}PyInstaller no instalado. Ejecutar: pip install pyinstaller{RESET}")
        sys.exit(1)

    ultima_mod = ARCHIVO.stat().st_mtime

    print(f"{BOLD}{CYAN}")
    print("  ╔══════════════════════════════════════════╗")
    print("  ║   Watcher — HubSatelital AutoBuild       ║")
    print("  ║   Monitoreando: hub_gui.py               ║")
    print("  ║   Presionar Ctrl+C para detener          ║")
    print("  ╚══════════════════════════════════════════╝")
    print(f"{RESET}")
    print(f"{AMARILLO}  Esperando cambios en {ARCHIVO}...{RESET}")

    # Compilar al arrancar para tener el .exe actualizado
    print(f"{AMARILLO}  Compilación inicial...{RESET}")
    compilar()

    try:
        while True:
            time.sleep(INTERVALO)
            mod_actual = ARCHIVO.stat().st_mtime
            if mod_actual != ultima_mod:
                ultima_mod = mod_actual
                ts = time.strftime("%H:%M:%S")
                print(f"\n{AMARILLO}  [{ts}] Cambio detectado en {ARCHIVO.name}{RESET}")
                compilar()
                print(f"{AMARILLO}  Esperando próximo cambio...{RESET}")

    except KeyboardInterrupt:
        print(f"\n{CYAN}  Watcher detenido.{RESET}\n")


if __name__ == "__main__":
    main()
