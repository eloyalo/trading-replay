"""API del backtest (spec 008, T5), con datos sintéticos y estrategias en una carpeta temporal.

Con `datos.serie`, el minuto i (desde las 09:30) abre en 100 + i y cierra en + 0,25: sube un punto por minuto.
"""

import time
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from trading_replay.app import app
from trading_replay.backtest import ejecutor, trabajos
from trading_replay.config import INSTRUMENTOS
from trading_replay.historico import almacen

cliente = TestClient(app)

COMPRA = '''\
"""Compra a la hora indicada con SL y TP en puntos."""

import time

from trading_replay.backtest import Estrategia, Parametro


class Compra(Estrategia):
    nombre = "Compra"
    timeframe = "1m"
    parametros = {
        "hora": Parametro("09:40", "Hora"),
        "tp": Parametro(5.0, "TP en puntos", minimo=1),
        "pausa": Parametro(0.0, "Segundos de espera por vela"),
    }

    def al_cerrar_vela(self, vela):
        time.sleep(self.p.pausa)
        if self.hora == self.p.hora:
            self.comprar(2, sl_puntos=10, tp_puntos=self.p.tp, motivo="a la hora")
            self.nivel(vela.close, "entrada")
'''


@pytest.fixture
def entorno(datos, tmp_path, monkeypatch):
    carpeta = tmp_path / "estrategias"
    carpeta.mkdir()
    monkeypatch.setenv("TRADING_REPLAY_ESTRATEGIAS", str(carpeta))
    (carpeta / "compra.py").write_text(COMPRA)
    datos.serie("NQ", datetime(2024, 3, 12, 9, 30), 120)
    almacen.construir(INSTRUMENTOS["NQ"])
    yield carpeta
    trabajos.cancelar()
    trabajos.esperar(10)
    trabajos._actual = None


def ok(respuesta, codigo=200):
    assert respuesta.status_code == codigo, respuesta.text
    return respuesta.json()


def lanzar(**cuerpo):
    trabajo = ok(cliente.post("/api/backtests", json={"estrategia": "compra", "simbolo": "NQ", **cuerpo}))
    trabajos.esperar(30)
    return trabajo


def test_lanzar_y_ver_el_resultado(entorno):
    [info] = ok(cliente.get("/api/estrategias"))
    assert (info["id"], info["timeframe"], [p["clave"] for p in info["parametros"]]) == ("compra", "1m", ["hora", "tp", "pausa"])
    assert ok(cliente.get("/api/estrategias/compra/codigo"))["codigo"] == COMPRA

    lanzar()
    estado = ok(cliente.get("/api/backtests/en-marcha"))
    assert (estado["estado"], estado["progreso"]) == ("hecho", 1.0), estado
    id_ejecucion = estado["ejecucion"]

    cuerpo = ok(cliente.get(f"/api/backtests/{id_ejecucion}"))
    [op] = cuerpo["operaciones"]
    # Como a mano (test_operativa): 2 NQ a 109,50, TP a 114,50; 190 $ netos.
    assert (op["lado"], op["entrada"], op["salida"], op["motivo_salida"], op["pnl_neto"]) == ("largo", 109.5, 114.5, "TP", 190.0)
    assert (op["motivo_entrada"], op["r"]) == ("a la hora", 0.475)  # 190 / (10 puntos × 2 × 20 $)
    assert (cuerpo["resumen"]["operaciones"], cuerpo["resumen"]["acierto"], cuerpo["total"]) == (1, 1.0, 1)
    assert cuerpo["curva"] == [{"time": op["t_cierre"], "value": 190.0}]
    assert cuerpo["ejecucion"]["codigo_cambiado"] is False
    assert cuerpo["ejecucion"]["parametros"] == {"hora": "09:40", "tp": 5.0, "pausa": 0.0}

    tramo = ok(cliente.get(f"/api/backtests/{id_ejecucion}/tramo", params={"desde": "2024-03-12T09:00", "hasta": "2024-03-12T12:00"}))
    assert [o["numero"] for o in tramo["operaciones"]] == [1]
    assert [(m["tipo"], m["texto"]) for m in tramo["marcas"]] == [("nivel", "entrada")]
    vacio = ok(cliente.get(f"/api/backtests/{id_ejecucion}/tramo", params={"desde": "2024-03-13T09:00", "hasta": "2024-03-13T12:00"}))
    assert vacio == {"operaciones": [], "marcas": []}


def test_filtros_por_la_api(entorno):
    lanzar()
    id_ejecucion = trabajos.actual().ejecucion
    nueva_york = ok(cliente.get(f"/api/backtests/{id_ejecucion}", params={"sesiones": "nueva_york", "anios": "2024"}))
    assert nueva_york["total"] == 1
    for filtro in ({"sesiones": "asia"}, {"lado": "cortos"}, {"anios": "2023"}, {"dias": "lunes"}):
        cuerpo = ok(cliente.get(f"/api/backtests/{id_ejecucion}", params=filtro))
        assert (cuerpo["total"], cuerpo["resumen"]["operaciones"], cuerpo["curva"]) == (0, 0, []), filtro
    ok(cliente.get(f"/api/backtests/{id_ejecucion}", params={"sesiones": "marte"}), 422)


def test_historial_codigo_cambiado_y_borrar(entorno):
    lanzar()
    lanzar(parametros={"tp": 8})
    primera, segunda = sorted(ok(cliente.get("/api/backtests")), key=lambda e: e["id"])
    assert (primera["resumen"]["neto"], segunda["resumen"]["neto"]) == (190.0, 8 * 2 * 20 - 10)
    assert not primera["codigo_cambiado"] and not segunda["codigo_cambiado"]

    # Se duplica, se toca la copia y se relanza: el historial sabe qué código dio cada resultado (RF-18).
    copia = ok(cliente.post("/api/estrategias/compra/duplicar"))
    assert (copia["id"], copia["nombre"]) == ("compra_2", "Compra (copia 2)")
    (entorno / "compra.py").write_text(COMPRA.replace('"09:40"', '"09:50"'))
    lanzar()
    historial = {e["id"]: e for e in ok(cliente.get("/api/backtests"))}
    assert historial[primera["id"]]["codigo_cambiado"] is True
    tercera = max(historial.values(), key=lambda e: e["id"])
    assert tercera["codigo_cambiado"] is False
    assert ok(cliente.get(f"/api/backtests/{primera['id']}/codigo"))["codigo"] == COMPRA

    ok(cliente.delete(f"/api/backtests/{primera['id']}"))
    ok(cliente.get(f"/api/backtests/{primera['id']}"), 404)
    ok(cliente.delete(f"/api/backtests/{primera['id']}"), 404)
    assert len(ok(cliente.get("/api/backtests"))) == 2


def test_errores_al_lanzar(entorno):
    ok(cliente.post("/api/backtests", json={"estrategia": "no_existe", "simbolo": "NQ"}), 404)
    ok(cliente.post("/api/backtests", json={"estrategia": "compra", "simbolo": "NQ", "parametros": {"tp": 0}}), 422)
    ok(cliente.post("/api/backtests", json={"estrategia": "compra", "simbolo": "NQ", "desde": "2024-03-13", "hasta": "2024-03-12"}), 422)
    (entorno / "rota.py").write_text("esto no es python")
    ok(cliente.post("/api/backtests", json={"estrategia": "rota", "simbolo": "NQ"}), 422)

    # Un error al ejecutar acaba en el trabajo, con su línea y su vela, y no se guarda nada.
    (entorno / "compra.py").write_text(COMPRA.replace("self.nivel(vela.close", "self.nivel(1 / 0"))
    lanzar()
    estado = ok(cliente.get("/api/backtests/en-marcha"))
    assert estado["estado"] == "error"
    assert (estado["error"]["archivo"], estado["error"]["linea"], estado["error"]["vela"]) == ("compra.py", 21, "2024-03-12 09:39")
    assert ok(cliente.get("/api/backtests")) == []


def test_backtest_y_replay_no_van_a_la_vez(entorno, monkeypatch):
    ok(cliente.post("/api/replay", json={"simbolo": "NQ", "inicio": "2024-03-12T10:00"}))
    ok(cliente.post("/api/backtests", json={"estrategia": "compra", "simbolo": "NQ"}), 409)
    ok(cliente.delete("/api/replay"))

    monkeypatch.setattr(ejecutor, "CADA_VELAS", 1)
    ok(cliente.post("/api/backtests", json={"estrategia": "compra", "simbolo": "NQ", "parametros": {"pausa": 0.05}}))
    ok(cliente.post("/api/replay", json={"simbolo": "NQ", "inicio": "2024-03-12T10:00"}), 409)
    ok(cliente.post("/api/backtests", json={"estrategia": "compra", "simbolo": "NQ"}), 409)
    time.sleep(0.2)
    assert 0 < ok(cliente.get("/api/backtests/en-marcha"))["progreso"] < 1
    ok(cliente.post("/api/backtests/en-marcha/cancelar"))
    trabajos.esperar(10)
    assert ok(cliente.get("/api/backtests/en-marcha"))["estado"] == "cancelado"
    assert ok(cliente.get("/api/backtests")) == []  # lo cancelado no se guarda
    ok(cliente.post("/api/replay", json={"simbolo": "NQ", "inicio": "2024-03-12T10:00"}))


def test_con_reto(entorno):
    ok(cliente.post("/api/backtests", json={"estrategia": "compra", "simbolo": "NQ", "perfil": "no-existe"}), 422)
    lanzar(perfil="topstep-50k")
    estado = ok(cliente.get("/api/backtests/en-marcha"))
    assert estado["estado"] == "hecho", estado
    cuerpo = ok(cliente.get(f"/api/backtests/{estado['ejecucion']}"))
    reto = cuerpo["reto"]
    assert (reto["perfil"], reto["titulo"]) == ("topstep-50k", "Topstep Trading Combine 50K")
    # Una sola operación (+190 $) en un día: el intento sigue en curso al acabar los datos.
    assert [(i["numero"], i["resultado"], i["dias"], i["beneficio"]) for i in reto["intentos"]] == [(1, "en_curso", 1, 190.0)]
    assert (reto["resumen"]["intentos"], reto["resumen"]["en_curso"], reto["resumen"]["aprobacion"]) == (1, 1, None)
    assert cuerpo["operaciones"][0]["intento"] == 1
    [ejecucion] = ok(cliente.get("/api/backtests"))
    assert ejecucion["perfil"] == "topstep-50k" and ejecucion["reto"]["intentos"] == 1


def test_abre_una_base_de_datos_de_la_spec_008(datos, tmp_path):
    import sqlite3

    from trading_replay.backtest import almacen_bt

    ruta = almacen_bt.ruta()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    vieja = sqlite3.connect(ruta)
    vieja.executescript(
        """
        CREATE TABLE ejecuciones (id INTEGER PRIMARY KEY AUTOINCREMENT, estrategia TEXT NOT NULL, nombre TEXT NOT NULL,
            huella TEXT NOT NULL, codigo TEXT NOT NULL, parametros TEXT NOT NULL, simbolo TEXT NOT NULL,
            timeframe TEXT NOT NULL, desde TEXT NOT NULL, hasta TEXT NOT NULL, costes TEXT NOT NULL, creada TEXT NOT NULL,
            segundos REAL NOT NULL, resumen TEXT NOT NULL);
        CREATE TABLE operaciones (ejecucion INTEGER NOT NULL, numero INTEGER NOT NULL, contrato TEXT NOT NULL,
            lado INTEGER NOT NULL, cantidad INTEGER NOT NULL, apertura TEXT NOT NULL, cierre TEXT NOT NULL,
            entrada REAL NOT NULL, salida REAL NOT NULL, sl_inicial REAL, sl_final REAL, tp_final REAL,
            motivo_entrada TEXT, motivo_salida TEXT NOT NULL, pnl_bruto REAL NOT NULL, comisiones REAL NOT NULL,
            riesgo REAL, dudosa INTEGER NOT NULL, minuto_entrada TEXT, minuto_salida TEXT, PRIMARY KEY (ejecucion, numero));
        INSERT INTO ejecuciones VALUES (1, 'x', 'X', 'h', '', '{}', 'NQ', '5m', '2024-01-01T18:00:00', '2024-02-01T18:00:00',
            '{}', '2026-10-17T10:00:00+00:00', 1.0, '{"operaciones": 0}');
        """
    )
    vieja.close()
    almacen_bt._conexion = None
    [meta] = almacen_bt.listar()
    assert (meta["id"], meta["perfil"], meta["reto"]) == (1, None, None)
    assert almacen_bt.operaciones(1) == [] and almacen_bt.intentos(1) == []


FIBO = '''\
"""Compra y dibuja un Fibonacci."""

from datetime import datetime

from trading_replay.backtest import Estrategia


class Fibo(Estrategia):
    nombre = "Fibo"
    timeframe = "1m"

    def al_cerrar_vela(self, vela):
        if self.hora == "09:40":
            self.marca = self.fibonacci((datetime(2024, 3, 12, 9, 31), 100.0), (datetime(2024, 3, 12, 9, 38), 108.0), retrocesos=(0.5, 0.618), extensiones=(1.618,), texto="Impulso")
            self.comprar(1, sl_puntos=10, tp_puntos=5)
        if self.hora == "09:50":
            self.marca.fin = self.instante
'''


def test_la_marca_de_fibonacci_se_guarda_y_se_sirve_con_el_reloj_del_grafico(entorno):
    (entorno / "fibo.py").write_text(FIBO)
    ok(cliente.post("/api/backtests", json={"estrategia": "fibo", "simbolo": "NQ"}))
    trabajos.esperar(30)
    id_ejecucion = ok(cliente.get("/api/backtests/en-marcha"))["ejecucion"]
    tramo = ok(cliente.get(f"/api/backtests/{id_ejecucion}/tramo", params={"desde": "2024-03-12T09:45", "hasta": "2024-03-12T12:00"}))
    [fibo] = [m for m in tramo["marcas"] if m["tipo"] == "fibonacci"]  # empieza a las 9:31 pero dura hasta las 9:50
    assert fibo["texto"] == "Impulso" and fibo["datos"]["retrocesos"] == [0.5, 0.618] and fibo["datos"]["extensiones"] == [1.618]
    assert (fibo["datos"]["origen"]["precio"], fibo["datos"]["final"]["precio"]) == (100.0, 108.0)
    # Los instantes salen como en las demás marcas: la hora ET como si fuera UTC.
    assert fibo["datos"]["origen"]["t"] == int(datetime(2024, 3, 12, 9, 31, tzinfo=timezone.utc).timestamp())
    assert fibo["t"] == fibo["datos"]["origen"]["t"] and fibo["t_fin"] > fibo["datos"]["final"]["t"]
    # Las marcas que no son de Fibonacci no llevan datos.
    assert all(m["datos"] is None for m in tramo["marcas"] if m["tipo"] != "fibonacci")


def test_una_base_de_datos_sin_la_columna_datos_de_las_marcas_se_migra(datos):
    import sqlite3

    from trading_replay.backtest import almacen_bt

    ruta = almacen_bt.ruta()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    vieja = sqlite3.connect(ruta)
    vieja.executescript(
        """
        CREATE TABLE marcas (ejecucion INTEGER NOT NULL, tipo TEXT NOT NULL, instante TEXT NOT NULL, fin TEXT,
            precio REAL, precio2 REAL, texto TEXT);
        """
    )
    vieja.close()
    almacen_bt._conexion = None
    almacen_bt.listar()
    columnas = {f[1] for f in almacen_bt._con().execute("PRAGMA table_info(marcas)")}
    assert "datos" in columnas
