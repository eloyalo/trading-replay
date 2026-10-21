"""`estrategias/ema_pullback.py` con mercados diseñados a mano, en velas de 1m.

Subida de 0,5 por minuto desde las 03:00 (cierres 100,5 … 310 a las 09:59). Con esa pendiente, las medias van
unos 4 (EMA 9), 9,5 (EMA 20) y 24,5 (EMA 50) puntos por debajo del cierre. Después, el pullback:
  10:00 baja a 307 (sin tocar la EMA 20) · 10:01 baja a 304 y toca la EMA 20 · 10:02 vela alcista que cierra en
  308 por encima de la EMA 9, con mínimo de 303,75.
Entrada a mercado al cierre de las 10:02: ASK 308,25. Stop 303,75 − 2 ticks = 303,25 (riesgo 5) y objetivo a 2 R: 318,25.
"""

from datetime import datetime, timedelta

import numpy as np
import pytest

from trading_replay.backtest import cargador, ejecutor
from trading_replay.backtest.estrategia import ParametroNoValido, a_segundos

UN_MINUTO = timedelta(minutes=1)
DIA = datetime(2024, 3, 12)  # martes
C0 = 310.0


def a(hora: str, dia: datetime = DIA) -> datetime:
    h, m = map(int, hora.split(":"))
    return dia + timedelta(hours=h, minutes=m)


def rampa(inicio: datetime, minutos: int, precio: float, paso: float) -> list[tuple]:
    filas = []
    for i in range(minutos):
        o = precio + paso * i
        c = o + paso
        filas.append((inicio + i * UN_MINUTO, o, max(o, c), min(o, c), c))
    return filas


def plano(inicio: datetime, minutos: int, precio: float) -> list[tuple]:
    return [(inicio + i * UN_MINUTO, precio, precio, precio, precio) for i in range(minutos)]


def pullback_alcista(previo: list[tuple] | None = None) -> list[tuple]:
    previo = previo if previo is not None else rampa(a("03:00"), 420, 100, 0.5)
    filas = previo + [
        (a("10:00"), C0, C0, C0 - 3, C0 - 3),
        (a("10:01"), C0 - 3, C0 - 3, C0 - 6, C0 - 6),
        (a("10:02"), C0 - 6, C0 - 1.75, C0 - 6.25, C0 - 2),
    ]
    return filas + rampa(a("10:03"), 120, C0 - 2, 0.5)


def espejo(filas: list[tuple]) -> list[tuple]:
    return [(t, 620 - o, 620 - l, 620 - h, 620 - c) for t, o, h, l, c in filas]


def correr(filas, **valores):
    info = cargador.buscar("ema_pullback")
    assert info.error is None, info.error
    columnas = {
        "t": np.array([a_segundos(f[0]) for f in filas], dtype="i8"),
        **{k: np.array([f[i + 1] for f in filas], dtype="f8") for i, k in enumerate(("open", "high", "low", "close"))},
        "volume": np.ones(len(filas)),
    }
    estrategia = info.clase({"timeframe": "1m", **valores})
    return ejecutor.Ejecutor(estrategia, "NQ").ejecutar(columnas)


# --- Versión base ---


def test_largo_al_pullback_a_la_ema_20_con_stop_bajo_el_pullback_y_objetivo_a_2r():
    resultado = correr(pullback_alcista())
    [op] = resultado.operaciones
    assert (op.lado, op.cantidad, op.entrada, op.sl_inicial, op.tp_final) == (1, 1, 308.25, 303.25, 318.25)
    assert op.motivo_salida == "TP"
    assert "20" in op.motivo_entrada
    assert {m.texto for m in resultado.marcas} >= {"Toque", "Entrada larga", "Stop"}


def test_corto_es_el_espejo_del_largo():
    resultado = correr(espejo(pullback_alcista()))
    [op] = resultado.operaciones
    # Vende al BID 312 (620 − 308); stop: máximo 316,25 + 2 ticks; objetivo a 2 R.
    assert (op.lado, op.entrada, op.sl_inicial) == (-1, 312.0, 316.75)
    assert op.tp_final == 312.0 - 2 * 4.75 == 302.5
    assert op.motivo_salida == "TP"


def test_lados():
    assert correr(pullback_alcista(), lados="solo cortos").operaciones == []
    assert len(correr(pullback_alcista(), lados="solo largos").operaciones) == 1
    assert correr(espejo(pullback_alcista()), lados="solo largos").operaciones == []


def test_sin_tendencia_no_hay_entrada():
    # Antes del pullback el mercado está plano: las medias no están apiladas.
    assert correr(pullback_alcista(plano(a("03:00"), 420, C0))).operaciones == []


def test_fuera_de_la_sesion_no_se_abre():
    assert correr(pullback_alcista(), sesion_nueva_york=False).operaciones == []
    assert len(correr(pullback_alcista(), sesion_nueva_york=False, sesion_londres=False, sesion_asia=False, ventana_desde="10:00", ventana_hasta="11:00").operaciones) == 1


def test_el_cierre_forzoso_saca_la_operacion():
    # Objetivo muy lejano y cierre forzoso a las 10:30.
    resultado = correr(pullback_alcista(), objetivo_r=20.0, hora_cierre="10:30")
    [op] = resultado.operaciones
    assert op.motivo_salida == "Cierre forzoso"


def test_parametros_incoherentes_fallan_con_un_mensaje():
    casos = {
        "desactivada": {"periodo_media": 0},
        "al menos una media": {"periodo_rapida": 0, "periodo_media": 0, "periodo_lenta": 0},
        "al menos un stop": {"stop_pullback": False},
        "entrada límite": {"entrada": "limite"},
        "Timeframe mayor": {"f_tf_mayor": True, "tf_mayor": "15m", "timeframe": "1h"},
    }
    for texto, valores in casos.items():
        with pytest.raises(cargador.ErrorEstrategia, match=texto):
            correr(pullback_alcista(), **valores)


# --- Variantes: tendencia ---
# Valores reales en la vela del toque (la estrategia la ve a las 10:02): EMA 9 = 307,04, EMA 20 = 305,28, EMA 50 = 298,34.


def test_filtro_de_pendiente():
    # La EMA 9 de hace 2 velas valía 308 y ahora 307,04: baja. La EMA 50 sigue subiendo.
    assert correr(pullback_alcista(), f_pendiente=True, pendiente_media="rapida", pendiente_velas=2).operaciones == []
    assert len(correr(pullback_alcista(), f_pendiente=True, pendiente_media="lenta", pendiente_velas=2).operaciones) == 1


def test_filtro_de_distancia_entre_rapida_y_lenta():
    # Rápida y lenta están a unos 8,7 puntos; con ATR de 0,7–0,8 son unos 12 ATR.
    assert correr(pullback_alcista(), f_distancia=True, distancia_min_atr=20.0).operaciones == []
    assert len(correr(pullback_alcista(), f_distancia=True, distancia_min_atr=5.0).operaciones) == 1


def test_filtro_de_tendencia_de_un_timeframe_mayor():
    # Desde las 18:00 de la víspera hay 60 velas de 15m: basta para una EMA 50 de ese timeframe.
    sube = rampa(a("18:00", DIA - timedelta(days=1)), 960, -170, 0.5)  # termina en 310 a las 09:59
    assert sube[-1][4] == C0
    assert len(correr(pullback_alcista(sube), f_tf_mayor=True, tf_mayor="15m", periodo_tf_mayor=50).operaciones) == 1
    # Con una EMA de 200 velas de 15m todavía no hay datos: sin tendencia que confirmar, no se entra.
    assert correr(pullback_alcista(sube), f_tf_mayor=True, tf_mayor="15m", periodo_tf_mayor=200).operaciones == []
    # Venía de 600 y cayó a 100 a las 03:00 antes de subir: la tendencia de 1m es la de siempre, pero el precio
    # sigue muy por debajo de la EMA 50 de 15m.
    cae = plano(a("18:00", DIA - timedelta(days=1)), 540, 600.0) + rampa(a("03:00"), 420, 100, 0.5)
    assert len(correr(pullback_alcista(cae)).operaciones) == 1
    assert correr(pullback_alcista(cae), f_tf_mayor=True, tf_mayor="15m", periodo_tf_mayor=50).operaciones == []


def test_en_un_mercado_plano_solo_entra_sin_los_filtros_de_tendencia():
    en_plano = plano(a("03:00"), 420, C0)
    assert correr(pullback_alcista(en_plano)).operaciones == []
    # En plano las velas ya tocan las medias (todas valen 310), así que tampoco hay "primer contacto".
    sin_filtros = correr(pullback_alcista(en_plano), f_apiladas=False, f_precio_lenta=False, primer_pullback=False, lados="solo largos")
    assert [o.lado for o in sin_filtros.operaciones] == [1]


# --- Variantes: pullback ---


def test_contacto_cierra_mas_alla_y_banda():
    # La vela del toque cierra en 304, a 1,28 de la EMA 20 (305,28), con un ATR de 0,844: hace falta una holgura de 1,52 ATR.
    assert len(correr(pullback_alcista(), contacto="cierra mas alla", banda_atr=5.0).operaciones) == 1
    assert correr(pullback_alcista(), contacto="cierra mas alla", banda_atr=0.5).operaciones == []
    # Banda de ±2 ATR en torno a la EMA 20: la entra la vela del toque y no la rampa.
    [op] = correr(pullback_alcista(), contacto="banda", banda_atr=2.0).operaciones
    assert op.sl_inicial == 303.25


def test_solo_el_primer_contacto():
    # Con una banda de ±12 ATR toda la rampa está dentro de ella: ninguna vela es un primer contacto...
    assert correr(pullback_alcista(), contacto="banda", banda_atr=12.0).operaciones == []
    # ...y si se permiten contactos seguidos, entra en cuanto confirma una vela.
    assert len(correr(pullback_alcista(), contacto="banda", banda_atr=12.0, primer_pullback=False).operaciones) >= 1


def test_velas_de_retroceso_seguidas():
    # Antes del toque cierran contra la tendencia 2 velas seguidas.
    assert correr(pullback_alcista(), min_velas_retroceso=3).operaciones == []
    assert len(correr(pullback_alcista(), min_velas_retroceso=2).operaciones) == 1
    assert correr(pullback_alcista(), max_velas_retroceso=1).operaciones == []


def test_la_confirmacion_tiene_plazo():
    # La vela de confirmación llega una vela después del toque; con plazo 0 (solo la misma vela) no hay entrada.
    assert correr(pullback_alcista(), max_velas_confirmacion=0).operaciones == []


def test_confirmacion_sobre_la_media_del_pullback_y_filtros_de_la_vela():
    assert len(correr(pullback_alcista(), confirma_sobre="media objetivo").operaciones) == 1
    # El cuerpo de la vela de confirmación es 4 de un rango de 4,5 (89 %).
    assert len(correr(pullback_alcista(), cuerpo_min_pct=80).operaciones) == 1
    # (Con plazo 1 solo cuenta esa vela: las siguientes de la rampa tienen cuerpo del 100 % y confirmarían.)
    assert correr(pullback_alcista(), cuerpo_min_pct=95, max_velas_confirmacion=1).operaciones == []
    # Su rango de 4,5 son 4 ATR (ATR 1,1): un tope de 3 ATR la descarta y uno de 20 no.
    assert correr(pullback_alcista(), vela_max_atr=3.0, max_velas_confirmacion=1).operaciones == []
    assert len(correr(pullback_alcista(), vela_max_atr=20.0, max_velas_confirmacion=1).operaciones) == 1
    # Con más plazo, una vela posterior de la rampa sí confirma, algo más tarde y más cara.
    [tarde] = correr(pullback_alcista(), cuerpo_min_pct=95).operaciones
    assert tarde.entrada > 308.25


def test_con_medias_simples_el_toque_es_con_la_sma():
    # SMA 20 en la vela del toque: 305,73; el mínimo de 304 la toca.
    [op] = correr(pullback_alcista(), tipo_media="sma").operaciones
    assert (op.lado, op.sl_inicial) == (1, 303.25)


# --- Variantes: stop y objetivo ---
# En la vela de confirmación (la estrategia la ve a las 10:03): ASK 308,25, EMA 50 = 298,72, ATR = 1,106,
# mínimo del pullback 303,75 y máximo previo (swing) 310.


def un_largo(**valores):
    [op] = correr(pullback_alcista(), **valores).operaciones
    return op


def test_stop_tras_la_media_lenta_con_el_mas_cercano_o_el_mas_lejano():
    assert un_largo(stop_pullback=False, stop_lenta=True).sl_inicial == 298.25  # 298,72 − 2 ticks, al tick
    assert un_largo(stop_lenta=True).sl_inicial == 303.25  # los dos activos: vale el más cercano (el del pullback)
    assert un_largo(stop_lenta=True, stop_modo="mas lejano").sl_inicial == 298.25


def test_stop_en_atr_y_en_puntos():
    op = un_largo(stop_pullback=False, stop_atr=True, stop_atr_n=2.0)
    assert (op.sl_inicial, op.tp_final) == (306.0, 312.75)  # 308,25 − 2 × 1,106 = 306,04 → 306; 2 R = 4,5
    op = un_largo(stop_pullback=False, stop_puntos=True, stop_puntos_n=20.0)
    assert (op.sl_inicial, op.tp_final) == (288.25, 348.25)


def test_no_se_opera_si_el_stop_es_demasiado_grande():
    assert un_largo(stop_max_ticks=20).sl_inicial == 303.25  # 5 puntos son 20 ticks justos
    assert correr(pullback_alcista(), stop_max_ticks=19).operaciones == []


def test_objetivos():
    # En ATR: 308,25 + 3 × 1,106 = 311,57 → 311,5. Da 0,65 R: por defecto se descarta (mínimo 1 R).
    assert correr(pullback_alcista(), objetivo="atr", objetivo_atr_n=3.0).operaciones == []
    assert un_largo(objetivo="atr", objetivo_atr_n=3.0, objetivo_min_r=0.0).tp_final == 311.5
    # En el swing anterior: el máximo de las 20 velas previas es 310 (1,75 puntos, 0,35 R).
    assert correr(pullback_alcista(), objetivo="swing").operaciones == []
    assert un_largo(objetivo="swing", objetivo_min_r=0.0).tp_final == 310.0
    # Sin objetivo: sale por el stop, la gestión o el final de los datos.
    op = un_largo(objetivo="ninguno")
    assert (op.tp_final, op.motivo_salida) == (None, "Fin de los datos")


def test_toma_parcial_y_break_even():
    # 2 contratos: uno sale a 1 R (313,25) y otro a 2 R (318,25). Tras la parcial el stop va a la entrada.
    op = un_largo(contratos=2, parcial=True, parcial_r=1.0, parcial_fraccion=0.5)
    assert op.cantidad == 2 and op.sl_final == 308.25
    assert op.pnl_bruto == pytest.approx((5.0 + 10.0) * 20)
    assert op.motivo_salida == "TP"


# --- Variantes: entrada ---


def test_entrada_por_ruptura_del_maximo_de_la_vela_de_confirmacion():
    # Orden de compra stop en 308,5 (máximo 308,25 + 1 tick), que la vela siguiente alcanza.
    op = un_largo(entrada="ruptura")
    assert op.entrada >= 308.5 and op.sl_inicial == 303.25
    assert op.tp_final == pytest.approx(308.5 + 2 * (308.5 - 303.25))


def test_la_orden_de_ruptura_caduca():
    # Tras la confirmación el precio se queda en 306 más de 3 velas: la orden stop se cancela y no entra después.
    final = plano(a("10:03"), 6, 306.0) + rampa(a("10:09"), 60, 306.0, 0.5)
    filas = pullback_alcista()[: -120] + final
    assert correr(filas, entrada="ruptura", max_velas_orden=3).operaciones == []
    # La rampa desde 306 llega a 308,5 once velas después: con una vida de 30 velas la orden sí se ejecuta.
    assert len(correr(filas, entrada="ruptura", max_velas_orden=30).operaciones) == 1


def test_entrada_con_limite_en_la_media():
    # La ventana empieza justo antes: la orden se pone en la vela de las 10:00, a la EMA 20 de entonces (305,25).
    # Sin vela de confirmación ni mínimo del pullback, el stop va a 4 ATR (0,5) de la entrada.
    op = un_largo(entrada="limite", stop_pullback=False, stop_atr=True, stop_atr_n=4.0, ventana_desde="09:59", ventana_hasta="12:00")
    assert (op.lado, op.entrada, op.sl_inicial, op.tp_final) == (1, 305.25, 303.25, 309.25)


# --- Variantes: gestión ---


def con_final(final: list[tuple]) -> list[tuple]:
    return pullback_alcista()[:-120] + final


def sube_y_se_hunde():
    # Tras entrar en 308,25: sube 30 minutos hasta 323 y se hunde 3 puntos por minuto hasta 263.
    subida = rampa(a("10:03"), 30, C0 - 2, 0.5)
    return con_final(subida + rampa(a("10:33"), 20, subida[-1][4], -3.0) + plano(a("10:53"), 60, subida[-1][4] - 60))


def test_break_even_al_llegar_a_n_r():
    # Llega a 313,25 (1 R) y luego se hunde: el stop ya estaba en la entrada y no pierde los 5 puntos del stop.
    op = correr(sube_y_se_hunde(), be_r=1.0, objetivo="ninguno").operaciones[0]
    assert op.sl_final == 308.25
    assert op.pnl_bruto >= -1.0 * 20
    sin_be = correr(sube_y_se_hunde(), objetivo="ninguno").operaciones[0]
    assert sin_be.sl_final == 303.25 and sin_be.pnl_bruto == pytest.approx(-5.0 * 20)


def test_trailing_por_minimos_de_las_ultimas_velas():
    op = correr(sube_y_se_hunde(), objetivo="ninguno", trailing="minimos", trailing_velas=3, trailing_tras_parcial=False).operaciones[0]
    assert op.sl_final > 315  # siguió al precio hacia arriba
    assert op.pnl_bruto > 0


def test_salir_si_cierra_al_otro_lado_de_la_media_lenta():
    # Con el stop muy lejos, la salida llega por el cierre bajo la EMA 50 y no por el stop.
    op = correr(sube_y_se_hunde(), stop_pullback=False, stop_puntos=True, stop_puntos_n=100.0, objetivo="ninguno", salida_cierra_lenta=True).operaciones[0]
    assert op.motivo_salida == "Cierre al otro lado de la media lenta"


def test_salir_si_la_rapida_cruza_la_intermedia_en_contra():
    op = correr(sube_y_se_hunde(), stop_pullback=False, stop_puntos=True, stop_puntos_n=100.0, objetivo="ninguno", salida_cruce=True).operaciones[0]
    assert op.motivo_salida == "Cruce de medias en contra"
