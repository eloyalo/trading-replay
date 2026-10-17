"""Lo que necesita conocer quien escribe una estrategia (spec 008): `Estrategia`, `Parametro` y `Vela`.

Una estrategia es una subclase de `Estrategia` en un archivo de `estrategias/`. El ejecutor la avisa al
cerrar cada vela de su timeframe y ella decide con las velas cerradas, los indicadores y la hora.
La guía completa está en `estrategias/LEEME.md`.

Las horas son las del mercado (ET), como en el gráfico. Internamente, un instante es la hora ET en
segundos como si fuera UTC (el `time` de las velas del gráfico).
"""

from array import array
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from trading_replay.backtest import indicadores as ind
from trading_replay.historico import almacen

TIMEFRAMES = ("1m", "5m", "15m", "30m", "1h", "4h")
DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
EPOCA = datetime(1970, 1, 1)
_HORAS = [f"{m // 60:02d}:{m % 60:02d}" for m in range(1440)]


def a_fecha(t: int) -> datetime:
    """Instante en segundos (hora ET como si fuera UTC) → datetime ET sin zona."""
    return EPOCA + timedelta(seconds=t)


def a_segundos(momento: datetime) -> int:
    return int((momento - EPOCA).total_seconds())


def minutos_de(hora: str) -> int:
    """"09:30" → 570."""
    horas, minutos = hora.split(":")
    return int(horas) * 60 + int(minutos)


class ParametroNoValido(ValueError):
    pass


@dataclass(frozen=True)
class Parametro:
    """Un ajuste de la estrategia que se cambia desde la app sin tocar el código.

    El tipo sale del valor por defecto: entero, decimal, sí/no o texto. Con `opciones`, solo se puede
    elegir uno de esa lista.
    """

    defecto: int | float | bool | str
    texto: str = ""
    minimo: float | None = None
    maximo: float | None = None
    paso: float | None = None
    opciones: tuple | list | None = None

    @property
    def tipo(self) -> str:
        if isinstance(self.defecto, bool):
            return "bool"
        if isinstance(self.defecto, int):
            return "int"
        if isinstance(self.defecto, float):
            return "float"
        return "str"

    def validar(self, valor):
        """Convierte `valor` al tipo del parámetro y comprueba sus límites."""
        tipo = self.tipo
        try:
            if tipo == "bool":
                if not isinstance(valor, bool):
                    raise ValueError
            elif tipo == "int":
                if isinstance(valor, bool) or float(valor) != int(float(valor)):
                    raise ValueError
                valor = int(float(valor))
            elif tipo == "float":
                if isinstance(valor, bool):
                    raise ValueError
                valor = float(valor)
            else:
                valor = str(valor)
        except (TypeError, ValueError):
            raise ParametroNoValido(f"«{self.texto}» tiene que ser {NOMBRES_TIPO[tipo]}") from None
        if self.opciones is not None and valor not in self.opciones:
            raise ParametroNoValido(f"«{self.texto}» tiene que ser uno de: {', '.join(map(str, self.opciones))}")
        if self.minimo is not None and valor < self.minimo:
            raise ParametroNoValido(f"«{self.texto}» no puede ser menor que {self.minimo}")
        if self.maximo is not None and valor > self.maximo:
            raise ParametroNoValido(f"«{self.texto}» no puede ser mayor que {self.maximo}")
        return valor

    def api(self, clave: str) -> dict:
        return {
            "clave": clave,
            "texto": self.texto or clave,
            "tipo": self.tipo,
            "defecto": self.defecto,
            "minimo": self.minimo,
            "maximo": self.maximo,
            "paso": self.paso,
            "opciones": list(self.opciones) if self.opciones is not None else None,
        }


NOMBRES_TIPO = {"bool": "sí o no", "int": "un número entero", "float": "un número", "str": "un texto"}


class Valores:
    """Los valores de los parámetros elegidos al lanzar: `self.p.minutos_rango`."""

    def __init__(self, valores: dict):
        self.__dict__.update(valores)

    def __repr__(self):
        return f"Valores({self.__dict__})"


def valores_parametros(declarados: dict[str, Parametro], elegidos: dict | None) -> dict:
    """Valores de todos los parámetros: los elegidos, validados, y el defecto en los demás."""
    elegidos = elegidos or {}
    desconocidos = set(elegidos) - set(declarados)
    if desconocidos:
        raise ParametroNoValido(f"Parámetros desconocidos: {', '.join(sorted(desconocidos))}")
    return {clave: p.validar(elegidos[clave]) if clave in elegidos else p.defecto for clave, p in declarados.items()}


@dataclass(frozen=True, slots=True)
class Vela:
    inicio: datetime  # hora ET
    fin: datetime  # cuándo cierra: inicio + duración del timeframe
    open: float
    high: float
    low: float
    close: float
    volume: float


class VelasCerradas(Sequence):
    """Las velas cerradas hasta ahora, en orden: `velas[-1]` es la que acaba de cerrar.

    Solo crece cuando cierra una vela: aquí no hay nada del futuro. También se puede leer por
    columnas (`velas.close[-20:]`), que es más rápido para recorrer muchas.
    """

    def __init__(self, timeframe: str):
        self.duracion = almacen.TIMEFRAMES[timeframe] * 60
        self.time = array("q")  # inicio de cada vela, en segundos
        self.open, self.high, self.low, self.close, self.volume = (array("d") for _ in range(5))

    def __len__(self):
        return len(self.time)

    def __getitem__(self, i):
        if isinstance(i, slice):
            return [self[j] for j in range(*i.indices(len(self)))]
        t = self.time[i]  # da IndexError fuera de rango, también con negativos
        inicio = a_fecha(t)
        return Vela(
            inicio, inicio + timedelta(seconds=self.duracion), self.open[i], self.high[i], self.low[i], self.close[i], self.volume[i]
        )

    def anadir(self, t: int, o: float, h: float, l: float, c: float, v: float) -> None:
        self.time.append(t)
        self.open.append(o)
        self.high.append(h)
        self.low.append(l)
        self.close.append(c)
        self.volume.append(v)


def inicio_vela(t: int, tf: str) -> int:
    """Inicio de la vela de `tf` que contiene el instante `t` (segundos). Misma regla que
    `almacen.consultar` y `cubeta()` de `calculos.js`: 4h se alinea a las 18:00 ET."""
    segundos = almacen.TIMEFRAMES[tf] * 60
    if segundos >= 4 * 3600:
        return (t + ind.SEIS_HORAS) // segundos * segundos - ind.SEIS_HORAS
    return t // segundos * segundos


class Agregador:
    """Arma velas de un timeframe mayor con las velas cerradas del timeframe de la estrategia.

    Una vela mayor se da por cerrada cuando cierra su última vela pequeña, o cuando llega una vela
    pequeña que ya es de la siguiente (si la última faltaba, por la pausa diaria o un hueco). Nunca
    se ve una vela mayor a medias.
    """

    def __init__(self, timeframe: str):
        self.timeframe = timeframe
        self.velas = VelasCerradas(timeframe)
        self._actual: list | None = None  # [inicio, open, high, low, close, volume] de la vela en curso

    def anadir(self, t: int, o: float, h: float, l: float, c: float, v: float, fin: int) -> None:
        inicio = inicio_vela(t, self.timeframe)
        actual = self._actual
        if actual is not None and actual[0] != inicio:
            self._cerrar()
            actual = None
        if actual is None:
            self._actual = [inicio, o, h, l, c, v]
        else:
            actual[2], actual[3], actual[4], actual[5] = max(actual[2], h), min(actual[3], l), c, actual[5] + v
        if fin == inicio + self.velas.duracion:
            self._cerrar()

    def _cerrar(self) -> None:
        self.velas.anadir(*self._actual)
        self._actual = None


class Estrategia:
    """Base de las estrategias. Se rellenan `nombre`, `timeframe`, `parametros` y `al_cerrar_vela`."""

    nombre: str = ""
    timeframe: str = "5m"
    parametros: dict[str, Parametro] = {}

    def __init__(self, valores: dict | None = None):
        self.p = Valores(valores_parametros(self.parametros, valores))
        self.velas = VelasCerradas(self.timeframe)
        self._fin = 0  # instante del cierre de la vela actual, en segundos
        self._series: dict[tuple, ind.Serie] = {}
        self._agregadores: dict[str, Agregador] = {}
        self._bt = None  # el ejecutor, que pone las órdenes y las marcas
        self.simbolo: str | None = None  # instrumento del backtest; lo pone el ejecutor
        self.tick: float | None = None  # tick del instrumento, en puntos (0,25 en NQ y ES, 0,1 en GC)

    # --- Avisos: la estrategia sobrescribe los que use ---

    def al_empezar(self):
        """Una vez, antes de la primera vela."""

    def al_empezar_dia(self):
        """Al empezar cada día de trading (18:00 ET), antes de avisar de su primera vela."""

    def al_cerrar_vela(self, vela: Vela):
        """Al cerrar cada vela del timeframe. `vela` es la que acaba de cerrar (`self.velas[-1]`)."""
        raise NotImplementedError

    # --- Tiempo: todo en hora de Nueva York (ET), del cierre de la vela que acaba de cerrar ---

    @property
    def hora(self) -> str:
        """"HH:MM" del cierre de la vela. Se compara como texto: `self.hora >= "16:00"`."""
        return _HORAS[(self._fin % ind.UN_DIA) // 60]

    @property
    def instante(self) -> datetime:
        return a_fecha(self._fin)

    @property
    def fecha(self) -> date:
        """Fecha del día de trading: lo que cierra después de las 18:00 cuenta ya para el día siguiente."""
        return date(1970, 1, 1) + timedelta(days=ind.dia_trading(self._fin))

    @property
    def dia_semana(self) -> str:
        """"lunes", "martes"... del día de trading."""
        return DIAS[self.fecha.weekday()]

    @property
    def sesion(self) -> str | None:
        """"asia", "londres" o "nueva_york" (las del botón de momento aleatorio), o None de 17:00 a 18:00."""
        return almacen.sesion((self._fin % ind.UN_DIA) // 60)

    def entre(self, desde: str, hasta: str) -> bool:
        """Si la vela cierra después de `desde` y como tarde a `hasta`. Con `desde` mayor que `hasta`
        ("18:00", "03:00") el tramo cruza la medianoche."""
        hora = self.hora
        if desde <= hasta:
            return desde < hora <= hasta
        return hora > desde or hora <= hasta

    @staticmethod
    def hora_mas(hora: str, minutos: int) -> str:
        """`hora_mas("09:30", 15)` → "09:45"."""
        return _HORAS[(minutos_de(hora) + int(minutos)) % 1440]

    # --- Indicadores: valor en la vela que acaba de cerrar (o `atras` velas antes), o None ---

    def _indicador(self, clave: tuple, atras: int):
        serie = self._series.get(clave)
        if serie is None:
            nombre, *parametros = clave
            serie = self._series[clave] = ind.Serie(ind.INDICADORES[nombre](*parametros))
            serie.avanzar(self.velas)  # se pone al día con las velas que ya habían cerrado
        valores = serie.valores
        return valores[-1 - atras] if atras < len(valores) else None

    def ema(self, periodo: int, atras: int = 0) -> float | None:
        return self._indicador(("ema", int(periodo)), atras)

    def sma(self, periodo: int, atras: int = 0) -> float | None:
        return self._indicador(("sma", int(periodo)), atras)

    def rsi(self, periodo: int = 14, atras: int = 0) -> float | None:
        return self._indicador(("rsi", int(periodo)), atras)

    def atr(self, periodo: int = 14, atras: int = 0) -> float | None:
        return self._indicador(("atr", int(periodo)), atras)

    def vwap(self, atras: int = 0) -> float | None:
        return self._indicador(("vwap",), atras)

    def dia_anterior(self, atras: int = 0) -> ind.Niveles | None:
        """Máximo, mínimo y cierre del día de trading anterior: `.high`, `.low`, `.close`."""
        return self._indicador(("dia_anterior",), atras)

    def overnight(self, atras: int = 0) -> ind.Niveles | None:
        """Máximo y mínimo de 18:00 a 9:30 ET (`.high`, `.low`), con valor a partir de las 9:30."""
        return self._indicador(("overnight",), atras)

    def _avanzar_indicadores(self) -> None:
        for serie in self._series.values():
            serie.avanzar(self.velas)
        if self._agregadores:
            v = self.velas
            for agregador in self._agregadores.values():
                agregador.anadir(v.time[-1], v.open[-1], v.high[-1], v.low[-1], v.close[-1], v.volume[-1], v.time[-1] + v.duracion)

    # --- Otros timeframes ---

    def velas_de(self, timeframe: str) -> VelasCerradas:
        """Velas cerradas de un timeframe mayor que el de la estrategia (`self.velas_de("1h")`), armadas
        con las suyas. Se leen igual que `self.velas`: `[-1]` es la última que ha cerrado."""
        if timeframe == self.timeframe:
            return self.velas
        agregador = self._agregadores.get(timeframe)
        if agregador is None:
            base, mayor = almacen.TIMEFRAMES[self.timeframe], almacen.TIMEFRAMES.get(timeframe)
            if timeframe not in TIMEFRAMES or mayor <= base or mayor % base:
                raise ValueError(f"velas_de: el timeframe tiene que ser mayor que {self.timeframe} y múltiplo suyo: {', '.join(TIMEFRAMES)}")
            agregador = self._agregadores[timeframe] = Agregador(timeframe)
            v = self.velas
            for i in range(len(v)):  # se pone al día con las velas que ya habían cerrado
                agregador.anadir(v.time[i], v.open[i], v.high[i], v.low[i], v.close[i], v.volume[i], v.time[i] + v.duracion)
        return agregador.velas

    # --- Posición y órdenes ---

    def _ejecutor(self):
        if self._bt is None:
            raise RuntimeError("Las órdenes solo funcionan dentro de un backtest")
        return self._bt

    @property
    def posicion(self) -> int:
        """Contratos abiertos, con signo: positivo si es largo, negativo si es corto, 0 si no hay."""
        return self._ejecutor().posicion()

    @property
    def precio_entrada(self) -> float | None:
        """Precio medio de la posición abierta, o None."""
        return self._ejecutor().precio_entrada()

    @property
    def ordenes(self) -> list:
        """Órdenes pendientes (de entrada, SL y TP). Solo para consultar: `orden.tipo`, `.precio`, `.papel`."""
        return self._ejecutor().pendientes()

    def comprar(
        self,
        contratos: int = 1,
        tipo: str = "mercado",
        precio: float | None = None,
        sl: float | None = None,
        sl_puntos: float | None = None,
        tp: float | None = None,
        tp_puntos: float | None = None,
        tp_r: float | None = None,
        micro: bool = False,
        motivo: str = "",
    ):
        """Orden de compra. `tipo`: "mercado", "limite" o "stop" (estas dos con `precio`).
        SL en precio (`sl`) o en puntos desde la entrada (`sl_puntos`); TP en precio, en puntos o en R
        (`tp_r=2`: a dos veces la distancia de la entrada al SL). `motivo` se ve en la lista de operaciones.
        Devuelve el id de la orden."""
        return self._ejecutor().enviar(1, contratos, tipo, precio, sl, sl_puntos, tp, tp_puntos, tp_r, micro, motivo)

    def vender(
        self,
        contratos: int = 1,
        tipo: str = "mercado",
        precio: float | None = None,
        sl: float | None = None,
        sl_puntos: float | None = None,
        tp: float | None = None,
        tp_puntos: float | None = None,
        tp_r: float | None = None,
        micro: bool = False,
        motivo: str = "",
    ):
        """Como `comprar`, pero vende."""
        return self._ejecutor().enviar(-1, contratos, tipo, precio, sl, sl_puntos, tp, tp_puntos, tp_r, micro, motivo)

    def cerrar(self, motivo: str = ""):
        """Cancela las órdenes pendientes y cierra la posición a mercado."""
        self._ejecutor().cerrar(motivo)

    def cancelar(self, id_orden: str | None = None):
        """Cancela una orden de entrada pendiente, o todas si no se dice cuál. No toca el SL ni el TP."""
        self._ejecutor().cancelar(id_orden)

    def mover_sl(self, precio: float):
        """Lleva el SL de la posición abierta a `precio`."""
        self._ejecutor().mover_sl(precio)

    def tomar_parcial(self, contratos: int, precio: float):
        """Orden límite que cierra `contratos` de la posición a `precio` (por ejemplo, la mitad a 1 R).
        Solo reduce la posición: si la posición se cierra antes por otro lado, se cancela sola."""
        self._ejecutor().tomar_parcial(contratos, precio)

    # --- Marcas para el gráfico (RF-4) ---

    def _instante_de(self, hora) -> datetime:
        """Una hora "HH:MM" del día de trading actual (las de 18:00 en adelante son de la víspera)."""
        if isinstance(hora, datetime):
            return hora
        minutos = minutos_de(hora)
        dia = datetime.combine(self.fecha, datetime.min.time())
        if minutos >= ind.INICIO_DIA:
            dia -= timedelta(days=1)
        return dia + timedelta(minutes=minutos)

    def nivel(self, precio: float, texto: str = "", hasta=None):
        """Línea horizontal desde ahora hasta `hasta` ("HH:MM"; por defecto, las 17:00 del día)."""
        fin = self._instante_de(hasta or "17:00")
        self._ejecutor().marcar("nivel", self.instante, fin, precio, None, texto)

    def rango(self, desde, hasta, alto: float, bajo: float, texto: str = ""):
        """Rectángulo entre dos horas ("HH:MM" del día de trading) y dos precios."""
        self._ejecutor().marcar("rango", self._instante_de(desde), self._instante_de(hasta), alto, bajo, texto)

    def texto(self, texto: str, precio: float | None = None):
        """Un texto corto en la vela que acaba de cerrar, a la altura de `precio` (por defecto, su cierre)."""
        if precio is None:
            precio = self.velas.close[-1]
        self._ejecutor().marcar("texto", self.instante, None, precio, None, texto)
