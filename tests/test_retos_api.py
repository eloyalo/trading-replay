"""Retos de prop firm por la API (spec 006), con datos sintéticos y los perfiles reales.

Con `datos.serie`, el minuto i (desde las 09:30) abre en 100 + i, máximo + 0,5, mínimo − 0,5 y cierra
en + 0,25: el precio sube un punto por minuto. Para perder, se vende.
"""

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from trading_replay.app import app
from trading_replay.config import INSTRUMENTOS
from trading_replay.historico import almacen

cliente = TestClient(app)
INICIO = datetime(2024, 3, 12, 9, 30)


def preparar(datos, *simbolos, inicio=INICIO, minutos=120):
    for simbolo in simbolos or ("NQ",):
        datos.serie(simbolo, inicio, minutos, precio=5000.0 if simbolo == "ES" else 100.0)
        almacen.construir(INSTRUMENTOS[simbolo])


def ok(respuesta, codigo=200):
    assert respuesta.status_code == codigo, respuesta.text
    return respuesta.json()


def reto_nuevo(perfil):
    return ok(cliente.post("/api/cuentas", json={"perfil": perfil}))


def iniciar(instante="2024-03-12T09:40"):
    return ok(cliente.post("/api/replay", json={"simbolo": "NQ", "inicio": instante}))


def avanzar(minutos):
    return ok(cliente.post("/api/replay/avanzar", json={"simbolo": "NQ", "minutos": minutos}))


def mercado(lado, cantidad, contrato="NQ", codigo=200):
    return ok(cliente.post("/api/ordenes", json={"contrato": contrato, "lado": lado, "cantidad": cantidad}), codigo)


def test_perfiles_y_cuenta_de_reto(datos):
    preparar(datos)
    perfiles = ok(cliente.get("/api/perfiles"))
    assert {"id": "topstep-50k", "empresa": "Topstep", "nombre": "Trading Combine 50K",
            "titulo": "Topstep Trading Combine 50K", "balance_inicial": 50_000} in perfiles
    cuenta = reto_nuevo("daytraders-static-50k")
    assert (cuenta["nombre"], cuenta["balance"], cuenta["perfil"]) == ("DayTraders Static 50K", 50_000, "daytraders-static-50k")
    reto = ok(cliente.get("/api/cuenta"))["reto"]
    assert (reto["estado"], reto["umbral"], reto["objetivo"], reto["dia"]) == ("en_curso", 49_000, 3750, 0)
    ok(cliente.post("/api/cuentas", json={"perfil": "no-existe"}), 422)
    # Las cuentas libres siguen igual.
    libre = ok(cliente.post("/api/cuentas", json={"nombre": "Libre", "balance_inicial": 10_000}))
    assert libre["perfil"] is None and ok(cliente.get("/api/cuenta"))["reto"] is None


def test_suspendido_por_perdida_maxima(datos):
    preparar(datos)
    reto_nuevo("daytraders-static-50k")
    iniciar()
    assert ok(cliente.get("/api/cuenta"))["reto"]["dia"] == 1
    # Venta de 6 NQ a 109,25 (BID): balance 49.985 $. El umbral fijo de 49.000 $ se rompe con el
    # ASK a 117,50 (BID 117,25), en el minuto de las 09:47, cuyo máximo es 117,50.
    cuenta = mercado("venta", 6)["cuenta"]
    assert cuenta["reto"]["liquidacion"] == {"NQ": 117.25}
    respuesta = avanzar(10)
    cuenta = respuesta["cuenta"]
    [cierre] = [e for e in respuesta["ejecuciones"] if e["papel"] == "cierre"]
    assert (cierre["precio"], cierre["time"]) == (117.5, datetime(2024, 3, 12, 9, 47, tzinfo=timezone.utc).timestamp())
    assert cuenta["balance"] == 50_000 - 15 + (109.25 - 117.5) * 20 * 6 - 15 == 48_980
    assert cuenta["posiciones"] == []
    assert cuenta["reto"]["estado"] == "suspendido"
    assert [e["tipo"] for e in cuenta["eventos"]] == ["suspendido"]
    assert cuenta["eventos"][0]["mensaje"] == "Pérdida máxima: el balance llegó a 49.000,00 $"
    assert ok(cliente.get("/api/cuenta"))["eventos"] == []  # se entregan una vez
    assert "suspendido" in mercado("compra", 1, codigo=422)["detail"]


def test_limite_diario_pausa_hasta_el_siguiente_salto(datos):
    preparar(datos)
    reto_nuevo("topstep-50k")
    iniciar()
    # Venta de 5 NQ a 109,25: 49.987,50 $. El límite diario (49.000 $) se toca con el BID a 119,
    # que es la apertura de las 09:49: se cierra al ASK de 119,25.
    mercado("venta", 5)
    cuenta = avanzar(10)["cuenta"]
    assert cuenta["balance"] == 49_987.5 + (109.25 - 119.25) * 20 * 5 - 12.5 == 48_975
    assert [e["tipo"] for e in cuenta["eventos"]] == ["pausa"]
    reto = cuenta["reto"]
    assert reto["estado"] == "en_curso" and reto["bloqueo"].startswith("Límite diario")
    assert (reto["nivel"], reto["regla"]) == (48_000, "perdida_maxima")
    assert "Límite diario" in mercado("venta", 1, codigo=422)["detail"]
    avanzar(5)
    assert ok(cliente.get("/api/cuenta"))["eventos"] == []  # no se repite
    # Siguiente salto: día nuevo, se puede operar. El umbral no sube con un día perdedor.
    iniciar()
    reto = ok(cliente.get("/api/cuenta"))["reto"]
    assert (reto["dia"], reto["bloqueo"], reto["umbral"], reto["nivel"]) == (2, None, 48_000, 48_000)
    mercado("compra", 1)


def test_contratos_maximos(datos):
    preparar(datos, "NQ", "ES")
    reto_nuevo("topstep-50k")
    iniciar()
    ok(cliente.post("/api/ordenes", json={"contrato": "NQ", "lado": "compra", "tipo": "limite", "cantidad": 3, "precio": 100}))
    assert "5 contratos" in mercado("compra", 3, codigo=422)["detail"]  # 3 pendientes + 3 = 6
    mercado("compra", 1)
    mercado("venta", 11, contrato="MES", codigo=422)  # 3 + 1 + 1,1 = 5,1
    mercado("venta", 10, contrato="MES")  # 5
    mercado("venta", 2)  # reduce la posición: NQ 3 + 1 − 2 = 2, más 1 de MES


def test_hora_de_cierre(datos):
    preparar(datos, inicio=datetime(2024, 3, 12, 16, 0), minutos=20)
    reto_nuevo("topstep-50k")
    iniciar("2024-03-12T16:05")
    mercado("compra", 1)  # al ASK de 104,50
    cuenta = avanzar(10)["cuenta"]
    assert cuenta["posiciones"] == [] and [e["tipo"] for e in cuenta["eventos"]] == ["hora_cierre"]
    # Se cerró a la apertura de las 16:10 (110): +5,50 puntos.
    assert cuenta["balance"] == 50_000 + (110 - 104.5) * 20 - 5 == 50_105
    assert cuenta["reto"]["bloqueo"].startswith("Fuera del horario")
    assert "Fuera del horario" in mercado("compra", 1, codigo=422)["detail"]


def ganar_un_dia(contratos=10, minutos=8):
    """Compra a 109,50 (ASK) a las 09:40, avanza y cierra todo al último precio."""
    iniciar()
    mercado("compra", contratos)
    avanzar(minutos)
    ok(cliente.post("/api/cuenta/cerrar-todo"))


def test_aprobado_al_cerrar_el_dia(datos):
    preparar(datos)
    reto_nuevo("daytraders-trail-50k")
    ganar_un_dia()  # (117,25 − 109,50) × 200 − 50 = +1.500 $
    ganar_un_dia()  # otro +1.500 $: 3.000 $ con el mejor día en el 50 %
    cuenta = ok(cliente.get("/api/cuenta"))
    reto = cuenta["reto"]
    assert (cuenta["balance"], reto["estado"], reto["falta"], reto["dias_validos"]) == (53_000, "en_curso", 0, 2)
    assert cuenta["eventos"] == []  # se aprueba al cerrar el día, no al tocar el objetivo
    ok(cliente.delete("/api/replay"))
    cuenta = ok(cliente.get("/api/cuenta"))
    [evento] = cuenta["eventos"]
    assert evento["tipo"] == "aprobado"
    assert (evento["beneficio"], evento["dias"], evento["mejor_dia"]) == (3000, 2, 1500)
    assert cuenta["reto"]["estado"] == "aprobado"
    iniciar()
    assert "aprobado" in mercado("compra", 1, codigo=422)["detail"]


def test_resumen_de_cuentas_y_consistencia(datos):
    preparar(datos)
    reto_nuevo("topstep-50k")
    ganar_un_dia(contratos=5)  # (117,25 − 109,50) × 100 − 25 = +750 $
    iniciar()
    mercado("venta", 5)  # a 109,25
    avanzar(3)
    ok(cliente.post("/api/cuenta/cerrar-todo"))  # al ASK de 112,50: −325 − 25 = −350 $
    tarjetas = ok(cliente.get("/api/cuentas/resumen"))
    demo, topstep = tarjetas
    assert demo["reto"] is None and demo["operaciones"] == 0
    assert (topstep["beneficio"], topstep["operaciones"], topstep["acierto"]) == (400, 2, 0.5)
    assert (topstep["mayor_ganancia"], topstep["mayor_perdida"], topstep["comisiones"]) == (750, -350, 50)
    reto = topstep["reto"]
    assert [(d["pnl"], d["en_curso"]) for d in reto["dias"]] == [(750, False), (-350, True)]
    assert (reto["dia"], reto["mejor_dia"], reto["objetivo_efectivo"], reto["falta"]) == (2, 750, 3000, 2600)
    consistencia = reto["consistencia"]
    assert consistencia["porcentaje_mejor"] == 1.875  # 750 de 400
    assert (consistencia["beneficio_necesario"], consistencia["falta"]) == (1363.64, 963.64)
    assert consistencia["sube_objetivo"] is False


def test_reiniciar_reto_guarda_el_intento(datos):
    preparar(datos)
    cuenta = reto_nuevo("daytraders-static-50k")
    iniciar()
    mercado("venta", 6)
    avanzar(10)  # suspendido
    ok(cliente.delete("/api/replay"))
    ok(cliente.post(f"/api/cuentas/{cuenta['id']}/reiniciar"))
    tarjeta = next(t for t in ok(cliente.get("/api/cuentas/resumen")) if t["id"] == cuenta["id"])
    [intento] = tarjeta["intentos"]
    assert (intento["numero"], intento["resultado"], intento["dias"], intento["beneficio"]) == (1, "suspendido", 1, -1020)
    reto = tarjeta["reto"]
    assert (reto["intento"], reto["estado"], reto["umbral"], tarjeta["balance"]) == (2, "en_curso", 49_000, 50_000)
    iniciar()
    mercado("compra", 1)
