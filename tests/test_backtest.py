"""Backtest (spec 008): estrategias, cargador y ejecutor. Los precios esperados están calculados a mano.

Recordatorio de la ejecución (spec 005): el BID es el precio de los datos redondeado al tick y el ASK,
el BID más 1 tick de spread. Comisión de 2,50 $ por contrato y lado en NQ ($20 por punto).
"""

import textwrap
from datetime import datetime, timedelta

import numpy as np
import pytest
from fastapi.testclient import TestClient

from trading_replay.app import app
from trading_replay.backtest import Estrategia, Parametro, cargador, ejecutor
from trading_replay.backtest.estrategia import ParametroNoValido, a_segundos
from trading_replay.config import INSTRUMENTOS
from trading_replay.historico import almacen

UN_MINUTO = timedelta(minutes=1)
T0 = datetime(2024, 3, 12, 9, 30)  # martes


def columnas(filas: list[tuple]) -> dict[str, np.ndarray]:
    """Minutos de 1m a partir de (hora ET, open, high, low, close)."""
    return {
        "t": np.array([a_segundos(f[0]) for f in filas], dtype="i8"),
        **{k: np.array([f[i + 1] for f in filas], dtype="f8") for i, k in enumerate(("open", "high", "low", "close"))},
        "volume": np.ones(len(filas)),
    }


def planos(n: int, precio: float = 100.0, inicio: datetime = T0) -> list[tuple]:
    return [(inicio + i * UN_MINUTO, precio, precio, precio, precio) for i in range(n)]


def correr(clase, filas, valores=None, simbolo="NQ"):
    return ejecutor.Ejecutor(clase(valores), simbolo).ejecutar(columnas(filas))


class AlCerrar(Estrategia):
    """Hace `accion(self, vela)` al cerrar la vela de las `hora`."""

    nombre = "Prueba"
    timeframe = "1m"
    hora_accion = "09:31"

    def accion(self, vela):
        pass

    def al_cerrar_vela(self, vela):
        if self.hora == self.hora_accion:
            self.accion(vela)


def estrategia(hora="09:31", **metodos):
    return type("Prueba", (AlCerrar,), {"hora_accion": hora, **metodos})


# --- Ejecución ---


def test_sl_y_tp_en_el_mismo_minuto_cuenta_el_sl_y_se_marca_como_dudosa():
    filas = planos(1) + [(T0 + UN_MINUTO, 100, 103, 97, 100)] + planos(2, inicio=T0 + 2 * UN_MINUTO)
    clase = estrategia(accion=lambda self, v: self.comprar(1, sl_puntos=2, tp_puntos=2))
    [op] = correr(clase, filas).operaciones
    # Entrada al ASK 100,25 al cierre de las 09:30; SL 98,25 y TP 102,25, los dos dentro del minuto 09:31.
    assert (op.entrada, op.salida, op.motivo_salida, op.dudosa) == (100.25, 98.25, "SL", True)
    # La entrada a mercado sale con el precio del minuto de las 09:30; el SL, dentro del de las 09:31.
    assert (op.apertura, op.minuto_entrada, op.cierre, op.minuto_salida) == (T0 + UN_MINUTO, T0, T0 + UN_MINUTO, T0 + UN_MINUTO)
    assert op.pnl_neto == -2 * 20 - 5
    assert (op.riesgo, op.r) == (40.0, -45 / 40)


def test_sl_en_precio_y_tp_en_r():
    filas = planos(1) + [(T0 + UN_MINUTO, 100, 102.5, 100, 102)] + planos(2, 102, T0 + 2 * UN_MINUTO)
    clase = estrategia(accion=lambda self, v: self.comprar(1, sl=99.25, tp_r=2, motivo="prueba"))
    [op] = correr(clase, filas).operaciones
    # Entrada 100,25; riesgo 1 punto → TP a 2 R = 102,25, que toca el máximo 102,5 del minuto 09:31.
    assert (op.sl_inicial, op.sl_final, op.tp_final) == (99.25, 99.25, 102.25)
    assert (op.salida, op.motivo_salida, op.motivo_entrada, op.dudosa) == (102.25, "TP", "prueba", False)
    assert op.riesgo == 20.0 and op.r == pytest.approx((40 - 5) / 20)


def test_sl_rebasado_al_entrar_cierra_en_el_acto():
    clase = estrategia(accion=lambda self, v: self.comprar(1, sl=101))
    [op] = correr(clase, planos(4)).operaciones
    assert (op.entrada, op.salida, op.motivo_salida) == (100.25, 100.0, "SL rebasado al entrar")
    assert op.apertura == op.cierre == T0 + UN_MINUTO
    assert op.minuto_entrada == op.minuto_salida == T0
    assert op.pnl_neto == -5 - 5


def test_cierre_de_la_estrategia_con_motivo_y_fin_de_los_datos():
    class CierraALas0933(AlCerrar):
        def al_cerrar_vela(self, vela):
            if self.hora == "09:31":
                self.vender(2, motivo="corto")
            if self.hora == "09:33":
                self.cerrar("me salgo")
            if self.hora == "09:34":
                self.comprar(1)

    primera, segunda = correr(CierraALas0933, planos(1) + planos(5, 90, T0 + UN_MINUTO)).operaciones
    # Vende 2 al BID 100 a las 09:31; cierra a las 09:33 al ASK 90,25.
    assert (primera.lado, primera.cantidad, primera.entrada, primera.salida) == (-1, 2, 100.0, 90.25)
    assert (primera.motivo_entrada, primera.motivo_salida) == ("corto", "me salgo")
    assert primera.pnl_neto == 9.75 * 2 * 20 - 10
    assert segunda.motivo_salida == ejecutor.FIN_DATOS and segunda.cierre == T0 + 6 * UN_MINUTO


def test_una_limite_enviada_al_cerrar_no_se_ejecuta_con_precios_de_esa_vela():
    # La vela de las 09:30 baja hasta 98; desde las 09:31 el precio no baja de 100.
    filas = [(T0, 100, 100, 98, 100)] + planos(5, inicio=T0 + UN_MINUTO)
    clase = estrategia(accion=lambda self, v: self.comprar(1, tipo="limite", precio=98.5))
    assert correr(clase, filas).operaciones == []


def test_no_puede_leer_la_vela_siguiente(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADING_REPLAY_ESTRATEGIAS", str(tmp_path))
    (tmp_path / "mirona.py").write_text(
        textwrap.dedent(
            """\
            from trading_replay.backtest import Estrategia

            class Mirona(Estrategia):
                nombre = "Mirona"
                timeframe = "1m"

                def al_cerrar_vela(self, vela):
                    assert self.velas[-1] == vela
                    siguiente = self.velas[len(self.velas)]
            """
        )
    )
    info = cargador.buscar("mirona")
    assert info.error is None
    with pytest.raises(cargador.ErrorEstrategia) as error:
        correr(info.clase, planos(3))
    assert (error.value.archivo, error.value.linea, error.value.vela) == ("mirona.py", 9, "2024-03-12 09:30")
    assert error.value.mensaje.startswith("IndexError")


def test_velas_iguales_que_las_del_grafico_en_todos_los_timeframes(datos):
    # Viernes y lunes, con el cambio de hora del domingo 10 de marzo de 2024, la pausa diaria y un hueco.
    datos.serie("NQ", datetime(2024, 3, 8, 13, 7), 200, 100)
    datos.serie("NQ", datetime(2024, 3, 10, 18, 0), 700, 300)
    datos.serie("NQ", datetime(2024, 3, 11, 9, 13), 400, 500)
    almacen.construir(INSTRUMENTOS["NQ"])
    desde, hasta = datetime(2024, 3, 8), datetime(2024, 3, 12)
    cols = almacen.columnas_1m("NQ", desde, hasta)
    for tf in ("1m", "5m", "15m", "30m", "1h", "4h"):
        velas = ejecutor.armar_velas(cols, tf)
        armadas = [
            {"time": int(t), "open": o, "high": h, "low": l, "close": c, "volume": round(v, 4)}
            for t, o, h, l, c, v in zip(*(velas[k] for k in ("t", "open", "high", "low", "close", "volume")))
        ]
        assert armadas == almacen.consultar("NQ", tf, desde, hasta), tf


def test_avisos_tiempo_e_indicadores():
    vistas = []

    class Mira(Estrategia):
        nombre = "Mira"
        timeframe = "5m"

        def al_empezar_dia(self):
            vistas.append("día")

        def al_cerrar_vela(self, vela):
            vistas.append((self.hora, self.fecha.isoformat(), self.dia_semana, self.sesion, vela.close, self.sma(2)))

    domingo = datetime(2024, 3, 10, 18, 0)
    filas = [(domingo + i * UN_MINUTO, 100 + i, 100 + i, 100 + i, 100 + i) for i in range(10)]
    correr(Mira, filas)
    # Las velas del domingo a partir de las 18:00 son del lunes, en la sesión de Asia.
    assert vistas == ["día", ("18:05", "2024-03-11", "lunes", "asia", 104, None), ("18:10", "2024-03-11", "lunes", "asia", 109, 106.5)]


def test_entre_y_hora_mas():
    e = AlCerrar()
    e._fin = a_segundos(datetime(2024, 3, 12, 9, 45))
    assert e.entre("09:30", "09:45") and not e.entre("09:45", "10:00") and e.entre("18:00", "10:00")
    assert e.hora_mas("09:30", 15) == "09:45" and e.hora_mas("23:50", 20) == "00:10"


def test_parametros():
    class ConParametros(AlCerrar):
        parametros = {"n": Parametro(3, "N", minimo=1, maximo=5), "r": Parametro(1.5, "R"), "lado": Parametro("ambos", "Lado", opciones=["ambos", "largos"])}

    e = ConParametros({"n": "4", "r": 2})
    assert (e.p.n, e.p.r, e.p.lado) == (4, 2.0, "ambos")
    for malos in ({"n": 6}, {"n": 2.5}, {"lado": "cortos"}, {"otro": 1}):
        with pytest.raises(ParametroNoValido):
            ConParametros(malos)


# --- Igual que a mano (criterio de aceptación) ---

cliente = TestClient(app)


def test_el_mismo_trade_da_lo_mismo_que_operado_a_mano(datos):
    datos.serie("NQ", T0, 120)
    almacen.construir(INSTRUMENTOS["NQ"])

    # A mano, en el replay: a las 09:40 compra 2 con SL 10 y TP 5 (como en test_operativa).
    assert cliente.post("/api/replay", json={"simbolo": "NQ", "inicio": "2024-03-12T09:40"}).status_code == 200
    assert cliente.post("/api/ordenes", json={"contrato": "NQ", "lado": "compra", "cantidad": 2, "sl_puntos": 10, "tp_puntos": 5}).status_code == 200
    cliente.post("/api/replay/avanzar", json={"simbolo": "NQ", "minutos": 10})
    [manual] = cliente.get("/api/operaciones").json()
    cliente.delete("/api/replay")

    variantes = [
        lambda self, v: self.comprar(2, sl_puntos=10, tp_puntos=5),
        lambda self, v: self.comprar(2, sl=99.5, tp=114.5),
        lambda self, v: self.comprar(2, sl=99.5, tp_r=0.5),
    ]
    for accion in variantes:
        clase = estrategia("09:40", accion=accion)
        [op] = ejecutor.ejecutar(clase, None, "NQ", T0, T0 + timedelta(hours=2)).operaciones
        assert (op.entrada, op.salida, op.pnl_neto) == (manual["entrada"], manual["salida"], manual["pnl_neto"]) == (109.5, 114.5, 190.0)


# --- Cargador ---


@pytest.fixture
def carpeta(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADING_REPLAY_ESTRATEGIAS", str(tmp_path))
    return tmp_path


BUENA = '''\
"""Compra a las 09:31."""

from trading_replay.backtest import Estrategia, Parametro


class Buena(Estrategia):
    nombre = "Buena"
    timeframe = "1m"
    parametros = {"contratos": Parametro(1, "Contratos", minimo=1)}

    def al_cerrar_vela(self, vela):
        if self.hora == "09:31":
            self.comprar(self.p.contratos)
'''


def test_cargador_lista_describe_y_recarga(carpeta):
    (carpeta / "buena.py").write_text(BUENA)
    (carpeta / "_ayudas.py").write_text("x = 1")
    [info] = cargador.listar()
    api = info.api()
    assert (api["id"], api["nombre"], api["descripcion"], api["timeframe"], api["error"]) == ("buena", "Buena", "Compra a las 09:31.", "1m", None)
    assert api["parametros"][0]["clave"] == "contratos"
    huella = info.huella

    (carpeta / "buena.py").write_text(BUENA.replace('"Buena"', '"Buena 2"'))
    info = cargador.buscar("buena")
    assert info.nombre == "Buena 2" and info.huella != huella
    [op] = correr(info.clase, planos(4), {"contratos": 3}).operaciones
    assert op.cantidad == 3


def test_errores_de_carga_con_su_linea(carpeta):
    (carpeta / "sintaxis.py").write_text("from trading_replay.backtest import Estrategia\n\nclass X(Estrategia)\n    pass\n")
    (carpeta / "importa.py").write_text("import no_existe\n")
    (carpeta / "sin_clase.py").write_text("x = 1\n")
    (carpeta / "mal_tf.py").write_text(BUENA.replace('"1m"', '"2m"'))
    errores = {i.id: i.error for i in cargador.listar()}
    assert (errores["sintaxis"].archivo, errores["sintaxis"].linea) == ("sintaxis.py", 3)
    assert (errores["importa"].archivo, errores["importa"].linea) == ("importa.py", 1)
    assert "ModuleNotFoundError" in errores["importa"].mensaje
    assert "Estrategia" in errores["sin_clase"].mensaje
    assert "Timeframe" in errores["mal_tf"].mensaje


def test_error_al_ejecutar_con_su_linea_y_su_vela(carpeta):
    (carpeta / "rompe.py").write_text(BUENA.replace("self.comprar(self.p.contratos)", "1 / 0"))
    info = cargador.buscar("rompe")
    with pytest.raises(cargador.ErrorEstrategia) as error:
        correr(info.clase, planos(4))
    assert (error.value.archivo, error.value.linea, error.value.vela) == ("rompe.py", 13, "2024-03-12 09:30")
    assert "ZeroDivisionError" in error.value.mensaje


def test_duplicar(carpeta):
    (carpeta / "buena.py").write_text(BUENA)
    copia = cargador.duplicar("buena")
    assert (copia.id, copia.nombre) == ("buena_2", "Buena (copia 2)")
    assert cargador.duplicar("buena_2").id == "buena_3"
    assert {i.id for i in cargador.listar()} == {"buena", "buena_2", "buena_3"}


# --- Otros timeframes, toma parcial e instrumento (añadidos para la Danny strategy) ---


def test_velas_de_un_timeframe_mayor_iguales_y_nunca_a_medias():
    # De 09:30 a 11:59, con un hueco de 10:07 a 10:22 (la vela de 10:15 de 15m no tiene su último minuto).
    filas = [f for f in planos(150) if not (37 <= (f[0] - T0) // UN_MINUTO < 53)]
    filas = [(t, 100 + i, 101 + i, 99 + i, 100.5 + i) for i, (t, *_) in enumerate(filas)]
    vistas = {}

    class Mayor(Estrategia):
        nombre = "Mayor"
        timeframe = "5m"

        def al_cerrar_vela(self, vela):
            vistas[self.hora] = len(self.velas_de("15m"))
            if self.hora == "10:00":
                assert self.velas_de("15m") is self.velas_de("15m")
                self.velas_de("1h")  # se pide tarde: se pone al día con lo que ya había cerrado

    e = Mayor()
    ejecutor.Ejecutor(e, "NQ").ejecutar(columnas(filas))
    # La vela de 15m de las 09:30 se ve al cerrar la de 5m de las 09:40, no antes.
    assert (vistas["09:40"], vistas["09:45"]) == (0, 1)
    esperadas = ejecutor.armar_velas(columnas(filas), "15m")
    v = e.velas_de("15m")
    # Los datos acaban a las 11:59: la última vela de 15m (11:45) y la de 1h (11:00) también han cerrado.
    assert list(v.time) == list(esperadas["t"])
    assert list(v.open) == list(esperadas["open"]) and list(v.high) == list(esperadas["high"])
    assert list(v.low) == list(esperadas["low"]) and list(v.close) == list(esperadas["close"])
    assert list(e.velas_de("1h").time) == list(ejecutor.armar_velas(columnas(filas), "1h")["t"])
    with pytest.raises(ValueError):
        e.velas_de("1m")


def test_toma_parcial_y_break_even():
    class Parcial(AlCerrar):
        def al_cerrar_vela(self, vela):
            if self.hora == "09:31":
                self.comprar(2, sl_puntos=2, tp_puntos=4)
                self.tomar_parcial(1, self.precio_entrada + 1)
            if self.hora == "09:33" and self.posicion == 1:
                self.mover_sl(self.precio_entrada)

    # 09:31 sube hasta 101,5 (toma la mitad a 101,25); 09:33 abre en 100,5 y baja: salta el SL en break-even.
    filas = (
        planos(1)
        + [(T0 + UN_MINUTO, 100, 101.5, 100, 101)]
        + planos(1, 101, T0 + 2 * UN_MINUTO)
        + [(T0 + 3 * UN_MINUTO, 100.5, 100.5, 99, 99)]
        + planos(2, 99, T0 + 4 * UN_MINUTO)
    )
    [op] = correr(Parcial, filas).operaciones
    assert (op.cantidad, op.entrada, op.motivo_salida) == (2, 100.25, "SL")
    assert op.salida == (101.25 + 100.25) / 2
    assert op.pnl_bruto == 1 * 20 and op.comisiones == 10


def test_toma_parcial_se_cancela_si_la_posicion_se_cierra_antes():
    class Parcial(AlCerrar):
        def al_cerrar_vela(self, vela):
            if self.hora == "09:31":
                self.comprar(2, sl_puntos=1)
                self.tomar_parcial(1, self.precio_entrada + 1)

    # Salta el SL a las 09:31 y después el precio pasa por el nivel de la toma parcial: no abre un corto.
    filas = planos(1) + [(T0 + UN_MINUTO, 100, 100, 98, 98)] + planos(3, 102, T0 + 2 * UN_MINUTO)
    [op] = correr(Parcial, filas).operaciones
    assert (op.cantidad, op.motivo_salida) == (2, "SL")


def test_simbolo_y_tick():
    vistos = []
    clase = estrategia(accion=lambda self, v: vistos.append((self.simbolo, self.tick)))
    correr(clase, planos(3), simbolo="GC")
    assert vistos == [("GC", 0.1)]
