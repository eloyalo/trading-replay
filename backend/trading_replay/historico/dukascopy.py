"""Descarga y decodificación de velas de 1 minuto de Dukascopy.

Cada día es un archivo LZMA con registros de 24 bytes big-endian:
segundos desde las 00:00 UTC, apertura, cierre, mínimo, máximo (enteros
multiplicados por la unidad de precio) y volumen (float).
"""

import http.client
import lzma
import os
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from trading_replay.config import FECHA_INICIO, Instrumento, carpeta_datos

HOST = "datafeed.dukascopy.com"
URL_BASE = f"https://{HOST}/datafeed"
HILOS = 6
REINTENTOS = 6
SATURADO = {429, 503}  # Dukascopy limita a quien pide demasiado: hay que esperar más
DIAS_PROVISIONALES = 3  # días recientes vacíos que se vuelven a pedir en la próxima actualización

REGISTRO = np.dtype(
    [("seg", ">i4"), ("open", ">i4"), ("close", ">i4"), ("low", ">i4"), ("high", ">i4"), ("volume", ">f4")]
)


def url_dia(instrumento: Instrumento, dia: date) -> str:
    # Dukascopy numera los meses de 0 a 11.
    return f"{URL_BASE}/{instrumento.dukascopy}/{dia.year}/{dia.month - 1:02d}/{dia.day:02d}/BID_candles_min_1.bi5"


def ruta_crudo(simbolo: str, dia: date) -> Path:
    return carpeta_datos() / "crudo" / simbolo / str(dia.year) / f"{dia.isoformat()}.bi5"


def decodificar(contenido: bytes, dia: date) -> np.ndarray:
    """Convierte un .bi5 comprimido en un array estructurado con el formato REGISTRO."""
    if not contenido:
        return np.empty(0, dtype=REGISTRO)
    datos = lzma.decompress(contenido)
    if len(datos) % REGISTRO.itemsize:
        raise ValueError(f"{dia}: tamaño {len(datos)} no es múltiplo de {REGISTRO.itemsize}")
    return np.frombuffer(datos, dtype=REGISTRO)


def dias_pendientes(simbolo: str, hasta: date) -> list[date]:
    """Días entre FECHA_INICIO y `hasta` sin archivo crudo. Se saltan los sábados (mercado cerrado)."""
    pendientes = []
    dia = FECHA_INICIO
    while dia <= hasta:
        if dia.weekday() != 5 and not ruta_crudo(simbolo, dia).exists():
            pendientes.append(dia)
        dia += timedelta(days=1)
    return pendientes


_por_hilo = threading.local()


def _conexion_del_hilo() -> http.client.HTTPSConnection:
    # Cada hilo reutiliza su conexión (keep-alive): abrir una conexión TLS con
    # Dukascopy puede tardar más de 10 s, mientras que cada archivo llega en ~0,1 s.
    if getattr(_por_hilo, "conexion", None) is None:
        _por_hilo.conexion = http.client.HTTPSConnection(HOST, timeout=60)
    return _por_hilo.conexion


def _pedir(url: str) -> bytes:
    """Descarga una URL con reintentos y espera creciente. 404 se trata como día sin datos."""
    ruta = url.removeprefix(f"https://{HOST}")
    for intento in range(REINTENTOS):
        conexion = _conexion_del_hilo()
        espera = 2**intento  # 1, 2, 4... hasta 32 s
        try:
            conexion.request("GET", ruta, headers={"User-Agent": "trading-replay/0.1"})
            respuesta = conexion.getresponse()
            contenido = respuesta.read()
            if respuesta.status == 200:
                return contenido
            if respuesta.status == 404:
                return b""
            fallo = f"HTTP {respuesta.status}"
            if respuesta.status in SATURADO:
                espera = max(espera * 4, int(respuesta.getheader("Retry-After", "0") or 0))
        except (OSError, http.client.HTTPException) as error:
            fallo = repr(error)
            conexion.close()
            _por_hilo.conexion = None
        time.sleep(espera)
    raise RuntimeError(f"No se pudo descargar {url}: {fallo}")


def _descargar_dia(instrumento: Instrumento, dia: date, hoy: date) -> int:
    contenido = _pedir(url_dia(instrumento, dia))
    if contenido:
        decodificar(contenido, dia)  # valida antes de guardar
    elif (hoy - dia).days <= DIAS_PROVISIONALES:
        return 0  # puede que Dukascopy aún no lo tenga: no se marca como descargado
    destino = ruta_crudo(instrumento.simbolo, dia)
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_suffix(".tmp")
    temporal.write_bytes(contenido)
    os.replace(temporal, destino)
    return len(contenido)


def descargar(
    instrumentos: Iterable[Instrumento],
    progreso: Callable[[str, int, int], None] | None = None,
) -> dict[str, list[tuple[date, str]]]:
    """Descarga los días que falten hasta ayer (UTC). Devuelve los errores por símbolo."""
    hoy = datetime.now(timezone.utc).date()
    errores: dict[str, list[tuple[date, str]]] = {}
    for instrumento in instrumentos:
        pendientes = dias_pendientes(instrumento.simbolo, hoy - timedelta(days=1))
        errores[instrumento.simbolo] = []
        hechos = 0
        with ThreadPoolExecutor(max_workers=HILOS) as hilos:
            futuros = {hilos.submit(_descargar_dia, instrumento, dia, hoy): dia for dia in pendientes}
            for futuro in as_completed(futuros):
                hechos += 1
                try:
                    futuro.result()
                except Exception as error:  # se informa y se reintenta en la próxima ejecución
                    errores[instrumento.simbolo].append((futuros[futuro], str(error)))
                if progreso:
                    progreso(instrumento.simbolo, hechos, len(pendientes))
    return errores
