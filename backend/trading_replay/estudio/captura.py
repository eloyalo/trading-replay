"""Captura de escenas del Estudio en PNG y MP4 (spec 010, RF-10).

Arranca un servidor propio en un puerto libre (sin `lifespan`, así no toca el replay ni las
cuentas), abre Chrome sin interfaz con el tamaño exacto del vídeo y, por el protocolo de
DevTools, llama a `estudio.ir(t)` y captura cada fotograma. Los PNG van por tubería a ffmpeg.
"""

from __future__ import annotations

import base64
import json
import math
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path

import uvicorn
from websockets.sync.client import connect

from trading_replay.estudio.escena import preparar

TAMANOS = {"16:9": (1920, 1080), "9:16": (1080, 1920)}
NAVEGADORES = ("google-chrome-stable", "google-chrome", "chromium", "chromium-browser")


class ErrorCaptura(RuntimeError):
    pass


def cargar_escena(ruta: Path) -> dict:
    """Lee la escena y mete dentro los trazos de pincel que estén en archivos aparte (`trazo`)."""
    escena = json.loads(ruta.read_text(encoding="utf-8"))
    for paso in escena.get("pasos", []):
        if isinstance(paso, dict) and paso.get("accion") == "pincel" and "trazo" in paso and "puntos" not in paso:
            trazo = json.loads((ruta.parent / paso.pop("trazo")).read_text(encoding="utf-8"))
            paso["puntos"] = trazo["puntos"] if isinstance(trazo, dict) else trazo
            if isinstance(trazo, dict) and "duracion" in trazo:
                paso.setdefault("duracion", trazo["duracion"])
    return escena


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def _servidor():
    from trading_replay.app import app

    puerto = _puerto_libre()
    servidor = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=puerto, lifespan="off", log_level="warning"))
    hilo = threading.Thread(target=servidor.run, daemon=True)
    hilo.start()
    limite = time.monotonic() + 20
    while not servidor.started:
        if time.monotonic() > limite:
            raise ErrorCaptura("El servidor del Estudio no arrancó")
        time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{puerto}"
    finally:
        servidor.should_exit = True
        hilo.join(timeout=10)


def _navegador() -> str:
    for nombre in (os.environ.get("TRADING_REPLAY_CHROME"), *NAVEGADORES):
        if nombre and shutil.which(nombre):
            return shutil.which(nombre)
    raise ErrorCaptura("No encuentro Chrome; indica la ruta con TRADING_REPLAY_CHROME")


class _Pestana:
    """Conexión mínima al protocolo de DevTools de una pestaña."""

    def __init__(self, ws):
        self.ws = ws
        self.siguiente = 0

    def llamar(self, metodo: str, **params) -> dict:
        self.siguiente += 1
        mi_id = self.siguiente
        self.ws.send(json.dumps({"id": mi_id, "method": metodo, "params": params}))
        while True:
            mensaje = json.loads(self.ws.recv(timeout=120))
            if mensaje.get("id") == mi_id:
                if "error" in mensaje:
                    raise ErrorCaptura(f"{metodo}: {mensaje['error'].get('message')}")
                return mensaje.get("result", {})

    def esperar_evento(self, metodo: str, limite: float = 30) -> None:
        fin = time.monotonic() + limite
        while time.monotonic() < fin:
            mensaje = json.loads(self.ws.recv(timeout=limite))
            if mensaje.get("method") == metodo:
                return
        raise ErrorCaptura(f"No llegó {metodo}")

    def evaluar(self, expresion: str):
        r = self.llamar("Runtime.evaluate", expression=expresion, awaitPromise=True, returnByValue=True)
        if "exceptionDetails" in r:
            detalle = r["exceptionDetails"].get("exception", {}).get("description") or r["exceptionDetails"].get("text")
            raise ErrorCaptura(detalle)
        return r.get("result", {}).get("value")

    def foto(self) -> bytes:
        return base64.b64decode(self.llamar("Page.captureScreenshot", format="png")["data"])


@contextmanager
def _chrome(ancho: int, alto: int):
    puerto = _puerto_libre()
    perfil = tempfile.mkdtemp(prefix="estudio-chrome-")
    proceso = subprocess.Popen(
        [_navegador(), "--headless=new", f"--remote-debugging-port={puerto}", f"--user-data-dir={perfil}",
         f"--window-size={ancho},{alto}", "--force-device-scale-factor=1", "--hide-scrollbars", "--mute-audio",
         "--no-first-run", "--no-default-browser-check", "--disable-extensions", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        limite = time.monotonic() + 20
        while True:
            try:
                peticion = urllib.request.Request(f"http://127.0.0.1:{puerto}/json/new?about:blank", method="PUT")
                with urllib.request.urlopen(peticion, timeout=2) as r:
                    destino = json.load(r)["webSocketDebuggerUrl"]
                break
            except OSError:
                if time.monotonic() > limite or proceso.poll() is not None:
                    raise ErrorCaptura("Chrome no arrancó") from None
                time.sleep(0.2)
        with connect(destino, max_size=None, open_timeout=20) as ws:
            pestana = _Pestana(ws)
            pestana.llamar("Emulation.setDeviceMetricsOverride", width=ancho, height=alto, deviceScaleFactor=1, mobile=False)
            yield pestana
    finally:
        proceso.terminate()  # por su objeto, nunca por nombre (CLAUDE.md)
        try:
            proceso.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proceso.kill()
        shutil.rmtree(perfil, ignore_errors=True)


@contextmanager
def sesion(escena: dict, aspecto: str | None = None):
    """Prepara la escena y deja una pestaña con ella cargada. Devuelve (pestaña, escena preparada)."""
    if aspecto:
        escena = {**escena, "lienzo": {**escena.get("lienzo", {}), "aspecto": aspecto}}
    preparada = preparar(escena)  # valida antes de abrir nada (RF-6)
    ancho, alto = TAMANOS[preparada["lienzo"]["aspecto"]]
    with _servidor() as base, _chrome(ancho, alto) as pestana:
        pestana.llamar("Page.enable")
        pestana.llamar("Page.navigate", url=f"{base}/estudio.html?captura=1")
        pestana.esperar_evento("Page.loadEventFired")
        pestana.evaluar(f"estudio.cargar({json.dumps(preparada)})")
        yield pestana, preparada


def fotos(escena: dict, instantes: list[float], salida: Path, aspecto: str | None = None) -> list[Path]:
    rutas = []
    with sesion(escena, aspecto) as (pestana, _):
        for t in instantes:
            pestana.evaluar(f"estudio.ir({float(t)})")
            ruta = salida.with_name(f"{salida.stem}_t{t:g}.png")
            ruta.parent.mkdir(parents=True, exist_ok=True)
            ruta.write_bytes(pestana.foto())
            rutas.append(ruta)
    return rutas


def video(escena: dict, salida: Path, fps: int = 30, aspecto: str | None = None, progreso=None) -> dict:
    if not shutil.which("ffmpeg"):
        raise ErrorCaptura("Falta ffmpeg")
    inicio = time.monotonic()
    with sesion(escena, aspecto) as (pestana, preparada):
        total = math.ceil(preparada["duracion"] * fps)
        salida.parent.mkdir(parents=True, exist_ok=True)
        ffmpeg = subprocess.Popen(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(fps), "-c:v", "png", "-i", "-",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "16", "-preset", "medium", "-movflags", "+faststart",
             str(salida)],
            stdin=subprocess.PIPE,
        )
        try:
            for i in range(total):
                pestana.evaluar(f"estudio.ir({i / fps})")
                ffmpeg.stdin.write(pestana.foto())
                if progreso:
                    progreso(i + 1, total)
        finally:
            ffmpeg.stdin.close()
            ffmpeg.wait()
        if ffmpeg.returncode:
            raise ErrorCaptura("ffmpeg falló al crear el vídeo")
    return {"fotogramas": total, "segundos": time.monotonic() - inicio, "ruta": salida}
