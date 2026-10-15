from datetime import UTC, date, datetime, time

import duckdb

from trading_replay.config import INSTRUMENTOS
from trading_replay.historico import almacen, huecos
from trading_replay.historico.dukascopy import decodificar, dias_pendientes, url_dia

from conftest import bi5

NQ = INSTRUMENTOS["NQ"]


def hora(vela: dict) -> datetime:
    """Hora que muestra el gráfico: `time` interpretado como UTC."""
    return datetime.fromtimestamp(vela["time"], UTC).replace(tzinfo=None)


def test_url_usa_meses_desde_cero():
    assert url_dia(NQ, date(2024, 3, 12)).endswith("/USATECHIDXUSD/2024/02/12/BID_candles_min_1.bi5")


def test_decodificar_respeta_el_orden_de_campos():
    registros = decodificar(bi5([(60, 100.0, 102.0, 99.0, 101.0, 0.5)]), date(2024, 3, 12))
    r = registros[0]
    assert (r["seg"], r["open"], r["high"], r["low"], r["close"]) == (60, 100000, 102000, 99000, 101000)


def test_dias_pendientes_salta_sabados_y_lo_ya_descargado(datos):
    datos("NQ", datetime(2022, 10, 17, 10, 0), 1, 1, 1, 1)  # lunes ya descargado
    pendientes = dias_pendientes("NQ", date(2022, 10, 18))
    # 15 (sábado) se salta, 16 domingo, 17 descargado, 18 martes
    assert pendientes == [date(2022, 10, 16), date(2022, 10, 18)]


def test_construir_descarta_minutos_sin_volumen_y_etiqueta_sesiones(datos):
    datos("NQ", datetime(2024, 3, 12, 2, 0), 1, 1, 1, 1)  # asia
    datos("NQ", datetime(2024, 3, 12, 5, 0), 2, 2, 2, 2)  # londres
    datos("NQ", datetime(2024, 3, 12, 10, 0), 3, 3, 3, 3)  # nueva york
    datos("NQ", datetime(2024, 3, 12, 16, 30), 4, 4, 4, 4, v=0)  # cerrado: se descarta
    datos("NQ", datetime(2024, 3, 12, 18, 30), 5, 5, 5, 5)  # asia del día siguiente

    assert almacen.construir(NQ) == 4
    filas = duckdb.sql(f"SELECT close, sesion FROM '{almacen.ruta_parquet('NQ')}' ORDER BY ts").fetchall()
    assert filas == [(1.0, "asia"), (2.0, "londres"), (3.0, "nueva_york"), (5.0, "asia")]


def test_vela_diaria_empieza_a_las_18_et(datos):
    # Domingo 10/03/2024 es el cambio a horario de verano: 18:00 ET ya son las 22:00 UTC.
    datos("NQ", datetime(2024, 3, 10, 18, 0), 100, 101, 99, 100)
    datos("NQ", datetime(2024, 3, 11, 16, 14), 110, 111, 109, 110)
    datos("NQ", datetime(2024, 3, 11, 18, 0), 120, 125, 119, 121)
    datos("NQ", datetime(2024, 3, 12, 12, 0), 130, 131, 118, 129)
    almacen.construir(NQ)

    velas = almacen.consultar("NQ", "1D", datetime(2024, 3, 10), datetime(2024, 3, 13))
    assert [hora(v) for v in velas] == [datetime(2024, 3, 11), datetime(2024, 3, 12)]
    lunes, martes = velas
    assert (lunes["open"], lunes["high"], lunes["low"], lunes["close"]) == (100, 111, 99, 110)
    assert (martes["open"], martes["high"], martes["low"], martes["close"]) == (120, 131, 118, 129)


def test_velas_de_4h_se_alinean_a_las_18_et(datos):
    datos("ES", datetime(2024, 1, 9, 18, 0), 1, 1, 1, 1)
    datos("ES", datetime(2024, 1, 9, 21, 59), 2, 2, 2, 2)
    datos("ES", datetime(2024, 1, 9, 22, 0), 3, 3, 3, 3)
    almacen.construir(INSTRUMENTOS["ES"])

    velas = almacen.consultar("ES", "4h", datetime(2024, 1, 9, 20, 0), datetime(2024, 1, 10))
    horas = [hora(v).hour for v in velas]
    assert horas == [18, 22]  # aunque `desde` sea a las 20:00, se incluye la vela entera de las 18:00
    assert velas[0]["close"] == 2


def test_15m_devuelve_hora_et_como_si_fuera_utc(datos):
    datos.serie("GC", datetime(2024, 7, 2, 9, 30), 30)
    almacen.construir(INSTRUMENTOS["GC"])

    velas = almacen.consultar("GC", "15m", datetime(2024, 7, 2), datetime(2024, 7, 3))
    assert [hora(v).strftime("%H:%M") for v in velas] == ["09:30", "09:45"]
    assert velas[0]["open"] == 100 and velas[0]["close"] == 114.25


def test_mercado_abierto_segun_horario_del_instrumento():
    indices, oro = time(16, 15), time(17, 0)
    martes = date(2024, 3, 12)
    assert huecos.mercado_abierto(datetime.combine(martes, time(16, 14)), indices)
    assert not huecos.mercado_abierto(datetime.combine(martes, time(16, 15)), indices)
    assert huecos.mercado_abierto(datetime.combine(martes, time(16, 15)), oro)
    assert not huecos.mercado_abierto(datetime.combine(martes, time(17, 30)), oro)
    assert not huecos.mercado_abierto(datetime(2024, 3, 16, 12, 0), oro)  # sábado
    assert not huecos.mercado_abierto(datetime(2024, 3, 17, 17, 59), oro)  # domingo antes de abrir
    assert huecos.mercado_abierto(datetime(2024, 3, 17, 18, 0), oro)


def test_huecos_ignora_la_pausa_diaria_y_detecta_los_cortes(datos):
    datos.serie("GC", datetime(2024, 3, 12, 16, 50), 10)  # hasta 16:59
    datos.serie("GC", datetime(2024, 3, 12, 18, 0), 10)  # pausa normal de 17:00 a 18:00
    datos.serie("GC", datetime(2024, 3, 12, 19, 0), 10)  # corte de 18:10 a 19:00
    almacen.construir(INSTRUMENTOS["GC"])

    encontrados = huecos.buscar(INSTRUMENTOS["GC"], umbral_minutos=15)
    assert encontrados == [(datetime(2024, 3, 12, 18, 10), datetime(2024, 3, 12, 19, 0), 50)]
