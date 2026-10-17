"""Backtest con las reglas de un reto (spec 009), con perfiles de prueba y días diseñados a mano.

Cada día tiene minutos de 09:30 a 10:29, planos a 100 salvo los indicados. La estrategia sigue un guion:
a la hora indicada (cierre de la vela de 1m), hace lo que diga. Una compra a las 09:31 sale al ASK 100,25.
NQ: $20 por punto y 5 $ de comisiones por operación de un contrato.
"""

from datetime import date, datetime, timedelta

import numpy as np

from trading_replay.backtest import Estrategia, ejecutor, metricas
from trading_replay.backtest.estrategia import a_segundos
from trading_replay.operativa.perfiles import LimiteDiario, PerdidaMaxima, Perfil
from trading_replay.operativa.reto import APROBADO, EN_CURSO, SUSPENDIDO

UN_MINUTO = timedelta(minutes=1)
MARTES = date(2024, 3, 12)


def perfil(**cambios) -> Perfil:
    datos = dict(id="prueba", empresa="Prueba", nombre="50K", balance_inicial=50_000.0, objetivo=1000.0, perdida_maxima=PerdidaMaxima(500, "estatica"))
    return Perfil(**{**datos, **cambios})


def dias(*cambios_por_dia: dict) -> list[tuple]:
    """Un día por argumento desde el martes 12 de marzo de 2024 (saltando el fin de semana): {"HH:MM": (o, h, l, c)}."""
    filas, dia = [], MARTES
    for cambios in cambios_por_dia:
        inicio = datetime.combine(dia, datetime.min.time()) + timedelta(hours=9, minutes=30)
        for i in range(60):
            momento = inicio + i * UN_MINUTO
            filas.append((momento, *cambios.get(f"{momento:%H:%M}", (100, 100, 100, 100))))
        dia += timedelta(days=3 if dia.weekday() == 4 else 1)
    return filas


def correr(guion: dict, filas: list[tuple], p: Perfil):
    """`guion`: {"AAAA-MM-DD HH:MM": función(estrategia)}."""

    class Guion(Estrategia):
        nombre = "Guion"
        timeframe = "1m"

        def al_cerrar_vela(self, vela):
            accion = guion.get(f"{self.instante:%Y-%m-%d %H:%M}")
            if accion:
                accion(self)

    columnas = {
        "t": np.array([a_segundos(f[0]) for f in filas], dtype="i8"),
        **{k: np.array([f[i + 1] for f in filas], dtype="f8") for i, k in enumerate(("open", "high", "low", "close"))},
        "volume": np.ones(len(filas)),
    }
    return ejecutor.Ejecutor(Guion(), "NQ", perfil=p).ejecutar(columnas)


def test_aprobado_suspendido_al_precio_de_ruptura_e_intentos_encadenados():
    guion = {
        "2024-03-12 09:31": lambda e: e.comprar(1, tp_puntos=30),  # TP 130,25: +595
        "2024-03-13 09:31": lambda e: e.comprar(1, tp_puntos=25),  # TP 125,25: +495 → 1.090 en 2 días
        "2024-03-14 09:31": lambda e: e.comprar(1),  # intento 2: el precio se hunde
        "2024-03-14 09:40": lambda e: e.comprar(1),  # intento suspendido: no se envía
        "2024-03-15 09:31": lambda e: e.comprar(1),  # intento 3
    }
    filas = dias({"09:31": (100, 131, 100, 100)}, {"09:31": (100, 126, 100, 100)}, {"09:31": (100, 100, 70, 70)}, {})
    r = correr(guion, filas, perfil(dias_minimos=2))
    intentos = r.reto.intentos
    assert [(i.numero, i.resultado, i.dias) for i in intentos] == [(1, APROBADO, 2), (2, SUSPENDIDO, 1), (3, EN_CURSO, 1)]
    assert intentos[0].beneficio == 1090 and intentos[0].mejor_dia == 595
    # Pérdida máxima estática: umbral 49.500. Tras 2,50 $ de comisión de entrada, el balance en vivo llega al
    # umbral con el BID por debajo de 75,375: se cierra en 75,25, no en el mínimo del minuto (70).
    suspendida = r.operaciones[2]
    assert (suspendida.intento, suspendida.salida, suspendida.motivo_salida) == (2, 75.25, "Pérdida máxima")
    assert intentos[1].beneficio == -505 and intentos[1].motivo.startswith("Pérdida máxima")
    assert intentos[1].fin == datetime(2024, 3, 14, 9, 31)
    assert [op.intento for op in r.operaciones] == [1, 1, 2, 3]
    assert r.reto.rechazadas == {"Intento terminado (el siguiente empieza al día siguiente)": 1}
    assert [i.operaciones for i in intentos] == [2, 1, 1]


def test_limite_diario_en_pausa_hasta_el_dia_siguiente():
    guion = {
        "2024-03-12 09:31": lambda e: e.comprar(1),
        "2024-03-12 09:40": lambda e: e.comprar(1),
        "2024-03-13 09:31": lambda e: e.comprar(1, tp_puntos=10),
    }
    filas = dias({"09:31": (100, 100, 80, 80)}, {"09:31": (100, 111, 100, 100)})
    r = correr(guion, filas, perfil(perdida_maxima=PerdidaMaxima(2000, "estatica"), limite_diario=LimiteDiario(300, "pausa")))
    primera, segunda = r.operaciones
    # Límite diario: 49.700. Tras la comisión de entrada, se rompe con el BID por debajo de 85,375: en 85,25.
    assert (primera.salida, primera.motivo_salida) == (85.25, "Límite diario")
    assert r.reto.rechazadas == {"Límite diario alcanzado": 1}
    assert (segunda.motivo_salida, segunda.intento) == ("TP", 1)
    assert [(i.resultado, i.dias) for i in r.reto.intentos] == [(EN_CURSO, 2)]


def test_la_consistencia_retrasa_el_aprobado():
    # Con consistencia del 50 %, un mejor día de 1.195 $ pide 2.390 $ en total: no aprueba el primer día.
    guion = {f"2024-03-{d} 09:31": (lambda e: e.comprar(1, tp_puntos=60)) for d in (12, 13)}
    filas = dias({"09:31": (100, 161, 100, 100)}, {"09:31": (100, 161, 100, 100)}, {})
    r = correr(guion, filas, perfil(consistencia=0.5, dias_minimos=1))
    [aprobado, siguiente] = r.reto.intentos
    assert (aprobado.resultado, aprobado.dias, aprobado.beneficio) == (APROBADO, 2, 2390)
    assert siguiente.resultado == EN_CURSO and siguiente.operaciones == 0


def test_contratos_maximos_y_hora_de_cierre():
    guion = {
        "2024-03-12 09:31": lambda e: (e.comprar(3), e.comprar(2)),
        "2024-03-12 10:05": lambda e: e.comprar(1),
    }
    filas = dias({"10:00": (104, 104, 104, 104)})
    r = correr(guion, filas, perfil(contratos_maximos=2, hora_cierre=datetime(2024, 1, 1, 10, 0).time()))
    [op] = r.operaciones
    # La de 3 contratos no se envía; la de 2 se cierra a las 10:00, en la apertura del minuto (104).
    assert (op.cantidad, op.salida, op.motivo_salida) == (2, 104, "Hora de cierre del reto")
    assert r.reto.rechazadas == {"Contratos máximos": 1, "Fuera del horario del reto": 1}


def test_resumen_del_reto():
    guion = {
        "2024-03-12 09:31": lambda e: e.comprar(1, tp_puntos=30),
        "2024-03-13 09:31": lambda e: e.comprar(1, tp_puntos=25),
        "2024-03-14 09:31": lambda e: e.comprar(1),
    }
    filas = dias({"09:31": (100, 131, 100, 100)}, {"09:31": (100, 126, 100, 100)}, {"09:31": (100, 100, 70, 70)}, {})
    r = correr(guion, filas, perfil(dias_minimos=2))
    resumen = metricas.resumen_reto(r.reto.intentos, r.reto.rechazadas)
    assert (resumen["intentos"], resumen["aprobados"], resumen["suspendidos"], resumen["en_curso"]) == (3, 1, 1, 1)
    assert resumen["aprobacion"] == 0.5
    assert (resumen["dias_hasta_aprobar"], resumen["dias_hasta_suspender"]) == (2, 1)
    assert resumen["motivos_suspension"] == [{"motivo": "Pérdida máxima", "intentos": 1}]
    assert (resumen["beneficio_aprobados"], resumen["beneficio_suspendidos"]) == (1090, -505)
    assert resumen["rechazadas"] == []
