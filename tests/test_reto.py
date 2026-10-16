"""Perfiles y reglas de los retos de prop firm (spec 006), sin servidor ni base de datos."""

from datetime import datetime, time

import pytest

from trading_replay.operativa import perfiles, reto
from trading_replay.operativa.reto import Dia

AHORA = datetime(2024, 3, 12, 10, 0)


def perfil(id_perfil):
    return perfiles.buscar(id_perfil)


def test_perfiles_incluidos():
    todos = perfiles.todos()
    topstep = todos["topstep-50k"]
    assert (topstep.titulo, topstep.objetivo, topstep.perdida_maxima.importe) == ("Topstep Trading Combine 50K", 3000, 2000)
    assert topstep.hora_cierre == time(16, 10) and topstep.tope_umbral == 50_000
    static = todos["daytraders-static-50k"]
    assert (static.objetivo, static.perdida_maxima.tipo, static.limite_diario, static.contratos_maximos) == (3750, "estatica", None, 6)
    assert todos["daytraders-trail-50k"].tope_umbral == 53_000
    assert len([p for p in todos.values() if p.empresa == "DayTraders"]) == 10


def test_perfil_no_valido(tmp_path):
    (tmp_path / "x.json").write_text('{"empresa": "X", "cuentas": [{"id": "x", "nombre": "X", "balance_inicial": 1, '
                                     '"objetivo": 1, "perdida_maxima": {"importe": 1, "tipo": "rara"}}]}')
    with pytest.raises(perfiles.PerfilNoValido):
        perfiles.leer(tmp_path)


def test_trailing_al_cierre_con_tope():
    p = perfil("topstep-50k")
    estado = reto.nuevo(1, p)
    assert estado.umbral == 48_000
    reto.cerrar_dia(estado, p, 50_500, [Dia("a", 500)], AHORA)
    assert estado.umbral == 48_500
    reto.cerrar_dia(estado, p, 50_000, [Dia("a", 500), Dia("b", -500)], AHORA)
    assert estado.umbral == 48_500  # no baja
    reto.cerrar_dia(estado, p, 52_500, [Dia("a", 500), Dia("b", -500), Dia("c", 2500)], AHORA)
    assert estado.umbral == 50_000  # tope: el balance inicial


def test_trailing_intradia_y_estatica():
    trail = perfil("daytraders-trail-50k")
    estado = reto.nuevo(1, trail)
    assert estado.umbral == 47_500
    reto.actualizar_pico(estado, trail, 52_000)
    reto.actualizar_pico(estado, trail, 51_000)
    assert (estado.pico, estado.umbral) == (52_000, 49_500)
    reto.actualizar_pico(estado, trail, 60_000)
    assert estado.umbral == 53_000  # tope: balance inicial + objetivo

    static = perfil("daytraders-static-50k")
    estado = reto.nuevo(1, static)
    reto.actualizar_pico(estado, static, 53_000)
    reto.cerrar_dia(estado, static, 53_000, [Dia("a", 1000)], AHORA)
    assert estado.umbral == 49_000


def test_nivel_de_liquidacion():
    p = perfil("topstep-50k")
    estado = reto.nuevo(1, p)
    assert reto.nivel_liquidacion(estado, p) == (49_000, "limite_diario")
    estado.balance_inicio_dia = 48_800
    assert reto.nivel_liquidacion(estado, p) == (48_000, "perdida_maxima")


def test_precio_de_ruptura():
    # Largo de 2 NQ (10 $ por tick) a 400 ticks con 50.000 $: balance(b) = 50.000 + 10 × (b − 400).
    assert reto.precio_ruptura(48_000, 50_000 - 4000, 10) == 200  # justo en el umbral
    assert reto.precio_ruptura(48_005, 50_000 - 4000, 10) == 200  # 200,5: con 201 aún no se llega
    # Corto: balance(b) = 50.000 − 10 × (b − 400).
    assert reto.precio_ruptura(48_005, 50_000 + 4000, -10) == 600  # 599,5: con 599 aún no se llega
    assert reto.precio_ruptura(48_000, 50_000, 0) is None


def test_romper():
    p = perfil("topstep-50k")
    estado = reto.nuevo(1, p)
    evento = reto.romper(estado, p, "limite_diario", 49_000, AHORA)
    assert evento["tipo"] == "pausa" and estado.estado == "en_curso" and estado.bloqueo == "limite_diario"
    evento = reto.romper(estado, p, "perdida_maxima", 48_000, AHORA)
    assert evento["tipo"] == "suspendido" and estado.estado == "suspendido"
    assert estado.motivo == "Pérdida máxima: el balance llegó a 48.000,00 $"


def test_consistencia():
    p = perfil("topstep-50k")
    assert reto.objetivo_efectivo(p, 2200) == 4000
    assert reto.objetivo_efectivo(p, 1000) == 3000
    hecho = reto.progreso(p, 52_500, [Dia("a", 1800), Dia("b", -300), Dia("c", 1000)])
    assert (hecho.mejor_dia, hecho.objetivo_efectivo, hecho.falta) == (1800, 3272.73, 772.73)


def test_dias_minimos_y_aprobado():
    p = perfil("daytraders-trail-50k")
    estado = reto.nuevo(1, p)
    dias = [Dia("a", 1500), Dia("b", 150), Dia("c", 1500)]
    hecho = reto.progreso(p, 53_150, dias[:2])
    assert (hecho.dias_validos, hecho.faltan_dias, hecho.aprobaria) == (1, 1, False)
    assert reto.cerrar_dia(estado, p, 53_150, dias, AHORA)["tipo"] == "aprobado"
    assert estado.estado == "aprobado" and estado.fin == AHORA
    # Ya aprobado: no se vuelve a anunciar.
    assert reto.cerrar_dia(estado, p, 53_150, dias, AHORA) is None


def test_no_aprueba_por_consistencia():
    p = perfil("daytraders-trail-50k")
    estado = reto.nuevo(1, p)
    # 3.200 $ con un mejor día de 3.000 $: la regla del 50 % pide 6.000 $.
    assert reto.cerrar_dia(estado, p, 53_200, [Dia("a", 3000), Dia("b", 200)], AHORA) is None


def test_contratos_en_uso():
    assert reto.contratos_en_uso({"NQ": 4, "MES": -11}) == 5.1
    assert reto.contratos_en_uso({"NQ": 0}) == 0


def test_dinero():
    assert reto.dinero(1234.5) == "1.234,50 $"
    assert reto.dinero(-772.727) == "−772,73 $"
