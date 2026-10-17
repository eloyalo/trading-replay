"""Los indicadores de las estrategias dan lo mismo que los del gráfico (spec 008, RF-2).

Node calcula con `frontend/calculos.js` y Python con `backtest/indicadores.py` sobre la misma serie.
"""

import json
import random
import shutil
import subprocess
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import pytest

from trading_replay.backtest import indicadores as ind

SCRIPT = Path(__file__).parent / "js" / "paridad_indicadores.mjs"
# (clave, nombre en calculos.js, nombre en Python, parámetro)
CASOS = [
    ("sma3", "sma", "sma", 3),
    ("sma20", "sma", "sma", 20),
    ("ema9", "ema", "ema", 9),
    ("ema50", "ema", "ema", 50),
    ("rsi14", "rsi", "rsi", 14),
    ("atr14", "atr", "atr", 14),
    ("vwap", "vwap", "vwap", None),
    ("dia_anterior", "diaAnterior", "dia_anterior", None),
    ("overnight", "overnight", "overnight", None),
]


def serie_sintetica() -> list[dict]:
    """Velas de 5m durante cuatro días de trading, con la pausa diaria, un hueco a mitad de sesión y
    un minuto sin volumen. Empieza a mitad de día, como una ventana del gráfico."""
    azar = random.Random(8)
    velas = []
    t = int(datetime(2024, 3, 4, 13, 0, tzinfo=timezone.utc).timestamp())  # lunes 13:00 ET "como UTC"
    fin = t + 4 * 86400
    precio = 18000.0
    while t < fin:
        minuto = (t % 86400) // 60
        pausa = 16 * 60 + 15 <= minuto < 18 * 60
        hueco = 86400 + 2 * 3600 <= t - velas[0]["time"] < 86400 + 3 * 3600 if velas else False
        if not pausa and not hueco:
            apertura = precio
            precio = round(precio + azar.uniform(-8, 8), 2)
            alto = round(max(apertura, precio) + azar.uniform(0, 4), 2)
            bajo = round(min(apertura, precio) - azar.uniform(0, 4), 2)
            volumen = 0.0 if len(velas) == 40 else round(azar.uniform(10, 500), 4)
            velas.append({"time": t, "open": apertura, "high": alto, "low": bajo, "close": precio, "volume": volumen})
        t += 300
    return velas


class Columnas:
    """Velas por columnas, como las ve una estrategia."""

    def __init__(self, velas: list[dict]):
        for campo in ("time", "high", "low", "close", "volume"):
            setattr(self, campo, [v[campo] for v in velas])

    def __len__(self):
        return len(self.time)


def normalizar(valor):
    if isinstance(valor, ind.Niveles):
        return {k: v for k, v in asdict(valor).items() if v is not None}
    return valor


def iguales(python, js, contexto):
    if js is None or python is None:
        assert python == js, contexto
    elif isinstance(js, dict):
        assert python.keys() == js.keys(), contexto
        for k in js:
            iguales(python[k], js[k], f"{contexto}.{k}")
    else:
        assert abs(python - js) < 1e-9, f"{contexto}: {python} ≠ {js}"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node no está instalado")
def test_mismos_valores_que_calculos_js():
    velas = serie_sintetica()
    entrada = {"velas": velas, "indicadores": [[clave, js, parametro] for clave, js, _, parametro in CASOS]}
    salida = subprocess.run(["node", str(SCRIPT)], input=json.dumps(entrada), capture_output=True, text=True, timeout=60)
    assert salida.returncode == 0, salida.stderr
    esperado = json.loads(salida.stdout)

    cols = Columnas(velas)
    for clave, _, nombre, parametro in CASOS:
        fabrica = ind.INDICADORES[nombre]
        valores = ind.calcular(fabrica(parametro) if parametro is not None else fabrica(), cols)
        assert len(valores) == len(esperado[clave])
        for i, (python, js) in enumerate(zip(valores, esperado[clave])):
            iguales(normalizar(python), js, f"{clave}[{i}]")
        assert any(v is not None for v in valores), clave  # la serie da para que todos tengan valor


def test_serie_incremental_igual_que_de_una_vez():
    velas = serie_sintetica()
    serie = ind.Serie(ind.ema(9))
    for n in range(1, len(velas) + 1):
        serie.avanzar(Columnas(velas[:n]))
    assert serie.valores == ind.calcular(ind.ema(9), Columnas(velas))
