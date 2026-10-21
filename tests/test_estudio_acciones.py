"""Acciones y ETF de Dukascopy para el Estudio (spec 010, RF-4), con archivos sintéticos y sin red."""

from datetime import date, datetime, timezone

import pytest

from trading_replay.estudio import acciones
from conftest import bi5


@pytest.fixture
def red(monkeypatch, tmp_path):
    """Sustituye la descarga por archivos en memoria y cuenta las peticiones."""
    monkeypatch.setenv("TRADING_REPLAY_DATOS", str(tmp_path))
    archivos: dict[str, bytes] = {}
    pedidas: list[str] = []

    def pedir(url):
        pedidas.append(url)
        return archivos.get(url.split("/datafeed/")[1], b"")

    monkeypatch.setattr(acciones, "_pedir", pedir)
    return archivos, pedidas


def test_diario_filtra_dias_sin_volumen_y_ajusta_splits(red):
    archivos, pedidas = red
    dia = 86400
    inicio_2024 = (date(2024, 6, 6) - date(2024, 1, 1)).days * dia
    archivos["NVDAUSUSD/2024/BID_candles_day_1.bi5"] = bi5([
        (inicio_2024, 1240, 1255, 1183, 1209, 50),          # jueves 6, antes del split
        (inicio_2024 + dia, 1195, 1216, 1180, 1208, 40),    # viernes 7
        (inicio_2024 + 2 * dia, 1208, 1208, 1208, 1208, 0),  # sábado: plano y sin volumen
        (inicio_2024 + 4 * dia, 120.4, 123, 117, 121.6, 7),  # lunes 10, después del split
    ])
    velas = acciones.consultar("NVDA", "1D", datetime(2024, 6, 6), datetime(2024, 6, 11))
    assert [datetime.fromtimestamp(v["time"], timezone.utc).date() for v in velas] == [
        date(2024, 6, 6), date(2024, 6, 7), date(2024, 6, 10)]
    assert velas[0]["open"] == 124.0 and velas[0]["close"] == 120.9   # /10
    assert velas[0]["volume"] == 50                                    # el volumen no se toca
    assert velas[2]["open"] == 120.4
    # Segunda consulta: sale de la caché, sin pedir nada más.
    acciones.consultar("NVDA", "1D", datetime(2024, 6, 6), datetime(2024, 6, 11))
    assert len(pedidas) == 1


def test_intradia_en_hora_et_y_agregado(red):
    archivos, pedidas = red
    # 2024-08-29: la sesión de 9:30 ET es 13:30 UTC (horario de verano).
    seg = 13 * 3600 + 30 * 60
    filas = [(seg - 60, 100, 100, 100, 100, 0)]  # minuto previo plano: fuera
    filas += [(seg + 60 * i, 100 + i, 100.5 + i, 99.5 + i, 100.25 + i, 1) for i in range(30)]
    archivos["SPYUSUSD/2024/07/29/BID_candles_min_1.bi5"] = bi5(filas)
    velas = acciones.consultar("SPY", "15m", datetime(2024, 8, 29, 9, 0), datetime(2024, 8, 29, 16, 0))
    assert [datetime.fromtimestamp(v["time"], timezone.utc).strftime("%H:%M") for v in velas] == ["09:30", "09:45"]
    assert velas[0] == {"time": velas[0]["time"], "open": 100.0, "high": 114.5, "low": 99.5, "close": 114.25,
                        "volume": 15.0}
    assert pedidas == ["https://datafeed.dukascopy.com/datafeed/SPYUSUSD/2024/07/29/BID_candles_min_1.bi5"]


def test_simbolo_no_valido():
    with pytest.raises(acciones.SimboloNoValido):
        acciones.codigo_dukascopy("nvda; rm")


def test_limite_de_dias_intradia(red):
    with pytest.raises(ValueError, match="Demasiados días"):
        acciones.consultar("NVDA", "5m", datetime(2023, 1, 1), datetime(2024, 1, 1))
