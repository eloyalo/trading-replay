"""Acciones y ETF de Dukascopy bajo demanda, solo para el Estudio (spec 010, RF-4).

Dukascopy tiene CFD de acciones estadounidenses (`NVDAUSUSD`, `SPYUSUSD`...) con velas de
1 minuto por día, de 1 hora por mes y de 1 día por año. Solo cotizan en la sesión regular
(9:30-16:00 ET); fuera de ella los archivos traen minutos planos con volumen 0, que se quitan.

No hay descarga masiva: se pide el archivo que cubre lo que necesita la escena y se guarda en
`datos/estudio/<SÍMBOLO>/`. Los precios de Dukascopy no están ajustados por splits; se ajustan
aquí con `SPLITS`.
"""

from __future__ import annotations

import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from trading_replay.config import ZONA_MERCADO, carpeta_datos
from trading_replay.historico.dukascopy import URL_BASE, _pedir, decodificar

ET = ZoneInfo(ZONA_MERCADO)
UNIDAD_PRECIO = 0.001
SIMBOLO_VALIDO = re.compile(r"^[A-Z]{1,5}$")
RECIENTE = timedelta(days=3)  # archivos que pueden cambiar todavía
CADUCIDAD_RECIENTE = 12 * 3600  # segundos

# Splits (fecha del primer día con el precio nuevo, factor). Dukascopy no ajusta el histórico:
# antes de esa fecha los precios se dividen por el factor. El volumen del CFD no cambia con el
# split (NVDA, junio de 2024: 54 antes y 73 después en bruto), así que se deja como está.
SPLITS: dict[str, list[tuple[date, float]]] = {
    "NVDA": [(date(2021, 7, 20), 4), (date(2024, 6, 10), 10)],
    "AAPL": [(date(2020, 8, 31), 4)],
    "TSLA": [(date(2020, 8, 31), 5), (date(2022, 8, 25), 3)],
    "AMZN": [(date(2022, 6, 6), 20)],
    "GOOGL": [(date(2022, 7, 18), 20)],
    "GOOG": [(date(2022, 7, 18), 20)],
    "AVGO": [(date(2024, 7, 15), 10)],
    "WMT": [(date(2024, 2, 26), 3)],
    "CMG": [(date(2024, 6, 26), 50)],
    "SMCI": [(date(2024, 10, 1), 10)],
}

# Timeframes que admite el Estudio para acciones y de qué archivo salen.
TF_MINUTOS = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1D": 1440}
MAX_DIAS_INTRADIA = 120  # días de archivos de 1m por escena (evita descargas grandes por error)


class SimboloNoValido(ValueError):
    pass


def codigo_dukascopy(simbolo: str) -> str:
    if not SIMBOLO_VALIDO.match(simbolo):
        raise SimboloNoValido(f"Símbolo de acción no válido: {simbolo!r}")
    return f"{simbolo}USUSD"


def carpeta(simbolo: str) -> Path:
    return carpeta_datos() / "estudio" / simbolo


def _archivo(simbolo: str, nombre: str, url: str, fin_periodo: date) -> bytes:
    """Contenido del archivo, de la caché o de Dukascopy. Los periodos recientes caducan."""
    ruta = carpeta(simbolo) / nombre
    hoy = datetime.now(timezone.utc).date()
    reciente = hoy - fin_periodo < RECIENTE
    if ruta.exists() and not (reciente and time.time() - ruta.stat().st_mtime > CADUCIDAD_RECIENTE):
        return ruta.read_bytes()
    contenido = _pedir(url)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_suffix(".tmp")
    temporal.write_bytes(contenido)
    temporal.replace(ruta)
    return contenido


def _registros(contenido: bytes, inicio_utc: datetime) -> tuple[np.ndarray, np.ndarray]:
    """(instantes UTC en segundos, registros con volumen) de un .bi5."""
    reg = decodificar(contenido, inicio_utc.date())
    reg = reg[reg["volume"] > 0]
    return int(inicio_utc.timestamp()) + reg["seg"].astype(np.int64), reg


def _como_velas(t_utc: np.ndarray, reg: np.ndarray) -> dict[str, np.ndarray]:
    return {
        "t_utc": t_utc,
        **{k: reg[k].astype("f8") * UNIDAD_PRECIO for k in ("open", "high", "low", "close")},
        "volume": reg["volume"].astype("f8"),
    }


def _ajustar_splits(simbolo: str, cols: dict[str, np.ndarray], dias: np.ndarray) -> None:
    """Divide los precios de las velas anteriores a cada split. `dias`: datetime64[D] en hora ET."""
    for fecha, factor in SPLITS.get(simbolo, []):
        antes = dias < np.datetime64(fecha, "D")
        for k in ("open", "high", "low", "close"):
            cols[k][antes] /= factor


def _hora_et(t_utc: np.ndarray) -> np.ndarray:
    """Segundos "ET como UTC", como `time` en `almacen.consultar`."""
    return np.array(
        [int(datetime.fromtimestamp(int(t), timezone.utc).astimezone(ET).replace(tzinfo=timezone.utc).timestamp())
         for t in t_utc],
        dtype=np.int64,
    )


def _diarias(simbolo: str, desde: datetime, hasta: datetime) -> dict[str, np.ndarray]:
    codigo = codigo_dukascopy(simbolo)
    partes = []
    for anio in range(desde.year, hasta.year + 1):
        inicio = datetime(anio, 1, 1, tzinfo=timezone.utc)
        contenido = _archivo(simbolo, f"{anio}.dia.bi5", f"{URL_BASE}/{codigo}/{anio}/BID_candles_day_1.bi5",
                             date(anio, 12, 31))
        partes.append(_registros(contenido, inicio))
    t = np.concatenate([p[0] for p in partes])
    cols = _como_velas(t, np.concatenate([p[1] for p in partes]))
    # La vela diaria se etiqueta con su fecha a las 00:00, como la de 1D de los futuros.
    cols["time"] = t - t % 86400
    return cols


def _minutos(simbolo: str, desde: datetime, hasta: datetime) -> dict[str, np.ndarray]:
    codigo = codigo_dukascopy(simbolo)
    dias = []
    dia = desde.date()
    while dia <= hasta.date():
        if dia.weekday() < 5:
            dias.append(dia)
        dia += timedelta(days=1)
    if len(dias) > MAX_DIAS_INTRADIA:
        raise ValueError(f"Demasiados días de 1m para una escena ({len(dias)}; máximo {MAX_DIAS_INTRADIA}). "
                         "Usa un timeframe mayor o acorta el rango.")
    partes = []
    for dia in dias:
        # La sesión regular (9:30-16:00 ET) cae siempre dentro del mismo día UTC.
        url = f"{URL_BASE}/{codigo}/{dia.year}/{dia.month - 1:02d}/{dia.day:02d}/BID_candles_min_1.bi5"
        contenido = _archivo(simbolo, f"{dia.year}/{dia.isoformat()}.bi5", url, dia)
        partes.append(_registros(contenido, datetime(dia.year, dia.month, dia.day, tzinfo=timezone.utc)))
    if not partes:
        return {k: np.empty(0) for k in ("t_utc", "open", "high", "low", "close", "volume", "time")}
    t = np.concatenate([p[0] for p in partes])
    cols = _como_velas(t, np.concatenate([p[1] for p in partes]))
    cols["time"] = _hora_et(t)
    return cols


def consultar(simbolo: str, tf: str, desde: datetime, hasta: datetime) -> list[dict]:
    """Velas de `tf` con inicio en [desde, hasta) (hora ET sin zona), en el formato de `almacen.consultar`.

    Intradía: velas alineadas al reloj ET, así que la de 1h de las 9:00 solo tiene de 9:30 a 10:00
    y las de 4h son la de las 8:00 (9:30-12:00) y la de las 12:00 (12:00-16:00).
    """
    if tf not in TF_MINUTOS:
        raise ValueError(f"Timeframe no válido: {tf}")
    if tf == "1D":
        cols = _diarias(simbolo, desde, hasta)
    else:
        cols = _minutos(simbolo, desde, hasta)
    if not len(cols["time"]):
        return []
    _ajustar_splits(simbolo, cols, cols["time"].astype("datetime64[s]").astype("datetime64[D]"))

    inicio = int(desde.replace(tzinfo=timezone.utc).timestamp())
    fin = int(hasta.replace(tzinfo=timezone.utc).timestamp())
    dentro = (cols["time"] >= inicio) & (cols["time"] < fin)
    if tf == "1D":
        dentro = (cols["time"] >= inicio - inicio % 86400) & (cols["time"] < fin)
    cols = {k: v[dentro] for k, v in cols.items()}

    paso = TF_MINUTOS[tf] * 60
    cubeta = cols["time"] - cols["time"] % paso if tf != "1D" else cols["time"]
    velas = []
    limites = np.flatnonzero(np.diff(cubeta)) + 1
    for grupo in np.split(np.arange(len(cubeta)), limites):
        if not len(grupo):
            continue
        velas.append({
            "time": int(cubeta[grupo[0]]),
            "open": round(float(cols["open"][grupo[0]]), 3),
            "high": round(float(cols["high"][grupo].max()), 3),
            "low": round(float(cols["low"][grupo].min()), 3),
            "close": round(float(cols["close"][grupo[-1]]), 3),
            "volume": round(float(cols["volume"][grupo].sum()), 4),
        })
    return velas
