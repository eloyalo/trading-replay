"""Spec 012, RF-1: el timeframe como parámetro elegible y los parámetros agrupados."""

import textwrap
from datetime import datetime, timedelta

import numpy as np
import pytest

from trading_replay.backtest import Estrategia, Parametro, cargador, ejecutor
from trading_replay.backtest.estrategia import a_segundos, timeframe_de

T0 = datetime(2024, 3, 12, 9, 30)


class Cuenta(Estrategia):
    nombre = "Cuenta velas"
    timeframe = "5m"
    parametros = {"timeframe": Parametro("5m", "Timeframe", opciones=["5m", "15m"], grupo="General")}

    def al_empezar(self):
        self.cerradas = 0

    def al_cerrar_vela(self, vela):
        self.cerradas += 1


class Fija(Cuenta):
    parametros = {}


def filas(n):
    return [(T0 + timedelta(minutes=i), 100.0, 100.0, 100.0, 100.0) for i in range(n)]


def correr(clase, valores=None):
    f = filas(60)
    columnas = {
        "t": np.array([a_segundos(x[0]) for x in f], dtype="i8"),
        **{k: np.array([x[i + 1] for x in f], dtype="f8") for i, k in enumerate(("open", "high", "low", "close"))},
        "volume": np.ones(len(f)),
    }
    estrategia = clase(valores)
    ejecutor.Ejecutor(estrategia, "NQ").ejecutar(columnas)
    return estrategia


def test_el_timeframe_elegido_manda_sobre_el_de_la_clase():
    assert correr(Cuenta).cerradas == 12  # 60 minutos en velas de 5m
    assert correr(Cuenta, {"timeframe": "15m"}).cerradas == 4
    assert correr(Cuenta, {"timeframe": "15m"}).velas.duracion == 15 * 60


def test_sin_parametro_timeframe_todo_sigue_igual():
    assert correr(Fija).cerradas == 12
    assert timeframe_de(Fija, {"timeframe": "15m"}) == "5m"
    assert timeframe_de(Cuenta, {"timeframe": "15m"}) == "15m"
    assert timeframe_de(Cuenta, None) == "5m"


def test_un_timeframe_fuera_de_las_opciones_se_rechaza():
    from trading_replay.backtest.estrategia import ParametroNoValido

    with pytest.raises(ParametroNoValido):
        Cuenta({"timeframe": "1h"})


def test_el_cargador_valida_el_parametro_timeframe(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADING_REPLAY_ESTRATEGIAS", str(tmp_path))
    base = textwrap.dedent(
        """
        from trading_replay.backtest import Estrategia, Parametro

        class E(Estrategia):
            nombre = "E"
            parametros = {"timeframe": Parametro("5m", "Timeframe", opciones=%s)}

            def al_cerrar_vela(self, vela):
                pass
        """
    )
    (tmp_path / "buena.py").write_text(base % '["5m", "1h"]')
    (tmp_path / "mala.py").write_text(base % '["5m", "7m"]')
    (tmp_path / "sin_opciones.py").write_text(base % "None")
    assert cargador.buscar("buena").error is None
    assert cargador.buscar("buena").api()["timeframe_elegible"] is True
    assert "7m" in cargador.buscar("mala").error.mensaje or "timeframe" in cargador.buscar("mala").error.mensaje
    assert cargador.buscar("sin_opciones").error is not None


def test_la_api_de_un_parametro_lleva_su_grupo():
    assert Cuenta.parametros["timeframe"].api("timeframe")["grupo"] == "General"
    assert Parametro(1).api("x")["grupo"] == ""
