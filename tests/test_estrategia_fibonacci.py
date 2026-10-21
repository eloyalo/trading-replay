"""`estrategias/fibonacci.py` con mercados en zigzag diseñados a mano, en velas de 1m y pivotes de 2 velas.

Camino (cada vela abre donde cerró la anterior; sin mechas): 15 velas planas en 150 desde las 09:00, baja de 150 a 100
de 5 en 5, sube de 100 a 200, retrocede hasta 130 y sube hasta 320.
Impulso: origen 100, final 200 (100 puntos, unos 20 ATR). El pivote alto se conoce 2 velas después de formarse.
  0,618 → 200 − 61,8 = 138,2 → al tick, 138,25 · 0,65 → 135 · 0,786 → 121,4 · extensión 1,0 → 200 · 1,618 → 261,8 → 261,75.
Stop: 121,4 − 2 ticks = 120,9 → al tick, 121,0.
"""

from datetime import datetime, timedelta

import numpy as np
import pytest

from trading_replay.backtest import cargador, ejecutor
from trading_replay.backtest.estrategia import a_segundos

UN_MINUTO = timedelta(minutes=1)
DIA = datetime(2024, 3, 12)  # martes
BASE = {"timeframe": "1m", "velas_pivote": 2}


def camino(*tramos, inicio=150.0, planas=15, hora="09:00", minutos_por_paso=1) -> list[tuple]:
    """Velas de 1m: `planas` en `inicio` y después, por cada (destino, paso), cierres cada `paso` hasta el destino.
    Con `minutos_por_paso` > 1 cada paso dura ese tiempo y el movimiento ocurre en su último minuto."""
    h, m = map(int, hora.split(":"))
    t = DIA + timedelta(hours=h, minutes=m)
    precio, filas = inicio, []
    for _ in range(planas):
        filas.append((t, precio, precio, precio, precio))
        t += UN_MINUTO
    for destino, paso in tramos:
        while (destino - precio) * paso > 0:
            for _ in range(minutos_por_paso - 1):
                filas.append((t, precio, precio, precio, precio))
                t += UN_MINUTO
            nuevo = precio + paso
            filas.append((t, precio, max(precio, nuevo), min(precio, nuevo), nuevo))
            precio, t = nuevo, t + UN_MINUTO
    return filas


def espejo(filas):
    return [(t, 300 - o, 300 - l, 300 - h, 300 - c) for t, o, h, l, c in filas]


BAJA, SUBE, RETROCEDE, REMONTA = (100, -5), (200, 5), (130, -5), (320, 5)
ALCISTA = camino(BAJA, SUBE, RETROCEDE, REMONTA)


def correr(filas, **valores):
    info = cargador.buscar("fibonacci")
    assert info.error is None, info.error
    columnas = {
        "t": np.array([a_segundos(f[0]) for f in filas], dtype="i8"),
        **{k: np.array([f[i + 1] for f in filas], dtype="f8") for i, k in enumerate(("open", "high", "low", "close"))},
        "volume": np.ones(len(filas)),
    }
    return ejecutor.Ejecutor(info.clase({**BASE, **valores}), "NQ").ejecutar(columnas)


# --- Versión base ---


def test_largo_en_el_0_618_con_stop_tras_el_0_786_y_objetivos_en_las_extensiones():
    resultado = correr(ALCISTA, contratos=2)
    [op] = resultado.operaciones
    assert (op.lado, op.cantidad, op.entrada, op.sl_inicial, op.tp_final) == (1, 2, 138.25, 121.0, 261.75)
    assert op.motivo_salida == "TP"
    # La mitad sale en 200 (extensión 1,0) y la otra mitad en 261,75 (1,618): (61,75 + 123,5) puntos × 20 $.
    assert op.pnl_bruto == pytest.approx((200 - 138.25 + 261.75 - 138.25) * 20)
    assert op.sl_final == 138.25  # tras la parcial, a break-even


def test_la_figura_de_fibonacci_se_dibuja_y_dura_lo_que_la_operacion():
    resultado = correr(ALCISTA, contratos=2)
    [op] = resultado.operaciones
    [fibo] = [m for m in resultado.marcas if m.tipo == "fibonacci"]
    assert (fibo.precio, fibo.precio2) == (100.0, 200.0)
    assert fibo.datos["origen"]["precio"] == 100.0 and fibo.datos["final"]["precio"] == 200.0
    assert 0.618 in fibo.datos["retrocesos"] and fibo.datos["extensiones"] == [1.0, 1.618]
    assert fibo.instante < datetime.fromisoformat(fibo.datos["final"]["instante"]) and fibo.fin >= op.cierre
    assert {"Orden larga", "Stop"} <= {m.texto for m in resultado.marcas}
    assert correr(ALCISTA, contratos=2, marcar=False).marcas == []


def test_corto_es_el_espejo_del_largo():
    [op] = correr(espejo(ALCISTA), contratos=2).operaciones
    # 0,618 → 100 + 61,8 = 161,8 → 161,75 · 0,786 → 178,6 + 2 ticks = 179,1 → 179,0 · extensión 1,618 → 38,2 → 38,25.
    assert (op.lado, op.cantidad, op.entrada, op.sl_inicial, op.tp_final) == (-1, 2, 161.75, 179.0, 38.25)
    assert op.motivo_salida == "TP"


def test_con_un_contrato_va_todo_al_ultimo_objetivo():
    [op] = correr(ALCISTA).operaciones
    assert (op.cantidad, op.tp_final, op.pnl_bruto) == (1, 261.75, pytest.approx((261.75 - 138.25) * 20))


def test_si_el_precio_no_llega_al_nivel_se_descarta_el_swing():
    # Retrocede solo hasta 150 y sigue: supera el máximo (200) sin haber entrado. (Ese tramo bajista de 50 puntos es a
    # su vez un impulso, y su retroceso daría un corto: aquí solo se miran los largos.)
    assert correr(camino(BAJA, SUBE, (150, -5), REMONTA), lados="solo largos").operaciones == []
    assert len(correr(ALCISTA, lados="solo largos").operaciones) == 1


def test_el_impulso_tiene_que_tener_un_tamano():
    assert correr(ALCISTA, impulso_min_atr=50.0).operaciones == []  # 100 puntos son unos 20 ATR
    assert correr(ALCISTA, impulso_max_atr=5.0).operaciones == []
    assert len(correr(ALCISTA, impulso_min_atr=10.0, impulso_max_atr=40.0).operaciones) == 1


def test_lados_y_sesiones():
    # Con la subida de 130 a 320 hay también un impulso bajista (200 → 130) cuyo retroceso da un corto.
    assert {o.lado for o in correr(ALCISTA, lados="solo cortos").operaciones} == {-1}
    assert {o.lado for o in correr(ALCISTA, lados="solo largos").operaciones} == {1}
    # Con los dos lados, el largo ocupa la posición mientras dura el retroceso del impulso bajista.
    assert {o.lado for o in correr(ALCISTA).operaciones} == {1}
    assert correr(ALCISTA, sesion_nueva_york=False).operaciones == []


def test_parametros_incoherentes_fallan_con_un_mensaje():
    casos = {
        "fondo de la zona": {"zona_hasta": 0.5},
        "invalidación": {"nivel_inval": 0.6},
        "solo valen con la entrada por rechazo": {"confirma_ema": True},
        "tantas fracciones": {"fracciones": "1.0"},
        "de menos a más": {"extensiones": "1.618, 1.0"},
        "lista de números": {"extensiones": "uno, dos"},
        "trailing": {"objetivos_modo": "tramos con trailing"},
        "Timeframe de los pivotes": {"tf_pivotes": "15m", "timeframe": "1h"},
    }
    for texto, valores in casos.items():
        with pytest.raises(cargador.ErrorEstrategia, match=texto):
            correr(ALCISTA, **valores)


# --- Variantes: invalidación y entrada ---

CAE_Y_REBOTA = camino(BAJA, SUBE, (160, -5), (118, -6), (160, 6), REMONTA)  # baja a 118: pasa del 0,786 (121,4), no del origen


def test_se_invalida_al_perder_el_nivel_antes_de_entrar():
    # Con entrada por rechazo: el precio pasa por la zona, cae a 118 (por debajo del 0,786) y rebota.
    assert correr(CAE_Y_REBOTA, entrada="rechazo", lados="solo largos").operaciones == []
    # Con la invalidación en el 0,95 (105) la caída a 118 no la invalida y el rebote sí entra.
    [op] = correr(CAE_Y_REBOTA, entrada="rechazo", lados="solo largos", nivel_inval=0.95).operaciones
    assert op.lado == 1 and op.sl_inicial == 104.5  # 100 + 5 puntos, 2 ticks más allá del 0,95 (105)
    # O invalidándola en el origen: tampoco la rompe 118.
    [op] = correr(CAE_Y_REBOTA, entrada="rechazo", lados="solo largos", invalidacion="origen").operaciones
    assert op.sl_inicial == 99.5


def test_entrada_por_rechazo_a_mercado_al_cerrar_de_vuelta_a_favor():
    # Toca la zona al llegar a 130 y la primera vela que cierra por encima del borde (138,25) es la de 140.
    [op] = correr(ALCISTA, entrada="rechazo", lados="solo largos", contratos=2).operaciones
    assert (op.lado, op.entrada, op.sl_inicial) == (1, 140.25, 121.0)  # compra al ASK: 140 + 1 tick


def test_rechazo_con_confirmaciones_de_ema_y_rsi():
    solo = dict(entrada="rechazo", lados="solo largos")
    assert len(correr(ALCISTA, confirma_ema=True, **solo).operaciones) == 1
    assert correr(ALCISTA, confirma_ema=True, confirma_ema_periodo=400, **solo).operaciones == []  # sin datos para esa EMA
    # El RSI venía de bajar 14 de 14 velas seguidas: cerca de 0.
    assert len(correr(ALCISTA, confirma_rsi=True, rsi_nivel=40, **solo).operaciones) == 1
    assert correr(ALCISTA, confirma_rsi=True, rsi_nivel=1, **solo).operaciones == []


def test_entrada_escalonada_mitad_en_cada_nivel():
    # Mitad en el 0,5 (150) y mitad en el 0,618 (138,25); sin tomas parciales, todo al último objetivo.
    [op] = correr(ALCISTA, entrada="escalonada", nivel_entrada=0.5, zona_hasta=0.618, contratos=2, lados="solo largos").operaciones
    assert (op.cantidad, op.entrada, op.tp_final) == (2, pytest.approx(144.125, abs=0.01), 261.75)
    assert op.pnl_bruto == pytest.approx((261.75 - 144.125) * 2 * 20)
    # Con un solo contrato entra en el primer escalón.
    [uno] = correr(ALCISTA, entrada="escalonada", nivel_entrada=0.5, zona_hasta=0.618, lados="solo largos").operaciones
    assert (uno.cantidad, uno.entrada) == (1, 150.0)


def test_limite_en_el_fondo_de_la_zona():
    [op] = correr(ALCISTA, limite_en="zona_hasta", lados="solo largos").operaciones
    assert op.entrada == 135.0


def test_otro_nivel_de_entrada():
    [op] = correr(ALCISTA, nivel_entrada=0.5, zona_hasta=0.5, lados="solo largos").operaciones
    assert op.entrada == 150.0


# --- Variantes: stop y objetivos ---


def test_stops():
    solo = dict(lados="solo largos")
    assert correr(ALCISTA, stop_ref="origen", **solo).operaciones[0].sl_inicial == 99.5
    assert correr(ALCISTA, stop_margen_ticks=10, **solo).operaciones[0].sl_inicial == 119.0  # 121,4 − 2,5 → 118,9 → 119
    op = correr(ALCISTA, stop_ref="atr", stop_atr_n=2.0, **solo).operaciones[0]
    assert 0 < op.entrada - op.sl_inicial < 20  # unos 2 ATR de 5 puntos


def test_objetivos():
    solo = dict(lados="solo largos", contratos=2)
    # Extensiones 1,272 y 2,0: 227,2 → 227,25 y 300.
    op = correr(ALCISTA, extensiones="1.272, 2.0", **solo).operaciones[0]
    assert op.tp_final == 300.0
    assert op.pnl_bruto == pytest.approx((227.25 - 138.25 + 300 - 138.25) * 20)
    # Objetivo único en 1,618.
    op = correr(ALCISTA, objetivos_modo="unico", **solo).operaciones[0]
    assert (op.tp_final, op.pnl_bruto) == (261.75, pytest.approx((261.75 - 138.25) * 2 * 20))
    # Tres tramos con fracciones distintas: 1 contrato en 200 y 1 en 261,75 (con 2 contratos se saltan los primeros).
    op = correr(ALCISTA, extensiones="0.5, 1.0, 1.618", fracciones="0.2, 0.3, 0.5", **solo).operaciones[0]
    assert op.tp_final == 261.75


def test_ultimo_tramo_con_trailing():
    # Sin TP en el último tramo: lo saca el trailing por mínimos de 3 velas cuando el precio se hunde.
    sube_y_cae = camino(BAJA, SUBE, RETROCEDE, (300, 5), (150, -10))
    op = correr(sube_y_cae, objetivos_modo="tramos con trailing", trailing="minimos", trailing_velas=3, contratos=2, lados="solo largos").operaciones[0]
    assert op.tp_final is None and op.sl_final > 250  # el stop siguió al precio hacia arriba
    assert op.pnl_bruto > (200 - 138.25 + 250 - 138.25) * 20  # mejor que salir por el stop inicial


# --- Variantes: swing ---


def test_reanclar_al_nuevo_maximo():
    # Tras el máximo de 200 sigue hasta 240 y se hunde de golpe a 140 antes de que se conozca el pivote de 240.
    sigue = camino(BAJA, SUBE, (180, -5), (240, 5))
    sigue += [(sigue[-1][0] + UN_MINUTO, 240, 240, 140, 140)]
    sigue += camino((300, 10), inicio=140, planas=0, hora="10:03")  # el camino empieza aparte: se reajusta abajo
    t0 = sigue[-1][0]
    filas = sigue[: -len(camino((300, 10), inicio=140, planas=0))]
    filas += [(filas[-1][0] + (i + 1) * UN_MINUTO, 140 + 10 * i, 140 + 10 * (i + 1), 140 + 10 * i, 140 + 10 * (i + 1)) for i in range(16)]
    del t0
    solo = dict(lados="solo largos")
    assert correr(filas, **solo, reanclar=False).operaciones == []  # 240 > 200: se fue sin nosotros
    [op] = correr(filas, **solo, reanclar=True).operaciones
    assert op.entrada == 153.5  # 0,618 del impulso 100 → 240: 240 − 86,52 = 153,48 → 153,5


def test_reentrada_en_el_mismo_swing():
    # Objetivo único en 190 (extensión 0,9): el swing sigue vivo tras el objetivo porque no supera el máximo (200).
    # Sube a 190 y vuelve a bajar a 130, y después remonta.
    vuelve = camino(BAJA, SUBE, RETROCEDE, (190, 5), (130, -5), REMONTA)
    comunes = dict(objetivos_modo="unico", extension_unica=0.9, lados="solo largos")
    # Sin reentrada, la subida 130 → 190 es un impulso nuevo y su 0,618 (190 − 37,08 = 152,92 → 153) la segunda entrada.
    assert [o.entrada for o in correr(vuelve, **comunes).operaciones] == [138.25, 153.0]
    # Con reentrada, el swing de 100 → 200 sigue valiendo y vuelve a entrar en su mismo 0,618.
    assert [o.entrada for o in correr(vuelve, reentrada=True, **comunes).operaciones] == [138.25, 138.25]


def test_pivotes_de_un_timeframe_mayor():
    # El mismo camino, con cada paso de 15 minutos: los pivotes se calculan con velas de 15m y la entrada con las de 1m.
    largo = camino(BAJA, SUBE, RETROCEDE, REMONTA, minutos_por_paso=15)
    todo_el_dia = dict(sesion_asia=True, sesion_londres=True, hora_cierre="", max_operaciones_dia=0, lados="solo largos", contratos=2)
    [op] = correr(largo, tf_pivotes="15m", **todo_el_dia).operaciones
    assert (op.entrada, op.sl_inicial, op.tp_final) == (138.25, 121.0, 261.75)


def test_el_swing_caduca_a_las_n_velas():
    # El retroceso hasta el 0,618 tarda unas 12 velas en llegar: con una vida de 3 velas la orden se cancela antes.
    assert correr(ALCISTA, max_velas_swing=3, lados="solo largos").operaciones == []
    assert len(correr(ALCISTA, max_velas_swing=30, lados="solo largos").operaciones) == 1
