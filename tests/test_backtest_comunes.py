"""Spec 012, RF-2 a RF-5: sesión, lados, límites y gestión de la posición de `backtest/comunes.py`.

Velas de 1m. Ejecución (spec 005): ASK = BID + 1 tick (0,25 en NQ); las órdenes a mercado salen al cierre
de la vela que las pide.
"""

from datetime import datetime, timedelta

import numpy as np
import pytest

from trading_replay.backtest import Estrategia, ejecutor
from trading_replay.backtest.comunes import (
    Operativa,
    _repartir,
    parametros_gestion,
    parametros_operativa,
    parametros_sesion,
)
from trading_replay.backtest.estrategia import ParametroNoValido, a_segundos

UN_MINUTO = timedelta(minutes=1)
DIA = datetime(2024, 3, 12)  # martes


def a(hora: str, dia: datetime = DIA) -> datetime:
    h, m = map(int, hora.split(":"))
    return dia + timedelta(hours=h, minutes=m)


def plano(desde: str, hasta: str, precio: float, dia: datetime = DIA) -> list[tuple]:
    inicio = a(desde, dia)
    n = (a(hasta, dia) - inicio) // UN_MINUTO
    return [(inicio + i * UN_MINUTO, precio, precio, precio, precio) for i in range(n)]


def minuto(hora: str, o, h, l, c, dia: datetime = DIA) -> tuple:
    return (a(hora, dia), o, h, l, c)


def columnas(filas):
    return {
        "t": np.array([a_segundos(f[0]) for f in filas], dtype="i8"),
        **{k: np.array([f[i + 1] for f in filas], dtype="f8") for i, k in enumerate(("open", "high", "low", "close"))},
        "volume": np.ones(len(filas)),
    }


class Prueba(Estrategia):
    """Entra cuando la hora de la vela está en `señales` ({"09:35": (lado, stop, objetivos)}), sin más."""

    nombre = "Prueba"
    timeframe = "1m"
    parametros = {**parametros_sesion(), **parametros_operativa(), **parametros_gestion()}
    señales: dict = {}

    def al_empezar(self):
        self.op = Operativa(self)
        self.intentos = []

    def al_cerrar_vela(self, vela):
        self.op.gestionar(vela)
        senal = self.señales.get(self.hora)
        if senal is None:
            return
        lado, stop, objetivos = senal
        puede = self.op.puede_abrir(lado)
        self.intentos.append((self.hora, puede))
        if puede:
            self.op.entrar(lado, stop, objetivos, motivo="prueba")


def correr(filas, señales, **valores):
    clase = type("P", (Prueba,), {"señales": señales})
    estrategia = clase(valores)
    resultado = ejecutor.Ejecutor(estrategia, "NQ").ejecutar(columnas(filas))
    return resultado, estrategia


# --- Reparto de contratos ---


def test_reparto_de_contratos_entre_objetivos():
    assert _repartir(2, [(110, 0.5), (120, 0.5)]) == [(110, 1), (120, 1)]
    assert _repartir(1, [(110, 0.5), (120, 0.5)]) == [(120, 1)]  # un solo contrato: va al último objetivo
    assert _repartir(4, [(110, 0.5), (120, 0.25), (130, 0.25)]) == [(110, 2), (120, 1), (130, 1)]
    assert _repartir(3, [(110, 0.5), (130, 0.5)]) == [(110, 1), (130, 2)]
    assert _repartir(2, [(None, 1.0)]) == [(None, 2)]


# --- Sesión (RF-2) ---


def test_solo_se_puede_abrir_en_las_sesiones_elegidas():
    señal = {"04:00": (1, 90, [(110, 1.0)])}
    _, e = correr(plano("00:00", "23:59", 100), señal, sesion_londres=True, sesion_nueva_york=False)
    assert e.intentos == [("04:00", True)]
    _, e = correr(plano("00:00", "23:59", 100), señal)  # solo Nueva York
    assert e.intentos == [("04:00", False)]
    _, e = correr(plano("00:00", "23:59", 100), {"20:00": (1, 90, [(110, 1.0)])}, sesion_asia=True, sesion_nueva_york=False)
    assert e.intentos == [("20:00", True)]
    _, e = correr(plano("00:00", "23:59", 100), {"10:00": (1, 90, [(110, 1.0)])}, sesion_asia=True, sesion_nueva_york=False)
    assert e.intentos == [("10:00", False)]


def test_la_ventana_horaria_manda_sobre_las_sesiones():
    senales = {"09:35": (1, 90, [(110, 1.0)])}
    _, e = correr(plano("00:00", "23:59", 100), senales, ventana_desde="10:00", ventana_hasta="11:00")
    assert e.intentos == [("09:35", False)]
    _, e = correr(plano("00:00", "23:59", 100), senales, ventana_desde="09:00", ventana_hasta="10:00", sesion_nueva_york=False)
    assert e.intentos == [("09:35", True)]


def test_ventana_incompleta_o_hora_mal_escrita_se_rechazan():
    clase = type("P", (Prueba,), {})
    for valores in ({"ventana_desde": "09:00"}, {"hora_cierre": "4pm"}, {"ventana_desde": "9:00", "ventana_hasta": "10:00"}):
        with pytest.raises(ParametroNoValido):
            Operativa(_con_valores(clase, valores))


def _con_valores(clase, valores):
    return clase(valores)


# --- Lados y límites (RF-3, RF-4) ---


def test_lados():
    senales = {"09:35": (1, 90, [(110, 1.0)]), "10:35": (-1, 110, [(90, 1.0)])}
    filas = plano("09:00", "12:00", 100)
    _, e = correr(filas, senales, lados="solo cortos", max_operaciones_dia=0)
    assert e.intentos == [("09:35", False), ("10:35", True)]
    _, e = correr(filas, senales, lados="solo largos")
    assert e.intentos[0] == ("09:35", True) and e.intentos[1][0] == "10:35"


def test_maximo_de_operaciones_al_dia_y_de_seguidas_en_un_sentido():
    # Tres largos (a las 09:35, 09:45 y 09:55) que se cierran por su stop (95) en el minuto siguiente.
    filas = plano("09:00", "11:00", 100)
    por_hora = {f[0]: f for f in filas}
    for hora in ("09:36", "09:46", "09:56"):
        por_hora[a(hora)] = minuto(hora, 100, 100, 90, 100)
    filas = [por_hora[k] for k in sorted(por_hora)]
    señales = {h: (1, 95, [(110, 1.0)]) for h in ("09:35", "09:45", "09:55")}

    def operaciones(**valores):
        return len(correr(filas, señales, **valores)[0].operaciones)

    assert operaciones() == 3  # por defecto, hasta 3 al día
    assert operaciones(max_operaciones_dia=2) == 2
    assert operaciones(max_operaciones_dia=0) == 3
    assert operaciones(max_seguidas_sentido=1) == 1
    assert operaciones(max_seguidas_sentido=2) == 2


# --- Gestión (RF-5) ---


def test_entrada_con_parcial_break_even_y_objetivo_final():
    # Largo de 2 contratos a mercado a las 09:35 (ASK 100,25), stop 99,25 (riesgo 1), parcial a 101,25 (1 R)
    # y objetivo a 102,25. Sube hasta 101,5 (parcial), vuelve a la entrada (break-even) y sale por el stop.
    filas = plano("09:00", "09:36", 100)
    filas += [minuto("09:36", 100, 101.5, 100, 101.5)]
    filas += plano("09:37", "09:40", 101.5)
    filas += [minuto("09:40", 101.5, 101.5, 99.9, 99.9)]
    filas += plano("09:41", "10:30", 99.9)
    resultado, e = correr(filas, {"09:35": (1, 99.25, [(101.25, 0.5), (102.25, 0.5)])}, contratos=2)
    [op] = resultado.operaciones
    assert (op.cantidad, op.entrada) == (2, 100.25)
    assert op.sl_final == 100.25  # llevado a break-even tras la parcial
    assert op.pnl_bruto == pytest.approx((101.25 - 100.25) * 20)  # la parcial gana 1 punto y el resto sale en tablas


def test_cierre_forzoso():
    filas = plano("09:00", "16:30", 100)
    resultado, _ = correr(filas, {"09:35": (1, 90, [(120, 1.0)])})
    [op] = resultado.operaciones
    assert op.motivo_salida == "Cierre forzoso"
    assert a("16:00") <= op.cierre <= a("16:01")


def test_sin_cierre_forzoso_la_operacion_sigue():
    filas = plano("09:00", "16:30", 100)
    resultado, _ = correr(filas, {"09:35": (1, 90, [(120, 1.0)])}, hora_cierre="")
    assert [o.motivo_salida for o in resultado.operaciones] == ["Fin de los datos"]


def test_cerrar_al_acabar_la_sesion():
    filas = plano("09:00", "18:00", 100)
    resultado, _ = correr(filas, {"09:35": (1, 90, [(120, 1.0)])}, hora_cierre="", ventana_desde="09:30", ventana_hasta="11:00", cerrar_fin_sesion=True)
    [op] = resultado.operaciones
    assert op.motivo_salida == "Fin de la sesión"


def test_trailing_por_minimos_solo_avanza():
    # Largo a las 09:35 (ASK 100,25) con stop 99, sin objetivo. El precio sube a 110 y baja a 106: el stop
    # (mínimo de las 3 últimas velas menos 2 ticks) sube con el precio y no retrocede cuando baja.
    filas = plano("09:00", "09:36", 100)
    for i, p in enumerate(range(101, 111)):
        filas.append(minuto(f"09:{36 + i}", p - 1, p, p - 1, p))
    filas += plano("09:46", "09:50", 110)
    filas += [minuto("09:50", 110, 110, 100, 100)]
    filas += plano("09:51", "10:30", 100)
    resultado, _ = correr(
        filas, {"09:35": (1, 99, [(None, 1.0)])}, trailing="minimos", trailing_velas=3, trailing_tras_parcial=False, be_tras_parcial=False
    )
    [op] = resultado.operaciones
    assert op.sl_final > 105  # subió siguiendo al precio
    assert op.salida >= op.sl_final - 0.5  # y salió cerca del stop movido, no del inicial
