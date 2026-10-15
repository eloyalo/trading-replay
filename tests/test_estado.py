from fastapi.testclient import TestClient

from trading_replay import __version__
from trading_replay.app import app

cliente = TestClient(app)


def test_estado_responde_ok():
    respuesta = cliente.get("/api/estado")
    assert respuesta.status_code == 200
    assert respuesta.json() == {"ok": True, "version": __version__}


def test_sirve_la_pagina_principal():
    respuesta = cliente.get("/")
    assert respuesta.status_code == 200
    assert 'id="grafico"' in respuesta.text


def test_sirve_la_libreria_del_grafico():
    respuesta = cliente.get("/vendor/lightweight-charts.standalone.production.js")
    assert respuesta.status_code == 200
