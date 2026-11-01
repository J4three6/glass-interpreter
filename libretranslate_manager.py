"""
Gestiona el ciclo de vida de LibreTranslate desde Glass Interpreter.

    import libretranslate_manager as lt
    lt.iniciar()    # al arrancar Glass
    lt.detener()    # al cerrar Glass (tambien se llama solo con atexit)

Busca libretranslate.exe sin rutas fijas:
  1. junto al Python que ejecuta Glass (entorno virtual .venv\\Scripts)
  2. en la carpeta Scripts de ese Python (instalacion global)
  3. en el PATH
"""
import atexit
import os
import shutil
import socket
import subprocess
import sys
import time

HOST = "127.0.0.1"
PORT = 5000

CREATE_NO_WINDOW = 0x08000000
_proc = None


def _buscar_exe():
    base = os.path.dirname(sys.executable)
    for candidato in (
        os.path.join(base, "libretranslate.exe"),
        os.path.join(base, "Scripts", "libretranslate.exe"),
    ):
        if os.path.isfile(candidato):
            return candidato
    return shutil.which("libretranslate")


def _puerto_abierto():
    try:
        with socket.create_connection((HOST, PORT), timeout=0.5):
            return True
    except OSError:
        return False


def iniciar():
    """Lanza LibreTranslate oculto, salvo que ya haya uno respondiendo.
    Devuelve True si hay (o se lanzo) un servicio, False si no se encontro el ejecutable."""
    global _proc
    if _proc is not None or _puerto_abierto():
        return True
    exe = _buscar_exe()
    if not exe:
        return False
    # stdin/stdout/stderr a DEVNULL: bajo pythonw no hay consola
    _proc = subprocess.Popen(
        [exe, "--host", HOST, "--port", str(PORT)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW,
    )
    atexit.register(detener)
    return True


def esperar_listo(timeout=180):
    """Bloquea hasta que el servicio responda."""
    fin = time.time() + timeout
    while time.time() < fin:
        if _puerto_abierto():
            return True
        time.sleep(0.5)
    return False


def detener():
    """Cierra el LibreTranslate lanzado por esta sesion, con todos sus procesos hijos."""
    global _proc
    if _proc is not None and _proc.poll() is None:
        subprocess.run(
            ["taskkill", "/PID", str(_proc.pid), "/T", "/F"],
            capture_output=True,
            creationflags=CREATE_NO_WINDOW,
        )
    _proc = None
