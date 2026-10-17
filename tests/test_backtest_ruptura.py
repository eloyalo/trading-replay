"""La estrategia de ejemplo `estrategias/ruptura_rango.py` con días diseñados a mano (spec 008, criterio
de aceptación). Valores por defecto: rango de 15 minutos desde las 9:30, objetivo a 2 R, 1 contrato.

Cada día va de 09:30 a 16:10, plano salvo los minutos indicados. NQ: $20 por punto, ASK = BID + 0,25,
comisión de 5 $ por operación (2,50 por lado).
"""

from datetime import date, datetime, timedelta

import numpy as np
import pytest

from trading_replay.backtest import cargador, ejecutor, metricas
from trading_replay.backtest.estrategia import a_segundos


def dia(fecha: date, rango: tuple[float, float], plano: float, cambios: dict[str, tuple]) -> list[tuple]:
    """Minutos de un día: el de las 09:30 marca el rango (alto, bajo); los demás, a `plano` salvo los de
    `cambios` ("HH:MM" → (o, h, l, c)). Una entrada "HH:MM+" cambia el precio plano desde ese minuto."""
    alto, bajo = rango
    medio = (alto + bajo) / 2
    filas = []
    inicio = datetime.combine(fecha, datetime.min.time()) + timedelta(hours=9, minutes=30)
    for i in range(400):
        momento = inicio + timedelta(minutes=i)
        hora = f"{momento:%H:%M}"
        if f"{hora}+" in cambios:
            plano = cambios[f"{hora}+"]
        if i == 0:
            fila = (medio, alto, bajo, medio)
        elif hora in cambios:
            fila = cambios[hora]
        elif i < 15:
            fila = (medio,) * 4
        else:
            fila = (plano,) * 4
        filas.append((momento, *fila))
    return filas


DIAS = [
    # Martes: cierra por encima a las 09:55 (vela de 09:50) y sube hasta el TP.
    dia(date(2024, 3, 12), (110, 100), 105, {"09:50+": 111, "10:00": (111, 134, 111, 120), "10:01+": 120}),
    # Miércoles: cierra por debajo a las 09:50 y vuelve a por el SL.
    dia(date(2024, 3, 13), (210, 200), 199, {"09:50": (199, 211, 199, 205), "09:51+": 205}),
    # Jueves: no sale del rango.
    dia(date(2024, 3, 14), (310, 300), 305, {}),
    # Viernes: compra y en el mismo minuto toca el SL y el TP.
    dia(date(2024, 3, 15), (410, 400), 411, {"09:50": (411, 434, 399, 411), "09:51+": 405}),
    # Lunes: compra y a las 16:00 sigue abierta.
    dia(date(2024, 3, 18), (510, 500), 511, {"09:50+": 512}),
]


@pytest.fixture
def resultado():
    info = cargador.buscar("ruptura_rango")
    assert info.error is None, info.error
    filas = [f for d in DIAS for f in d]
    columnas = {
        "t": np.array([a_segundos(f[0]) for f in filas], dtype="i8"),
        **{k: np.array([f[i + 1] for f in filas], dtype="f8") for i, k in enumerate(("open", "high", "low", "close"))},
        "volume": np.ones(len(filas)),
    }
    return ejecutor.Ejecutor(info.clase(None), "NQ").ejecutar(columnas)


def test_operaciones_esperadas(resultado):
    resumen = [
        (o.apertura, o.lado, o.entrada, o.sl_inicial, o.tp_final, o.salida, o.motivo_salida, o.pnl_neto, o.dudosa)
        for o in resultado.operaciones
    ]
    assert resumen == [
        # Entrada al ASK 111,25; SL en el mínimo del rango (100); riesgo 11,25 → TP a 2 R = 133,75.
        (datetime(2024, 3, 12, 9, 55), 1, 111.25, 100, 133.75, 133.75, "TP", 22.5 * 20 - 5, False),
        # Venta al BID 199; SL en el máximo (210); riesgo 11 → TP 177. El SL salta a las 09:50.
        (datetime(2024, 3, 13, 9, 50), -1, 199, 210, 177, 210, "SL", -11 * 20 - 5, False),
        (datetime(2024, 3, 15, 9, 50), 1, 411.25, 400, 433.75, 400, "SL", -11.25 * 20 - 5, True),
        # A las 16:00 se cierra al BID del minuto de las 15:59: 512.
        (datetime(2024, 3, 18, 9, 50), 1, 511.25, 500, 533.75, 512, "16:00", 0.75 * 20 - 5, False),
    ]
    assert [o.motivo_entrada for o in resultado.operaciones] == ["Cierra por encima del rango", "Cierra por debajo del rango"] + [
        "Cierra por encima del rango"
    ] * 2


def test_rango_dibujado_cada_dia(resultado):
    rangos = [(m.instante, m.fin, m.precio, m.precio2) for m in resultado.marcas if m.tipo == "rango"]
    assert len(rangos) == 5
    assert rangos[0] == (datetime(2024, 3, 12, 9, 30), datetime(2024, 3, 12, 9, 45), 110, 100)


def test_metricas_a_mano(resultado):
    r = metricas.resumen(resultado.operaciones)
    # Netos: +445, −225, −230, +10.
    assert (r["operaciones"], r["acierto"], r["neto"]) == (4, 0.5, 0)
    assert r["profit_factor"] == 1.0  # 455 / 455
    assert (r["esperanza"], r["drawdown"]) == (0, 455)  # del máximo de 445 baja a −10
    assert (r["racha_ganadoras"], r["racha_perdedoras"], r["dudosas"]) == (1, 2, 1)
    assert r["esperanza_r"] == pytest.approx((445 / 225 - 225 / 220 - 230 / 225 + 10 / 225) / 4, abs=1e-3)
