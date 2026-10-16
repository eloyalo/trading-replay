"""Motor de órdenes (spec 005). Los precios esperados están calculados a mano en cada test."""

from datetime import datetime, timedelta

import pytest

from trading_replay.operativa.motor import COMPRA, VENTA, Costes, Minuto, Motor, Orden, OrdenNoValida

UN_MINUTO = timedelta(minutes=1)
T0 = datetime(2024, 3, 12, 9, 30)  # el reloj del replay está aquí al enviar las órdenes


def minuto(i: int, o: float, h: float, l: float, c: float) -> Minuto:
    return Minuto(T0 + i * UN_MINUTO, o, h, l, c)


def motor(precio: float = 100.0, simbolo: str = "NQ", balance: float = 50_000.0, **costes) -> Motor:
    """Motor con el último minuto visto en T0 − 1 min (mercado abierto) cerrando a `precio`."""
    m = Motor(Costes(**costes), balance)
    m.ultimo[simbolo] = minuto(-1, precio, precio, precio, precio)
    return m


def comprar(m: Motor, cantidad=1, contrato="NQ", tipo="mercado", instante=T0, **extra):
    return m.enviar(Orden(contrato, COMPRA, tipo, cantidad, **extra), instante)


def vender(m: Motor, cantidad=1, contrato="NQ", tipo="mercado", instante=T0, **extra):
    return m.enviar(Orden(contrato, VENTA, tipo, cantidad, **extra), instante)


def pendientes(m: Motor, papel=None):
    return [o for o in m.ordenes if o.estado == "pendiente" and (papel is None or o.papel == papel)]


def test_criterio_de_aceptacion_trade_con_sl_y_tp_a_mano():
    m = motor(100.10)  # BID 100,10 → tick 100,00; ASK 100,25
    [entrada] = comprar(m, 2, sl_puntos=10, tp_puntos=20)
    assert (entrada.precio, entrada.comision) == (100.25, 5.0)
    sl, tp = pendientes(m, "sl")[0], pendientes(m, "tp")[0]
    assert (sl.precio, tp.precio, sl.cantidad, tp.cantidad) == (90.25, 120.25, 2, 2)

    assert m.procesar("NQ", minuto(0, 100, 110, 95, 105)) == []
    # BID máximo 120,30 → 120,25: toca el TP.
    [salida] = m.procesar("NQ", minuto(1, 105, 120.30, 104, 118))
    assert (salida.precio, salida.lado, salida.cantidad) == (120.25, VENTA, 2)
    assert pendientes(m) == []  # el SL se cancela (OCO)

    pnl = (120.25 - 100.25) * 2 * 20 - 4 * 2.50
    assert m.balance == 50_000 + pnl == 50_790
    [operacion] = m.vaciar_cambios().operaciones
    assert (operacion.pnl_bruto, operacion.comisiones, operacion.pnl_neto) == (800, 10, 790)
    assert (operacion.entrada, operacion.salida, operacion.sl_inicial) == (100.25, 120.25, 90.25)
    assert (operacion.apertura, operacion.cierre) == (T0, T0 + UN_MINUTO)


@pytest.mark.parametrize(
    "contrato, simbolo, cierre, spread, desliz, compra, venta, comision",
    [
        ("NQ", "NQ", 18000.13, 1, 0, 18000.50, 18000.25, 2.50),  # 18000,13 se redondea a 18000,25
        ("MNQ", "NQ", 18000.13, 2, 1, 18001.00, 18000.00, 0.75),
        ("ES", "ES", 5000.37, 1, 1, 5000.75, 5000.00, 2.50),
        ("MES", "ES", 5000.13, 1, 1, 5000.75, 5000.00, 0.75),
        ("GC", "GC", 2000.06, 2, 1, 2000.40, 2000.00, 2.50),
        ("MGC", "GC", 2000.04, 1, 0, 2000.10, 2000.00, 0.75),
    ],
)
def test_spread_deslizamiento_y_tick(contrato, simbolo, cierre, spread, desliz, compra, venta, comision):
    m = motor(cierre, simbolo, spread_ticks=spread, deslizamiento_ticks=desliz)
    [c] = comprar(m, contrato=contrato)
    [v] = vender(m, contrato=contrato)
    assert (c.precio, v.precio, c.comision) == (compra, venta, comision)


def test_pnl_de_minis_y_micros():
    m = motor(2000.0, "GC")
    comprar(m, 3, contrato="MGC")  # ASK 2000,10
    m.ultimo["GC"] = minuto(0, 2003.3, 2003.3, 2003.3, 2003.3)
    vender(m, 3, contrato="MGC", instante=T0 + UN_MINUTO)  # BID 2003,30
    assert m.balance == round(50_000 + (2003.3 - 2000.1) * 3 * 10 - 6 * 0.75, 2) == 50_091.5


def test_mercado_con_el_mercado_cerrado_espera_a_la_apertura():
    m = motor(100.0)
    m.ultimo["NQ"] = minuto(-30, 100, 100, 100, 100)  # el último minuto es de hace media hora
    assert comprar(m) == []
    [e] = m.procesar("NQ", minuto(10, 105, 106, 104, 105))
    assert (e.precio, e.instante) == (105.25, T0 + 10 * UN_MINUTO)


def test_limite_al_tocar_y_con_hueco():
    m = motor(100.0)
    comprar(m, tipo="limite", precio=98)
    assert m.procesar("NQ", minuto(0, 100, 101, 98, 99)) == []  # ASK mínimo 98,25
    [e] = m.procesar("NQ", minuto(1, 99, 100, 97.75, 99))  # ASK mínimo 98: lo toca
    assert e.precio == 98.0

    vender(m, tipo="limite", precio=103, instante=T0 + 2 * UN_MINUTO)
    [e] = m.procesar("NQ", minuto(2, 104, 105, 103.5, 104))  # abre por encima: mejor precio
    assert e.precio == 104.0


def test_una_orden_no_se_evalua_con_minutos_anteriores_a_su_envio():
    m = motor(100.0)
    comprar(m, tipo="limite", precio=98, instante=T0 + 5 * UN_MINUTO)
    assert m.procesar("NQ", minuto(3, 97, 97, 90, 95)) == []
    assert len(pendientes(m)) == 1


def test_stop_validacion_y_hueco():
    m = motor(100.0, deslizamiento_ticks=1)  # BID 100, ASK 100,25
    with pytest.raises(OrdenNoValida):
        comprar(m, tipo="stop", precio=100.25)
    with pytest.raises(OrdenNoValida):
        vender(m, tipo="stop", precio=100)
    comprar(m, tipo="stop", precio=102)
    [e] = m.procesar("NQ", minuto(0, 100, 102, 99, 101))  # ASK máximo 102,25 ≥ 102
    assert e.precio == 102.25  # 102 + 1 tick de deslizamiento
    vender(m, tipo="stop", precio=99, instante=T0 + UN_MINUTO)
    [e] = m.procesar("NQ", minuto(1, 97, 98, 96, 97))  # abre por debajo: peor precio
    assert e.precio == 96.75


@pytest.mark.parametrize(
    "vela, papel, precio",
    [
        ((100, 125, 85, 100), "sl", 90.25),  # toca los dos: cuenta el SL
        ((121, 122, 80, 90), "tp", 121.0),  # abre más allá del TP: TP en la apertura
        ((89, 125, 85, 100), "sl", 89.0),  # abre más allá del SL: SL en la apertura
    ],
)
def test_sl_y_tp_en_el_mismo_minuto(vela, papel, precio):
    m = motor(100.10)
    comprar(m, sl_puntos=10, tp_puntos=20)  # entrada 100,25; SL 90,25; TP 120,25
    [e] = m.procesar("NQ", minuto(0, *vela))
    orden = next(o for o in m.vaciar_cambios().ordenes if o.id == e.orden)
    assert (orden.papel, e.precio) == (papel, precio)
    assert pendientes(m) == []


def test_minuto_de_la_entrada_limite_cuenta_el_sl_y_no_el_tp():
    m = motor(100.0)
    comprar(m, tipo="limite", precio=98, sl_puntos=5, tp_puntos=3)
    # Entra a 98 a mitad del minuto; el máximo (101) llega al TP pero no se sabe si fue después.
    [e] = m.procesar("NQ", minuto(0, 100, 101, 97.5, 100))
    assert e.precio == 98
    assert m.posiciones["NQ"].cantidad == 1
    [tp] = m.procesar("NQ", minuto(1, 100, 101.5, 99, 101))
    assert tp.precio == 101

    m = motor(100.0)
    comprar(m, tipo="limite", precio=98, sl_puntos=5, tp_puntos=3)
    # Aquí el mínimo llega al SL (93) en el mismo minuto de la entrada: lo peor es que fue después.
    entrada, sl = m.procesar("NQ", minuto(0, 100, 101, 92, 95))
    assert (entrada.precio, sl.precio) == (98, 93)
    assert m.posiciones["NQ"].cantidad == 0


def test_entrada_a_mercado_el_minuto_siguiente_cuenta_entero():
    m = motor(100.0)
    comprar(m, sl_puntos=5, tp_puntos=3)  # entrada 100,25; SL 95,25; TP 103,25
    [tp] = m.procesar("NQ", minuto(0, 100, 104, 99, 103))
    assert tp.precio == 103.25


def test_reducir_aumentar_y_dar_la_vuelta():
    m = motor(100.0)
    comprar(m, 3)  # 3 a 100,25
    m.ultimo["NQ"] = minuto(0, 110, 110, 110, 110)
    vender(m, 1, instante=T0 + UN_MINUTO)  # cierra 1 a 110: +195
    assert (m.posiciones["NQ"].cantidad, m.posiciones["NQ"].precio_medio) == (2, 100.25)
    m.ultimo["NQ"] = minuto(1, 104, 104, 104, 104)
    comprar(m, 1, instante=T0 + 2 * UN_MINUTO)  # 1 más a 104,25
    assert m.posiciones["NQ"].precio_medio == pytest.approx((2 * 100.25 + 104.25) / 3)
    m.ultimo["NQ"] = minuto(2, 106, 106, 106, 106)
    vender(m, 5, instante=T0 + 3 * UN_MINUTO)  # cierra 3 a 106 (+265) y abre 2 cortos
    posicion = m.posiciones["NQ"]
    assert (posicion.cantidad, posicion.precio_medio) == (-2, 106)

    primera, segunda = sorted(m.vaciar_cambios().operaciones, key=lambda o: o.apertura)
    assert (primera.lado, primera.cantidad, primera.entrada, primera.salida) == (COMPRA, 3, 101.25, 107)
    assert (primera.pnl_bruto, primera.comisiones, primera.cierre) == (460, 20, T0 + 3 * UN_MINUTO)
    assert (segunda.lado, segunda.cantidad, segunda.comisiones, segunda.cierre) == (VENTA, 2, 5, None)
    assert m.balance == 50_000 - (7.5 + 2.5 + 2.5 + 12.5) + 460


def test_sl_y_tp_solo_cierran_y_se_cancelan_al_quedar_plano():
    m = motor(100.0)
    comprar(m, 2, sl_puntos=10)
    vender(m, 1)  # queda 1 largo; el SL sigue siendo de 2
    [sl] = m.procesar("NQ", minuto(0, 100, 100, 85, 90))
    assert (sl.cantidad, m.posiciones["NQ"].cantidad) == (1, 0)

    m = motor(100.0)
    comprar(m, 1, sl_puntos=10, tp_puntos=10)
    vender(m, 1)  # cierra a mano: el SL y el TP sobran
    assert pendientes(m) == []


def test_cerrar_cancela_las_ordenes_del_contrato():
    m = motor(100.0)
    comprar(m, 2, sl_puntos=10, tp_puntos=10)
    comprar(m, 1, tipo="limite", precio=90)
    [cierre] = m.cerrar("NQ", T0)
    assert (cierre.lado, cierre.cantidad, cierre.precio) == (VENTA, 2, 100.0)
    assert pendientes(m) == []


def test_liquidar_cierra_al_ultimo_precio_aunque_el_mercado_este_cerrado():
    m = motor(100.0)
    vender(m, 2)  # 2 cortos a 100
    comprar(m, 1, tipo="limite", precio=90)
    m.ultimo["NQ"] = minuto(0, 95, 95, 95, 95)
    [e] = m.liquidar(T0 + timedelta(hours=3))
    assert (e.lado, e.cantidad, e.precio) == (COMPRA, 2, 95.25)
    assert pendientes(m) == [] and not m.hay_exposicion()


def test_pnl_abierto_a_lo_que_se_recibiria_al_cerrar():
    m = motor(100.0)
    comprar(m, 2)  # a 100,25
    m.ultimo["NQ"] = minuto(0, 101, 101, 101, 101)  # BID 101
    assert m.pnl_abierto(m.posiciones["NQ"]) == (101 - 100.25) * 2 * 20
    m = motor(100.0)
    vender(m, 1)  # a 100
    m.ultimo["NQ"] = minuto(0, 99, 99, 99, 99)  # ASK 99,25
    assert m.pnl_abierto(m.posiciones["NQ"]) == (100 - 99.25) * 20


def test_modificar_y_cancelar():
    m = motor(100.0)
    comprar(m, sl_puntos=10)
    [sl] = pendientes(m, "sl")
    with pytest.raises(OrdenNoValida):
        m.modificar(sl.id, 101)  # un stop de venta por encima del precio
    m.modificar(sl.id, 95.1)
    assert sl.precio == 95.0  # ajustado al tick
    [e] = m.procesar("NQ", minuto(0, 100, 100, 94.5, 96))
    assert e.precio == 95.0

    comprar(m, tipo="limite", precio=90, instante=T0 + UN_MINUTO)
    [limite] = pendientes(m)
    m.cancelar(limite.id)
    assert pendientes(m) == []
    with pytest.raises(KeyError):
        m.cancelar(limite.id)


@pytest.mark.parametrize(
    "orden",
    [
        Orden("XX", COMPRA, "mercado", 1),
        Orden("NQ", 2, "mercado", 1),
        Orden("NQ", COMPRA, "trailing", 1),
        Orden("NQ", COMPRA, "mercado", 0),
        Orden("NQ", COMPRA, "mercado", 51),
        Orden("NQ", COMPRA, "limite", 1),
        Orden("NQ", COMPRA, "mercado", 1, sl_puntos=0.1),
    ],
)
def test_ordenes_no_validas(orden):
    with pytest.raises(OrdenNoValida):
        motor().enviar(orden, T0)


def test_sin_precio_no_se_puede_operar():
    with pytest.raises(OrdenNoValida):
        Motor(Costes(), 0).enviar(Orden("ES", COMPRA, "mercado", 1), T0)
