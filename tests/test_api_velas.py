from datetime import datetime

from fastapi.testclient import TestClient

from trading_replay.app import app
from trading_replay.config import INSTRUMENTOS
from trading_replay.historico import almacen

cliente = TestClient(app)


def test_instrumentos_sin_datos(datos):
    respuesta = cliente.get("/api/instrumentos")
    assert respuesta.status_code == 200
    assert {i["simbolo"] for i in respuesta.json()} == {"NQ", "ES", "GC"}
    assert all(i["desde"] is None for i in respuesta.json())


def test_velas_por_defecto_devuelve_la_ultima_ventana(datos):
    datos.serie("NQ", datetime(2024, 3, 12, 9, 30), 60)
    almacen.construir(INSTRUMENTOS["NQ"])

    respuesta = cliente.get("/api/velas", params={"simbolo": "nq", "tf": "15m"})
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["simbolo"] == "NQ"
    assert len(cuerpo["velas"]) == 4
    assert cuerpo["velas"][-1]["close"] == 159.25


def test_velas_con_rango(datos):
    datos.serie("NQ", datetime(2024, 3, 12, 9, 30), 60)
    almacen.construir(INSTRUMENTOS["NQ"])

    respuesta = cliente.get(
        "/api/velas",
        params={"simbolo": "NQ", "tf": "5m", "desde": "2024-03-12T09:40", "hasta": "2024-03-12T09:50"},
    )
    assert len(respuesta.json()["velas"]) == 2


def test_errores_de_validacion(datos):
    assert cliente.get("/api/velas", params={"simbolo": "XX"}).status_code == 404
    assert cliente.get("/api/velas", params={"simbolo": "NQ", "tf": "7m"}).status_code == 422
    assert cliente.get("/api/velas", params={"simbolo": "NQ"}).status_code == 404  # sin datos
