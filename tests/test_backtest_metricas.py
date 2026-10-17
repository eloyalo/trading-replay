"""Métricas, desglose y filtros del backtest (spec 008, RF-10 a RF-12), con operaciones hechas a mano."""

from datetime import datetime, timedelta

import pytest

from trading_replay.backtest import metricas as m
from trading_replay.backtest.ejecutor import OperacionBT

MEDIA_HORA = timedelta(minutes=30)


def op(numero, apertura, lado, neto, r, dudosa=False):
    riesgo = 100.0
    return OperacionBT(
        numero, "NQ", lado, 1, apertura, apertura + MEDIA_HORA, 100.0, 101.0, 99.0, 99.0, 102.0,
        "", "TP", round(neto + 5, 2), 5.0, riesgo if r is not None else None, dudosa,
    )


# Neto: +200, −100, −100, +300, +50. R: 2, −1, −1, 3, 0,5.
OPS = [
    op(1, datetime(2024, 1, 2, 10, 0), 1, 200, 2),  # martes, Nueva York
    op(2, datetime(2024, 1, 3, 10, 0), -1, -100, -1),  # miércoles, Nueva York
    op(3, datetime(2024, 1, 4, 4, 0), 1, -100, -1, dudosa=True),  # jueves, Londres
    op(4, datetime(2024, 1, 7, 19, 0), -1, 300, 3),  # domingo 19:00: lunes, Asia
    op(5, datetime(2025, 2, 3, 10, 0), 1, 50, 0.5),  # lunes, Nueva York
]


def test_resumen_a_mano():
    r = m.resumen(OPS, meses=12)
    assert (r["operaciones"], r["ganadoras"], r["perdedoras"], r["acierto"]) == (5, 3, 2, 0.6)
    assert (r["neto"], r["bruto"], r["comisiones"]) == (350, 375, 25)
    assert (r["ganancia_media"], r["perdida_media"], r["proporcion"]) == (183.33, -100, 1.833)
    assert r["profit_factor"] == 2.75  # 550 / 200
    assert (r["esperanza"], r["esperanza_r"]) == (70, 0.7)
    assert (r["r_ganadoras"], r["r_perdedoras"]) == (1.833, -1)
    # Acumulado 200, 100, 0, 300, 350: del máximo de 200 baja a 0.
    assert (r["drawdown"], r["drawdown_r"]) == (200, 2)
    assert (r["racha_ganadoras"], r["racha_perdedoras"]) == (2, 2)
    assert (r["duracion_media"], r["por_mes"], r["dudosas"]) == (30, 0.42, 1)


def test_sin_perdidas_y_sin_operaciones():
    assert m.resumen(OPS[:1])["profit_factor"] is None  # la interfaz pone ∞
    vacio = m.resumen([])
    assert (vacio["operaciones"], vacio["acierto"], vacio["neto"], vacio["por_mes"]) == (0, None, 0, None)


def test_desglose():
    d = m.desglose(OPS)
    assert d["anio"] == [
        {"grupo": 2024, "operaciones": 4, "acierto": 0.5, "neto": 300, "profit_factor": 2.5, "esperanza_r": 0.75},
        {"grupo": 2025, "operaciones": 1, "acierto": 1.0, "neto": 50, "profit_factor": None, "esperanza_r": 0.5},
    ]
    assert [(g["grupo"], g["operaciones"]) for g in d["sesion"]] == [("asia", 1), ("londres", 1), ("nueva_york", 3)]
    assert [(g["grupo"], g["operaciones"]) for g in d["dia"]] == [("lunes", 2), ("martes", 1), ("miércoles", 1), ("jueves", 1)]
    assert [(g["grupo"], g["neto"]) for g in d["lado"]] == [("largos", 150), ("cortos", 200)]


def test_filtro_nueva_york_2024():
    filtradas = m.filtrar(OPS, m.Filtro(anios={2024}, sesiones={"nueva_york"}))
    assert [o.numero for o in filtradas] == [1, 2]
    r = m.resumen(filtradas)
    assert (r["operaciones"], r["acierto"], r["neto"], r["profit_factor"]) == (2, 0.5, 100, 2.0)


@pytest.mark.parametrize(
    "filtro, numeros",
    [
        (m.Filtro(lado="cortos"), [2, 4]),
        (m.Filtro(dias={"lunes"}), [4, 5]),
        (m.Filtro(desde=datetime(2024, 1, 3), hasta=datetime(2024, 1, 7, 19, 0)), [2, 3]),
        (m.Filtro(), [1, 2, 3, 4, 5]),
    ],
)
def test_filtros(filtro, numeros):
    assert [o.numero for o in m.filtrar(OPS, filtro)] == numeros


def test_curva():
    puntos = m.curva(OPS)
    assert [p["value"] for p in puntos] == [200, 100, 0, 300, 350]
    assert puntos[0]["time"] == m.segundos_grafico(datetime(2024, 1, 2, 10, 30))
