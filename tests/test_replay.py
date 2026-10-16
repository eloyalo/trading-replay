import random
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from trading_replay import replay
from trading_replay.app import app
from trading_replay.config import INSTRUMENTOS
from trading_replay.historico import almacen

cliente = TestClient(app)
INICIO = datetime(2024, 3, 12, 9, 30)  # martes


def tiempo(et: datetime) -> int:
    """Hora ET como la recibe el gráfico: segundos Unix como si fuera UTC."""
    return int(et.replace(tzinfo=timezone.utc).timestamp())


def preparar(datos, minutos: int = 120):
    """NQ de 09:30 a 11:29: el minuto i abre en 100 + i y cierra en 100 + i + 0.25."""
    datos.serie("NQ", INICIO, minutos)
    almacen.construir(INSTRUMENTOS["NQ"])


def iniciar(instante: str, simbolo: str = "NQ"):
    respuesta = cliente.post("/api/replay", json={"simbolo": simbolo, "inicio": instante})
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


def avanzar(**cuerpo):
    respuesta = cliente.post("/api/replay/avanzar", json={"simbolo": "NQ", **cuerpo})
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


def test_fin_cubeta():
    momento = datetime(2024, 3, 12, 10, 37)
    assert replay.fin_cubeta(momento, "1m") == datetime(2024, 3, 12, 10, 38)
    assert replay.fin_cubeta(momento, "15m") == datetime(2024, 3, 12, 10, 45)
    assert replay.fin_cubeta(momento, "1h") == datetime(2024, 3, 12, 11, 0)
    assert replay.fin_cubeta(momento, "4h") == datetime(2024, 3, 12, 14, 0)
    assert replay.fin_cubeta(momento, "1D") == datetime(2024, 3, 12, 18, 0)
    assert replay.fin_cubeta(datetime(2024, 3, 12, 19, 0), "1D") == datetime(2024, 3, 13, 18, 0)


def test_con_replay_ninguna_vela_muestra_el_futuro(datos):
    preparar(datos)
    assert iniciar("2024-03-12T10:37") == {"activo": True, "instante": "2024-03-12T10:37:00", "liquidadas": []}

    for tf in almacen.TIMEFRAMES:
        for params in ({}, {"hasta": "2024-03-13T00:00"}):
            velas = cliente.get("/api/velas", params={"simbolo": "NQ", "tf": tf, **params}).json()["velas"]
            # El último minuto visible es el de las 10:36 (i = 66): nada de lo posterior aparece.
            assert velas[-1]["close"] == 166.25, tf
            assert max(v["high"] for v in velas) == 166.5, tf


def test_vela_de_1h_en_formacion(datos):
    preparar(datos)
    iniciar("2024-03-12T10:37")

    ultima = cliente.get("/api/velas", params={"simbolo": "NQ", "tf": "1h"}).json()["velas"][-1]
    # Agregación manual de los minutos de 10:00 (i = 30) a 10:36 (i = 66).
    assert ultima == {
        "time": tiempo(datetime(2024, 3, 12, 10, 0)),
        "open": 130.0,
        "high": 166.5,
        "low": 129.5,
        "close": 166.25,
        "volume": 37.0,
    }


def test_avanzar_minutos(datos):
    preparar(datos)
    iniciar("2024-03-12T10:37")

    cuerpo = avanzar(minutos=3)
    assert cuerpo["instante"] == "2024-03-12T10:40:00"
    assert [v["time"] for v in cuerpo["velas"]] == [tiempo(datetime(2024, 3, 12, 10, m)) for m in (37, 38, 39)]
    assert cuerpo["velas"][0]["open"] == 167.0
    assert cuerpo["fin"] is False

    ultima = cliente.get("/api/velas", params={"simbolo": "NQ", "tf": "1m"}).json()["velas"][-1]
    assert ultima["time"] == tiempo(datetime(2024, 3, 12, 10, 39))


def test_siguiente_vela(datos):
    preparar(datos)
    iniciar("2024-03-12T10:37")

    cuerpo = avanzar(tf="15m")
    assert cuerpo["instante"] == "2024-03-12T10:45:00"
    assert len(cuerpo["velas"]) == 8  # de 10:37 a 10:44

    assert avanzar(tf="1h")["instante"] == "2024-03-12T11:00:00"
    assert avanzar(tf="1m")["instante"] == "2024-03-12T11:01:00"


def test_viernes_por_la_tarde_salta_al_domingo(datos):
    datos.serie("NQ", datetime(2024, 3, 15, 16, 10), 5)  # viernes, hasta las 16:14
    datos.serie("NQ", datetime(2024, 3, 17, 18, 0), 5)  # domingo, desde las 18:00
    almacen.construir(INSTRUMENTOS["NQ"])
    iniciar("2024-03-15T16:14")

    cuerpo = avanzar(tf="1m")
    assert cuerpo["instante"] == "2024-03-15T16:15:00"
    assert [v["time"] for v in cuerpo["velas"]] == [tiempo(datetime(2024, 3, 15, 16, 14))]

    cuerpo = avanzar(tf="1m")
    assert cuerpo["instante"] == "2024-03-17T18:01:00"
    assert [v["time"] for v in cuerpo["velas"]] == [tiempo(datetime(2024, 3, 17, 18, 0))]


def test_avanzar_cruza_huecos_mayores_que_el_bufer(datos):
    datos.serie("NQ", datetime(2024, 3, 12, 10, 0), 1)
    datos.serie("NQ", datetime(2024, 4, 2, 10, 0), 1)  # 3 semanas después
    almacen.construir(INSTRUMENTOS["NQ"])
    iniciar("2024-03-12T10:00")

    cuerpo = avanzar(minutos=2)
    assert cuerpo["instante"] == "2024-04-02T10:01:00"
    assert len(cuerpo["velas"]) == 2
    assert cuerpo["fin"] is True


def test_fin_de_los_datos(datos):
    preparar(datos)
    iniciar("2024-03-12T11:00")

    cuerpo = avanzar(minutos=500)
    assert len(cuerpo["velas"]) == 30
    assert cuerpo["instante"] == "2024-03-12T11:30:00"
    assert cuerpo["fin"] is True
    cuerpo = avanzar(minutos=1)
    assert (cuerpo["instante"], cuerpo["velas"], cuerpo["fin"]) == ("2024-03-12T11:30:00", [], True)


def test_salir_del_replay_devuelve_todo_el_historico(datos):
    preparar(datos)
    iniciar("2024-03-12T10:37")
    avanzar(minutos=1)

    assert cliente.delete("/api/replay").json() == {"activo": False, "instante": None, "liquidadas": []}
    assert cliente.get("/api/replay").json()["activo"] is False
    velas = cliente.get("/api/velas", params={"simbolo": "NQ", "tf": "1m"}).json()["velas"]
    assert len(velas) == 120


def test_cambiar_de_instrumento_mantiene_el_reloj(datos):
    datos.serie("NQ", INICIO, 120)
    datos.serie("ES", INICIO, 120, precio=500.0)
    almacen.construir(INSTRUMENTOS["NQ"])
    almacen.construir(INSTRUMENTOS["ES"])
    iniciar("2024-03-12T10:37")
    avanzar(minutos=3)

    velas = cliente.get("/api/velas", params={"simbolo": "ES", "tf": "1m"}).json()["velas"]
    assert velas[-1]["time"] == tiempo(datetime(2024, 3, 12, 10, 39))
    cuerpo = cliente.post("/api/replay/avanzar", json={"simbolo": "ES", "minutos": 1}).json()
    assert cuerpo["velas"][0]["open"] == 570.0  # ES a las 10:40


def test_momento_aleatorio(datos):
    # 70 días con un minuto en cada sesión: Asia (20:00), Londres (05:00) y Nueva York (10:00).
    horas = {"asia": 20, "londres": 5, "nueva_york": 10}
    primer_dia = datetime(2024, 1, 1)
    minutos = {}
    for d in range(70):
        for sesion, hora in horas.items():
            momento = primer_dia + timedelta(days=d, hours=hora)
            datos("NQ", momento, 100, 101, 99, 100.5)
            minutos[momento] = sesion
    almacen.construir(INSTRUMENTOS["NQ"])
    inicio, fin = min(minutos), max(minutos)

    azar = random.Random(1234)
    for i in range(500):
        sesion = ("cualquiera", "asia", "londres", "nueva_york")[i % 4]
        instante = replay.instante_aleatorio("NQ", sesion, azar)
        assert instante in minutos  # siempre un minuto con datos
        assert sesion == "cualquiera" or minutos[instante] == sesion
        assert inicio + replay.MARGEN_INICIO <= instante < fin - replay.MARGEN_FIN

    respuesta = cliente.post("/api/replay", json={"simbolo": "NQ", "aleatorio": True, "sesion": "londres"})
    instante = datetime.fromisoformat(respuesta.json()["instante"])
    assert minutos[instante] == "londres"


def test_errores_del_replay(datos):
    preparar(datos)
    assert cliente.post("/api/replay/avanzar", json={"simbolo": "NQ", "minutos": 1}).status_code == 409
    assert cliente.post("/api/replay", json={"simbolo": "NQ"}).status_code == 422
    assert cliente.post("/api/replay", json={"simbolo": "NQ", "inicio": "2020-01-01T10:00"}).status_code == 422
    assert cliente.post("/api/replay", json={"simbolo": "XX", "inicio": "2024-03-12T10:00"}).status_code == 404
    # Con poco histórico no hay hueco para el margen del primer mes y la última semana.
    assert cliente.post("/api/replay", json={"simbolo": "NQ", "aleatorio": True}).status_code == 422

    iniciar("2024-03-12T10:00")
    for cuerpo in ({}, {"minutos": 0}, {"minutos": 501}, {"minutos": 1, "tf": "1m"}, {"tf": "7m"}):
        respuesta = cliente.post("/api/replay/avanzar", json={"simbolo": "NQ", **cuerpo})
        assert respuesta.status_code == 422, cuerpo
