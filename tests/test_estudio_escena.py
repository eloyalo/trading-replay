"""Escenas del Estudio (spec 010): validación y resolución de datos."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from trading_replay import replay
from trading_replay.app import app
from trading_replay.config import INSTRUMENTOS
from trading_replay.estudio.escena import EscenaNoValida, preparar
from trading_replay.historico import almacen

cliente = TestClient(app)


def seg(texto):
    return int(datetime.fromisoformat(texto).replace(tzinfo=timezone.utc).timestamp())


def manual(pasos=(), **extra):
    return {"formato": 1, "datos": {"tipo": "manual", "velas": [[10, 12, 9, 11], [11, 11.5, 8, 9], [9, 13, 8.5, 12.5]]},
            "pasos": list(pasos), **extra}


def test_velas_manuales_con_tiempos_ficticios_y_aviso():
    e = preparar(manual())
    assert [v["close"] for v in e["velas"]] == [11, 9, 12.5]
    assert e["velas"][1]["time"] - e["velas"][0]["time"] == 86400
    assert e["lienzo"]["ilustrativo"] is True and e["lienzo"]["eje_tiempo"] is False
    assert e["duracion"] == 1.0


def test_tiempos_por_indice_y_puntos_mas_alla_de_la_ultima_vela():
    e = preparar(manual([{"id": "l", "t": 1, "accion": "tendencia", "puntos": [[0, 9], [5, 14]], "duracion": 2}]))
    paso = e["pasos"][0]
    assert paso["puntos"][0][0] == e["velas"][0]["time"]
    assert paso["puntos"][1][0] == e["velas"][2]["time"] + 3 * 86400
    assert e["duracion"] == 4.0


def test_errores_nombran_el_paso():
    with pytest.raises(EscenaNoValida) as error:
        preparar(manual([
            {"id": "a", "t": 0, "accion": "horizontal", "precio": 11},
            {"id": "a", "t": 1, "accion": "horizontal", "precio": 11},
            {"t": 2, "accion": "volar"},
            {"t": 3, "accion": "marca", "punto": [999, 10]},
            {"t": 4, "accion": "horizontal", "precio": -5},
            {"t": 5, "accion": "ocultar", "objetivos": ["z"]},
        ]))
    texto = " | ".join(error.value.errores)
    assert "id repetido 'a'" in texto
    assert "pasos[2]: acción 'volar' no válida" in texto
    assert "pasos[3] marca.punto: índice de vela 999" in texto
    assert "pasos[4] horizontal.precio: precio no válido -5" in texto
    assert "no hay ningún paso con id 'z'" in texto


def test_vela_imposible():
    with pytest.raises(EscenaNoValida, match="vela imposible"):
        preparar({"formato": 1, "datos": {"tipo": "manual", "velas": [[10, 9, 8, 11]]}})


def test_paso_que_termina_despues_de_la_escena():
    with pytest.raises(EscenaNoValida, match="termina después del final"):
        preparar(manual([{"t": 4, "accion": "horizontal", "precio": 10, "duracion": 2}], duracion=5))


def test_pincel_sin_tiempos_reparte_el_trazo():
    e = preparar(manual([{"t": 0, "accion": "pincel", "puntos": [[0, 10], [1, 11], [2, 12]], "duracion": 1}]))
    assert [p[2] for p in e["pasos"][0]["puntos"]] == [0, 0.5, 1]


def test_datos_reales_sin_recorte_del_replay(datos):
    datos.serie("NQ", datetime(2024, 3, 12, 9, 30), 120)
    almacen.construir(INSTRUMENTOS["NQ"])
    replay.iniciar(datetime(2024, 3, 12, 10, 0))  # replay a mitad del rango
    escena = {"formato": 1, "datos": {"tipo": "real", "instrumento": "nq", "tf": "15m",
                                      "desde": "2024-03-12 09:30", "hasta": "2024-03-12 11:30"},
              "pasos": [{"t": 0, "accion": "revelar", "hasta": "2024-03-12 10:45", "duracion": 3}]}
    respuesta = cliente.post("/api/estudio/preparar", json=escena)
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["velas"] == almacen.consultar("NQ", "15m", datetime(2024, 3, 12, 9, 30), datetime(2024, 3, 12, 11, 30))
    assert len(cuerpo["velas"]) == 8
    assert cuerpo["pasos"][0]["hasta"] == seg("2024-03-12 10:45")
    assert replay.actual().instante == datetime(2024, 3, 12, 10, 0)  # el replay sigue igual


def test_api_devuelve_422_con_los_errores():
    respuesta = cliente.post("/api/estudio/preparar", json={"formato": 1, "datos": {"tipo": "otro"}})
    assert respuesta.status_code == 422
    assert "datos.tipo" in respuesta.json()["detail"][0]["msg"]
