"""Widgets del Estudio (spec 011): validación de escenas sin velas."""

import pytest

from trading_replay.estudio.escena import EscenaNoValida, preparar

LIBRO = {"tipo": "libro", "simbolo": "XYZ", "asks": [[50.03, 300], [50.02, 500], [50.01, 200]],
         "bids": [[50.00, 400], [49.99, 600], [49.98, 300]]}


def escena(pasos, widget=LIBRO):
    return {"formato": 1, "widget": widget, "pasos": pasos}


def test_libro_ordenado_y_sin_velas():
    e = preparar(escena([{"t": 1, "accion": "orden", "lado": "compra", "cantidad": 900, "duracion": 3}]))
    assert e["velas"] == [] and e["duracion"] == 5
    assert e["widget"]["asks"][0] == [50.01, 200]  # la mejor ask primero
    assert e["widget"]["bids"][0] == [50.00, 400]
    assert e["lienzo"]["ilustrativo"] is True


def test_orden_mayor_que_el_libro():
    with pytest.raises(EscenaNoValida, match=r"pasos\[1\] orden: pide 700 y en el libro solo hay 400"):
        preparar(escena([{"t": 0, "accion": "orden", "lado": "venta", "cantidad": 900},
                         {"t": 2, "accion": "orden", "lado": "venta", "cantidad": 700}]))


def test_libro_cruzado_y_zona_no_valida():
    cruzado = {**LIBRO, "bids": [[50.05, 100]]}
    with pytest.raises(EscenaNoValida, match="tiene que estar por encima"):
        preparar(escena([], cruzado))
    with pytest.raises(EscenaNoValida, match="zona 'bid' no válida en `libro`"):
        preparar(escena([{"t": 0, "accion": "foco", "zona": "bid"}]))


def test_cotizacion_y_comparacion():
    e = preparar(escena([{"t": 0, "accion": "foco", "zona": "ask"}], {"tipo": "cotizacion", "bid": 50, "ask": 50.01, "last": 50}))
    assert e["widget"]["tipo"] == "cotizacion"
    e = preparar(escena([], {"tipo": "comparar_libros", "izquierda": LIBRO, "derecha": LIBRO}))
    assert e["widget"]["derecha"]["asks"][0][0] == 50.01
