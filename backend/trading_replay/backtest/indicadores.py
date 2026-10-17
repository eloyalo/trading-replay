"""Indicadores del gráfico (spec 004) en Python, para las estrategias del backtest (spec 008, RF-2).

Es una copia de `INDICADORES` de `frontend/calculos.js`, con el mismo cálculo paso a paso, para que una
estrategia vea los mismos valores que el gráfico. Si se toca uno, hay que tocar el otro: un test los
compara lanzando Node (`tests/test_backtest_indicadores.py`).

Cada indicador es una función que recibe sus parámetros y devuelve `paso(velas, i, previo)`, que calcula
la vela `i` a partir del estado que dejó la `i - 1` (`previo`, None en la primera) y devuelve
`(valor, estado)`. `velas` tiene las columnas `time`, `high`, `low`, `close` y `volume`, cada una
indexable por posición; `time` es la hora ET de inicio en segundos como si fuera UTC, como en el gráfico.
"""

from dataclasses import dataclass

SEIS_HORAS = 6 * 3600
UN_DIA = 86400
FIN_OVERNIGHT = 9 * 60 + 30  # 9:30 ET, apertura de la sesión de Nueva York
INICIO_DIA = 18 * 60  # 18:00 ET, inicio del día de trading


def dia_trading(t: int) -> int:
    """Número del día de trading (empieza a las 18:00 ET de la víspera)."""
    return (t + SEIS_HORAS) // UN_DIA


def minuto_del_dia(t: int) -> int:
    return (t % UN_DIA) // 60


@dataclass(frozen=True)
class Niveles:
    """Máximo, mínimo y, si lo hay, cierre de un tramo (día anterior u overnight)."""

    high: float
    low: float
    close: float | None = None


def sma(periodo: int):
    def paso(velas, i, previo):
        sale = velas.close[i - periodo] if i >= periodo else 0
        suma = (previo["suma"] if previo else 0) + velas.close[i] - sale
        return (suma / periodo if i >= periodo - 1 else None), {"suma": suma}

    return paso


def ema(periodo: int):
    """Arranca con la SMA de las `periodo` primeras velas."""
    alfa = 2 / (periodo + 1)

    def paso(velas, i, previo):
        cierre = velas.close[i]
        if i < periodo:
            suma = (previo["suma"] if previo else 0) + cierre
            valor = suma / periodo if i == periodo - 1 else None
            return valor, {"suma": suma, "ema": valor}
        valor = alfa * cierre + (1 - alfa) * previo["ema"]
        return valor, {"ema": valor}

    return paso


def rsi(periodo: int):
    """Wilder: arranca con la media simple de las `periodo` primeras subidas y bajadas."""

    def paso(velas, i, previo):
        if i == 0:
            return None, {"subidas": 0, "bajadas": 0}
        cambio = velas.close[i] - velas.close[i - 1]
        sube = max(cambio, 0)
        baja = max(-cambio, 0)
        subidas, bajadas = previo["subidas"], previo["bajadas"]
        if i < periodo:
            return None, {"subidas": subidas + sube, "bajadas": bajadas + baja}
        if i == periodo:
            subidas = (subidas + sube) / periodo
            bajadas = (bajadas + baja) / periodo
        else:
            subidas = (subidas * (periodo - 1) + sube) / periodo
            bajadas = (bajadas * (periodo - 1) + baja) / periodo
        if bajadas == 0:
            valor = 50 if subidas == 0 else 100
        else:
            valor = 100 - 100 / (1 + subidas / bajadas)
        return valor, {"subidas": subidas, "bajadas": bajadas}

    return paso


def atr(periodo: int):
    """Wilder sobre el rango verdadero: arranca con la media simple de los `periodo` primeros."""

    def paso(velas, i, previo):
        high, low = velas.high[i], velas.low[i]
        if i:
            anterior = velas.close[i - 1]
            rango = max(high - low, abs(high - anterior), abs(low - anterior))
        else:
            rango = high - low
        if i < periodo:
            suma = (previo["suma"] if previo else 0) + rango
            valor = suma / periodo if i == periodo - 1 else None
            return valor, {"suma": suma, "atr": valor}
        valor = (previo["atr"] * (periodo - 1) + rango) / periodo
        return valor, {"atr": valor}

    return paso


def vwap():
    """Precio típico ponderado por volumen, desde el inicio del día de trading."""

    def paso(velas, i, previo):
        dia = dia_trading(velas.time[i])
        tipico = (velas.high[i] + velas.low[i] + velas.close[i]) / 3
        mismo_dia = previo is not None and previo["dia"] == dia
        pv = (previo["pv"] if mismo_dia else 0) + tipico * velas.volume[i]
        vol = (previo["vol"] if mismo_dia else 0) + velas.volume[i]
        return (pv / vol if vol > 0 else tipico), {"dia": dia, "pv": pv, "vol": vol}

    return paso


def dia_anterior():
    """Máximo, mínimo y cierre del día de trading anterior con datos. El primer día puede estar
    incompleto (los datos empiezan a mitad de día), así que no sirve de "día anterior"."""

    def paso(velas, i, previo):
        high, low, close = velas.high[i], velas.low[i], velas.close[i]
        dia = dia_trading(velas.time[i])
        if previo is not None and previo["dia"] == dia:
            hoy = previo["hoy"]
            hoy = {"high": max(hoy["high"], high), "low": min(hoy["low"], low), "close": close, "completo": hoy["completo"]}
            anterior = previo["anterior"]
        else:
            hoy = {"high": high, "low": low, "close": close, "completo": previo is not None}
            anterior = previo["hoy"] if previo is not None and previo["hoy"]["completo"] else None
        valor = Niveles(anterior["high"], anterior["low"], anterior["close"]) if anterior else None
        return valor, {"dia": dia, "hoy": hoy, "anterior": anterior}

    return paso


def overnight():
    """Máximo y mínimo de 18:00 a 9:30 ET, con valor desde las 9:30 hasta el final del día.
    Solo es exacto en timeframes de 30m o menos (la vela que contiene las 9:30 empieza a las 9:30)."""

    def paso(velas, i, previo):
        t = velas.time[i]
        dia = dia_trading(t)
        minuto = minuto_del_dia(t)
        en_overnight = minuto >= INICIO_DIA or minuto < FIN_OVERNIGHT
        mismo_dia = previo is not None and previo["dia"] == dia
        alto = previo["alto"] if mismo_dia else None
        bajo = previo["bajo"] if mismo_dia else None
        completo = previo["completo"] if mismo_dia else previo is not None
        if en_overnight:
            alto = velas.high[i] if alto is None else max(alto, velas.high[i])
            bajo = velas.low[i] if bajo is None else min(bajo, velas.low[i])
        valor = Niveles(alto, bajo) if not en_overnight and completo and alto is not None else None
        return valor, {"dia": dia, "alto": alto, "bajo": bajo, "completo": completo}

    return paso


INDICADORES = {
    "sma": sma,
    "ema": ema,
    "rsi": rsi,
    "atr": atr,
    "vwap": vwap,
    "dia_anterior": dia_anterior,
    "overnight": overnight,
}


class Serie:
    """Valores de un indicador vela a vela, calculados según van cerrando las velas."""

    def __init__(self, paso):
        self.paso = paso
        self.valores: list = []
        self._estado = None

    def avanzar(self, velas) -> None:
        """Calcula las velas de `velas` que todavía no tienen valor (normalmente, la última)."""
        for i in range(len(self.valores), len(velas)):
            valor, self._estado = self.paso(velas, i, self._estado)
            self.valores.append(valor)


def calcular(paso, velas) -> list:
    """Valores de un indicador sobre todas las velas."""
    serie = Serie(paso)
    serie.avanzar(velas)
    return serie.valores
