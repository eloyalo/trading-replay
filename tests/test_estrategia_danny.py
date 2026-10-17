"""`estrategias/danny.py` (Danny strategy v1) con un día diseñado a mano. Solo zonas de 15m.

De 03:00 a 08:30, 22 velas de 15m pequeñas (cuerpo de 1 punto) que suben y bajan. A las 08:30 una vela base
roja (101 → 100,5, máximo 101,25, mínimo 100) y a las 08:45 una agresiva verde (100,5 → 105, cuerpo de 4,5).
Zona de demanda: AOI 101,25, nivel 1 101, 50 % 100,5 y nivel 3 100. A las 10:00 el precio vuelve a la zona.
"""

from datetime import datetime, timedelta

import numpy as np
import pytest

from trading_replay.backtest import cargador, ejecutor
from trading_replay.backtest.estrategia import a_segundos

UN_MINUTO = timedelta(minutes=1)
DIA = datetime(2024, 3, 12)
SOLO_15M = {"zonas_4h": False, "zonas_1h": False, "zonas_30m": False}


def a(hora: str) -> datetime:
    h, m = map(int, hora.split(":"))
    return DIA + timedelta(hours=h, minutes=m)


def vela15(inicio: datetime, o, h, l, c) -> list[tuple]:
    """Los 15 minutos de una vela de 15m con esos OHLC."""
    minutos = [(inicio, o, h, l, o)] + [(inicio + i * UN_MINUTO, o, o, o, o) for i in range(1, 14)]
    return minutos + [(inicio + 14 * UN_MINUTO, o, max(o, c), min(o, c), c)]


def plano(desde: datetime, hasta: datetime, precio) -> list[tuple]:
    n = (hasta - desde) // UN_MINUTO
    return [(desde + i * UN_MINUTO, precio, precio, precio, precio) for i in range(n)]


def dia(reaccion: list[tuple]) -> list[tuple]:
    filas = []
    for i in range(22):
        o, c = (100, 101) if i % 2 == 0 else (101, 100)
        filas += vela15(a("03:00") + i * 15 * UN_MINUTO, o, 101.5, 99.5, c)
    filas += vela15(a("08:30"), 101, 101.25, 100, 100.5)  # vela base
    filas += vela15(a("08:45"), 100.5, 105.25, 100.25, 105)  # vela agresiva
    filas += plano(a("09:00"), a("10:00"), 105)
    return filas + reaccion


def correr(filas):
    info = cargador.buscar("danny")
    assert info.error is None, info.error
    columnas = {
        "t": np.array([a_segundos(f[0]) for f in filas], dtype="i8"),
        **{k: np.array([f[i + 1] for f in filas], dtype="f8") for i, k in enumerate(("open", "high", "low", "close"))},
        "volume": np.ones(len(filas)),
    }
    return ejecutor.Ejecutor(info.clase(SOLO_15M), "NQ").ejecutar(columnas)


def test_rechazo_en_el_50_por_ciento_con_toma_parcial_y_objetivo():
    # La vela de 5m de las 10:00 baja hasta 100,4 (toca el 50 %) y cierra en 101,5: rechazo.
    reaccion = [(a("10:00"), 105, 105, 103, 103), (a("10:01"), 103, 103, 100.4, 100.6)] + plano(a("10:02"), a("10:05"), 101.5)
    # Después sube 0,25 por minuto hasta 107.
    reaccion += [(a("10:05") + i * UN_MINUTO, *(101.5 + 0.25 * i,) * 4) for i in range(23)] + plano(a("10:28"), a("11:00"), 107)
    resultado = correr(dia(reaccion))
    [op] = resultado.operaciones
    # Entrada al ASK 101,75. Stop 2 ticks bajo el nivel 3: 99,5. Riesgo 2,25 → mitad a 1 R (104), TP a 2 R (106,25).
    assert (op.lado, op.cantidad, op.entrada, op.sl_inicial, op.tp_final) == (1, 2, 101.75, 99.5, 106.25)
    assert op.salida == pytest.approx((104 + 106.25) / 2, abs=0.01)  # precio medio, guardado con dos decimales
    assert (op.motivo_salida, op.motivo_entrada) == ("TP", "Rechazo en el 50 % de demanda de 15m")
    assert op.pnl_neto == (2.25 + 4.5) * 20 - 10
    assert {(m.tipo, m.texto) for m in resultado.marcas} == {("rango", "Demanda 15m"), ("rango", "50 %"), ("rango", "Nivel 1")}


def test_si_cierra_por_debajo_del_50_por_ciento_la_zona_deja_de_valer():
    # La vela de 5m de las 10:00 cierra en 100,25, por debajo del 50 %; después vuelve a 101,5 y rebota.
    reaccion = [(a("10:00"), 105, 105, 100.25, 100.25)] + plano(a("10:01"), a("10:05"), 100.25)
    reaccion += [(a("10:05"), 100.25, 101.5, 100.25, 101.5)] + plano(a("10:06"), a("11:00"), 101.5)
    assert correr(dia(reaccion)).operaciones == []
