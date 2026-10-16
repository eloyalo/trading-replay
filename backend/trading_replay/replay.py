"""Sesión de replay: el reloj que decide hasta dónde se puede ver el histórico.

El instante es una hora ET sin zona. Se ven los minutos que empiezan antes del instante:
a las 10:37 se ve hasta la vela de 1m de las 10:36. Es la misma regla que
`almacen.consultar(..., hasta=instante)`.
"""

import random
import threading
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone

from trading_replay.historico import almacen

UN_MINUTO = timedelta(minutes=1)
# Minutos siguientes que se guardan en memoria por instrumento, para que avanzar no consulte el Parquet.
BLOQUE = timedelta(days=7)
# El momento aleatorio deja contexto previo y futuro que jugar.
MARGEN_INICIO = timedelta(days=31)
MARGEN_FIN = timedelta(days=7)
SESIONES = {"cualquiera": None, "asia": "asia", "londres": "londres", "nueva_york": "nueva_york"}
MAX_MINUTOS = 500

_azar = random.Random()


def fin_cubeta(momento: datetime, tf: str) -> datetime:
    """Final de la vela de `tf` que contiene el minuto `momento` (hora ET).

    Misma alineación que `almacen.consultar`: 4h y 1D cuentan desde las 18:00 ET.
    """
    minutos = almacen.TIMEFRAMES[tf]
    desfase = almacen.DESFASE_DIA if minutos >= 240 else timedelta(0)
    desplazado = momento + desfase
    medianoche = datetime.combine(desplazado.date(), datetime.min.time())
    transcurridos = (desplazado - medianoche) // UN_MINUTO
    return medianoche + timedelta(minutes=(transcurridos // minutos + 1) * minutos) - desfase


def vela_grafico(fila: tuple) -> dict:
    """Minuto de `almacen.minutos` en el formato de `almacen.consultar` (hora ET como si fuera UTC)."""
    et, o, h, l, c, v = fila
    tiempo = int(et.replace(tzinfo=timezone.utc).timestamp())
    return {"time": tiempo, "open": o, "high": h, "low": l, "close": c, "volume": round(v, 4)}


class SesionReplay:
    """Reloj del replay y, por instrumento, los minutos siguientes en memoria.

    Cada instrumento lleva su propio cursor: el del gráfico avanza con `avanzar()` y los demás
    (los que tienen órdenes o posiciones, spec 005) se leen con `minutos_entre()`.
    """

    def __init__(self, instante: datetime, id_sesion: str | None = None):
        self.id = id_sesion or uuid.uuid4().hex[:12]
        self.instante = instante
        self._bufer: dict[str, deque] = {}
        self._cargado_hasta: dict[str, datetime] = {}
        self._fin_datos: dict[str, datetime] = {}
        self._ultimo: dict[str, tuple | None] = {}  # último minuto visto de cada instrumento
        self._visto_hasta: dict[str, datetime] = {}
        self._cerrojo = threading.Lock()

    def _siguiente(self, simbolo: str, desde: datetime) -> tuple | None:
        """Primer minuto con datos que empieza en `desde` o después, o None si no quedan."""
        bufer = self._bufer.setdefault(simbolo, deque())
        while bufer and bufer[0][0] < desde:
            bufer.popleft()
        if bufer:
            return bufer[0]
        if simbolo not in self._fin_datos:
            self._fin_datos[simbolo] = almacen.rango(simbolo)[1]
        carga = max(self._cargado_hasta.get(simbolo, desde), desde)
        while not bufer and carga <= self._fin_datos[simbolo]:
            hasta = carga + BLOQUE
            bufer.extend(almacen.minutos(simbolo, carga, hasta))
            carga = hasta
        self._cargado_hasta[simbolo] = carga
        return bufer[0] if bufer else None

    def _visto(self, simbolo: str, filas: list[tuple], hasta: datetime) -> None:
        if filas:
            self._ultimo[simbolo] = filas[-1]
        self._visto_hasta[simbolo] = hasta

    def avanzar(self, simbolo: str, minutos: int | None = None, tf: str | None = None) -> tuple[list[tuple], bool]:
        """Avanza `minutos` minutos con datos, o hasta cerrar la siguiente vela de `tf`.

        Devuelve los minutos nuevos (filas de `almacen.minutos`) y si se han acabado los datos.
        """
        with self._cerrojo:
            nuevas = []
            siguiente = self._siguiente(simbolo, self.instante)
            limite = fin_cubeta(siguiente[0], tf) if tf and siguiente else None
            while siguiente and (siguiente[0] < limite if limite else len(nuevas) < minutos):
                nuevas.append(siguiente)
                self.instante = siguiente[0] + UN_MINUTO
                siguiente = self._siguiente(simbolo, self.instante)
            if limite:
                self.instante = limite
            # Sin minutos nuevos y sin haberlo mirado antes, el último precio sigue sin saberse.
            if nuevas or simbolo in self._visto_hasta:
                self._visto(simbolo, nuevas, self.instante)
            return nuevas, siguiente is None

    def _tomar(self, simbolo: str, desde: datetime, hasta: datetime) -> list[tuple]:
        filas = []
        siguiente = self._siguiente(simbolo, desde)
        while siguiente and siguiente[0] < hasta:
            filas.append(siguiente)
            siguiente = self._siguiente(simbolo, siguiente[0] + UN_MINUTO)
        self._visto(simbolo, filas, hasta)
        return filas

    def minutos_entre(self, simbolo: str, desde: datetime, hasta: datetime) -> list[tuple]:
        """Minutos de `simbolo` con inicio en [desde, hasta), para el tramo que acaba de avanzar el reloj."""
        with self._cerrojo:
            return self._tomar(simbolo, desde, hasta)

    def ultimo(self, simbolo: str) -> tuple | None:
        """Último minuto de `simbolo` que empieza antes del instante (el precio actual), o None."""
        with self._cerrojo:
            visto = self._visto_hasta.get(simbolo)
            if visto is None:
                # Primera vez: se busca hacia atrás (una consulta) y desde aquí se sigue con el búfer.
                filas = almacen.minutos(simbolo, self.instante - BLOQUE, self.instante)
                self._ultimo[simbolo] = filas[-1] if filas else None
                self._visto_hasta[simbolo] = self.instante
            elif visto < self.instante:
                self._tomar(simbolo, visto, self.instante)
            return self._ultimo[simbolo]


_sesion: SesionReplay | None = None


def actual() -> SesionReplay | None:
    return _sesion


def iniciar(instante: datetime, id_sesion: str | None = None) -> SesionReplay:
    """Empieza un replay; si había otro, lo sustituye. `id_sesion` sirve para retomar uno."""
    global _sesion
    _sesion = SesionReplay(instante, id_sesion)
    return _sesion


def terminar() -> None:
    global _sesion
    _sesion = None


def instante_aleatorio(simbolo: str, sesion: str, azar: random.Random = _azar) -> datetime | None:
    """Inicio de un minuto con datos al azar, fuera del primer mes y de la última semana."""
    inicio, fin = almacen.rango(simbolo)
    return almacen.minuto_aleatorio(simbolo, inicio + MARGEN_INICIO, fin - MARGEN_FIN, SESIONES[sesion], azar)
