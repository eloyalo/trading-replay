"""API de órdenes y cuentas (spec 005), con datos sintéticos.

Con `datos.serie`, el minuto i (desde las 09:30) abre en precio + i, máximo + 0,5, mínimo − 0,5 y
cierra en + 0,25: el precio sube un punto por minuto.
"""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from trading_replay import replay
from trading_replay.app import app
from trading_replay.config import INSTRUMENTOS
from trading_replay.historico import almacen
from trading_replay.operativa import servicio

cliente = TestClient(app)
INICIO = datetime(2024, 3, 12, 9, 30)


def preparar(datos, *simbolos, minutos=120):
    for simbolo in simbolos or ("NQ",):
        datos.serie(simbolo, INICIO, minutos, precio=5000.0 if simbolo == "ES" else 100.0)
        almacen.construir(INSTRUMENTOS[simbolo])


def ok(respuesta, codigo=200):
    assert respuesta.status_code == codigo, respuesta.text
    return respuesta.json()


def iniciar(instante="2024-03-12T09:40", simbolo="NQ"):
    return ok(cliente.post("/api/replay", json={"simbolo": simbolo, "inicio": instante}))


def avanzar(minutos=1, simbolo="NQ"):
    return ok(cliente.post("/api/replay/avanzar", json={"simbolo": simbolo, "minutos": minutos}))


def orden(**cuerpo):
    return ok(cliente.post("/api/ordenes", json={"contrato": "NQ", "lado": "compra", **cuerpo}))


def test_criterio_de_aceptacion_por_la_api(datos):
    preparar(datos)
    iniciar()  # último minuto 09:39: cierra en 109,25 → ASK 109,50
    cuerpo = orden(cantidad=2, sl_puntos=10, tp_puntos=5)
    [entrada] = cuerpo["ejecuciones"]
    assert (entrada["precio"], entrada["cantidad"], entrada["lado"]) == (109.5, 2, "compra")
    cuenta = cuerpo["cuenta"]
    assert cuenta["posiciones"][0]["cantidad"] == 2
    assert cuenta["posiciones"][0]["desde"] == datetime(2024, 3, 12, 9, 40, tzinfo=timezone.utc).timestamp()
    assert sorted((o["papel"], o["precio"]) for o in cuenta["ordenes"]) == [("sl", 99.5), ("tp", 114.5)]

    # El máximo del minuto de las 09:44 es 114,5: toca el TP.
    cuerpo = avanzar(10)
    [tp] = cuerpo["ejecuciones"]
    # `time` es la hora ET como la usa el gráfico: segundos como si fuera UTC.
    assert (tp["papel"], tp["precio"], tp["time"]) == ("tp", 114.5, datetime(2024, 3, 12, 9, 44, tzinfo=timezone.utc).timestamp())
    neto = (114.5 - 109.5) * 2 * 20 - 4 * 2.5
    assert cuerpo["cuenta"]["balance"] == 50_000 + neto == 50_190
    assert cuerpo["cuenta"]["pnl_sesion"] == neto
    assert cuerpo["cuenta"]["posiciones"] == [] and cuerpo["cuenta"]["ordenes"] == []

    [operacion] = ok(cliente.get("/api/operaciones"))
    assert (operacion["entrada"], operacion["salida"], operacion["pnl_neto"], operacion["sl_inicial"]) == (109.5, 114.5, 190, 99.5)
    assert (operacion["apertura"], operacion["cierre"]) == ("2024-03-12T09:40:00", "2024-03-12T09:44:00")
    assert len(ok(cliente.get("/api/ejecuciones", params={"simbolo": "NQ"}))) == 2


def test_una_orden_de_es_se_ejecuta_mientras_se_ve_nq(datos):
    preparar(datos, "NQ", "ES")
    iniciar()
    orden(contrato="ES", lado="venta", tipo="limite", precio=5015)
    cuerpo = avanzar(10)  # en el gráfico, NQ
    [venta] = cuerpo["ejecuciones"]
    assert (venta["contrato"], venta["precio"], venta["simbolo"]) == ("ES", 5015, "ES")
    assert cuerpo["cuenta"]["posiciones"][0]["cantidad"] == -1


def test_mercado_cerrado_espera_a_la_apertura(datos):
    datos.serie("NQ", INICIO, 30)  # 09:30 a 09:59
    datos.serie("NQ", INICIO + timedelta(hours=1), 30, precio=200.0)  # 10:30 a 10:59
    almacen.construir(INSTRUMENTOS["NQ"])
    iniciar("2024-03-12T10:15")
    cuerpo = orden()
    assert cuerpo["ejecuciones"] == [] and cuerpo["cuenta"]["ordenes"][0]["tipo"] == "mercado"
    [compra] = avanzar(1)["ejecuciones"]
    assert compra["precio"] == 200.25  # apertura de las 10:30 + 1 tick


def test_al_saltar_se_cierra_todo_al_precio_del_instante(datos):
    preparar(datos)
    iniciar()
    orden(cantidad=1)  # a 109,50
    orden(tipo="limite", precio=90)
    avanzar(5)  # último minuto 09:44, cierra en 114,25 (BID)
    cuerpo = iniciar("2024-03-12T10:30")
    [cierre] = cuerpo["liquidadas"]
    assert (cierre["lado"], cierre["precio"]) == ("venta", 114.25)
    cuenta = ok(cliente.get("/api/cuenta"))
    assert cuenta["posiciones"] == [] and cuenta["ordenes"] == []
    assert cuenta["balance"] == 50_000 + (114.25 - 109.5) * 20 - 5


def test_balance_e_historial_sobreviven_a_un_reinicio_y_el_replay_se_retoma(datos):
    preparar(datos)
    iniciar()
    orden(sl_puntos=20)
    avanzar(3)
    orden(cantidad=1)  # a las 09:43, a 112,50
    instante = replay.actual().instante

    # Reinicio: se olvida todo lo que hay en memoria.
    servicio._estado = None
    replay.terminar()
    assert servicio.restaurar_replay() is not None
    assert replay.actual().instante == instante
    cuenta = ok(cliente.get("/api/cuenta"))
    assert cuenta["posiciones"][0]["cantidad"] == 2
    assert [o["papel"] for o in cuenta["ordenes"]] == ["sl"]

    ok(cliente.post("/api/posiciones/NQ/cerrar"))  # a 112,25
    cuenta = ok(cliente.get("/api/cuenta"))
    assert cuenta["posiciones"] == [] and cuenta["ordenes"] == []
    balance = cuenta["balance"]
    assert balance == round(50_000 + (112.25 - 109.5) * 20 + (112.25 - 112.5) * 20 - 4 * 2.5, 2)

    servicio._estado = None
    replay.terminar()
    assert servicio.restaurar_replay() is None  # sin nada abierto no hay nada que retomar
    assert ok(cliente.get("/api/cuenta"))["balance"] == balance
    assert len(ok(cliente.get("/api/operaciones"))) == 1


def test_modificar_y_cancelar(datos):
    preparar(datos)
    iniciar()
    cuerpo = orden(sl_puntos=10)
    [sl] = cuerpo["cuenta"]["ordenes"]
    assert ok(cliente.patch(f"/api/ordenes/{sl['id']}", json={"precio": 105.1}))["cuenta"]["ordenes"][0]["precio"] == 105.0
    ok(cliente.patch(f"/api/ordenes/{sl['id']}", json={"precio": 120}), 422)  # stop de venta por encima
    ok(cliente.delete(f"/api/ordenes/{sl['id']}"))
    ok(cliente.delete(f"/api/ordenes/{sl['id']}"), 404)
    assert ok(cliente.post("/api/cuenta/cerrar-todo"))["cuenta"]["posiciones"] == []


def test_validaciones(datos):
    preparar(datos)
    ok(cliente.post("/api/ordenes", json={"contrato": "NQ", "lado": "compra"}), 409)  # sin replay
    iniciar()
    ok(cliente.post("/api/ordenes", json={"contrato": "XX", "lado": "compra"}), 422)
    ok(cliente.post("/api/ordenes", json={"contrato": "NQ", "lado": "compra", "tipo": "stop", "precio": 100}), 422)
    ok(cliente.post("/api/ordenes", json={"contrato": "NQ", "lado": "compra", "cantidad": 0}), 422)
    ok(cliente.post("/api/ordenes", json={"contrato": "NQ", "lado": "compra", "tipo": "limite"}), 422)


def test_cuentas_y_costes(datos):
    preparar(datos)
    [demo] = ok(cliente.get("/api/cuentas"))
    assert (demo["nombre"], demo["balance"], demo["activa"]) == ("Demo", 50_000, True)
    assert demo["costes"] == {"spread_ticks": 1, "deslizamiento_ticks": 0, "comision_mini": 2.5, "comision_micro": 0.75}

    reto = ok(cliente.post("/api/cuentas", json={"nombre": "Reto 100k", "balance_inicial": 100_000}))
    assert reto["activa"] and ok(cliente.get("/api/cuenta"))["balance"] == 100_000
    ok(cliente.patch(f"/api/cuentas/{reto['id']}", json={"spread_ticks": 2, "comision_mini": 2}))

    iniciar()
    [compra] = orden()["ejecuciones"]
    assert compra["precio"] == 109.75  # 2 ticks de spread
    ok(cliente.patch(f"/api/cuentas/{demo['id']}", json={"activa": True}), 409)  # con posición abierta
    ok(cliente.post("/api/cuenta/cerrar-todo"))
    ok(cliente.patch(f"/api/cuentas/{demo['id']}", json={"activa": True}))
    assert ok(cliente.get("/api/cuenta"))["balance"] == 50_000
    ok(cliente.patch("/api/cuentas/999", json={"activa": True}), 404)


def test_renombrar_reiniciar_y_borrar_cuentas(datos):
    preparar(datos)
    [demo] = ok(cliente.get("/api/cuentas"))
    ok(cliente.patch(f"/api/cuentas/{demo['id']}", json={"spread_ticks": 2}))
    iniciar()
    orden()
    # RF-26: renombrar se puede con una posición abierta.
    assert ok(cliente.patch(f"/api/cuentas/{demo['id']}", json={"nombre": "Libre"}))["nombre"] == "Libre"
    # RF-27 y RF-28: reiniciar o borrar la activa, no.
    ok(cliente.post(f"/api/cuentas/{demo['id']}/reiniciar"), 409)
    ok(cliente.post("/api/cuenta/cerrar-todo"))
    assert ok(cliente.get("/api/cuenta"))["balance"] < 50_000
    assert ok(cliente.get("/api/operaciones"))

    reiniciada = ok(cliente.post(f"/api/cuentas/{demo['id']}/reiniciar"))
    assert (reiniciada["nombre"], reiniciada["balance"], reiniciada["costes"]["spread_ticks"]) == ("Libre", 50_000, 2)
    cuenta = ok(cliente.get("/api/cuenta"))
    assert cuenta["balance"] == 50_000 and cuenta["pnl_sesion"] == 0
    assert ok(cliente.get("/api/operaciones")) == [] and ok(cliente.get("/api/ejecuciones")) == []

    ok(cliente.delete(f"/api/cuentas/{demo['id']}"), 409)  # la única
    reto = ok(cliente.post("/api/cuentas", json={"nombre": "Reto", "balance_inicial": 100_000}))
    orden()
    ok(cliente.delete(f"/api/cuentas/{reto['id']}"), 409)  # activa con posición abierta
    ok(cliente.post("/api/cuenta/cerrar-todo"))
    restantes = ok(cliente.delete(f"/api/cuentas/{reto['id']}"))
    assert [(c["nombre"], c["activa"]) for c in restantes] == [("Libre", True)]
    assert ok(cliente.get("/api/cuenta"))["balance"] == 50_000
    ok(cliente.delete(f"/api/cuentas/{reto['id']}"), 404)
    ok(cliente.post("/api/cuentas/999/reiniciar"), 404)


def test_borrar_cuenta_no_activa(datos):
    preparar(datos)
    [demo] = ok(cliente.get("/api/cuentas"))
    otra = ok(cliente.post("/api/cuentas", json={"nombre": "Otra", "balance_inicial": 25_000}))
    ok(cliente.patch(f"/api/cuentas/{demo['id']}", json={"activa": True}))
    iniciar()
    orden()
    # La cuenta que no está activa no tiene nada abierto: se borra aunque la activa tenga una posición.
    ok(cliente.patch(f"/api/cuentas/{otra['id']}", json={"activa": True}), 409)
    restantes = ok(cliente.delete(f"/api/cuentas/{otra['id']}"))
    assert [(c["nombre"], c["activa"]) for c in restantes] == [("Demo", True)]
    assert ok(cliente.get("/api/cuenta"))["posiciones"][0]["cantidad"] == 1
