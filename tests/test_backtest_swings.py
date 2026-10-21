"""Spec 012, RF-12: los pivotes no se conocen hasta que han cerrado `n` velas más."""

from datetime import datetime

from trading_replay.backtest.estrategia import VelasCerradas, a_segundos
from trading_replay.backtest.swings import Pivotes


def velas_de(maximos, minimos):
    velas = VelasCerradas("5m")
    t = a_segundos(datetime(2024, 3, 12, 9, 30))
    for i, (h, l) in enumerate(zip(maximos, minimos)):
        velas.anadir(t + 300 * i, (h + l) / 2, h, l, (h + l) / 2, 1.0)
    return velas


def test_el_pivote_llega_n_velas_despues_de_formarse():
    # Máximos con un pico en la vela 3 (110); n = 2: se sabe al cerrar la vela 5.
    maximos = [100, 102, 105, 110, 106, 104, 103]
    minimos = [m - 2 for m in maximos]
    pivotes = Pivotes(2)
    for cerradas in range(1, len(maximos) + 1):
        nuevos = pivotes.actualizar(velas_de(maximos[:cerradas], minimos[:cerradas]))
        altos = [p for p in nuevos if p.alto]
        if cerradas < 6:
            assert altos == [], f"el pivote no puede conocerse con {cerradas} velas"
        if cerradas == 6:
            [pico] = altos
            assert (pico.indice, pico.precio, pico.confirmado_en) == (3, 110, 5)


def test_igual_resultado_velas_a_velas_que_de_golpe():
    maximos = [100, 103, 101, 106, 104, 102, 107, 105, 103, 101, 104, 102, 100, 99]
    minimos = [m - 3 for m in maximos]
    de_golpe = Pivotes(2)
    de_golpe.actualizar(velas_de(maximos, minimos))
    una_a_una = Pivotes(2)
    for k in range(1, len(maximos) + 1):
        una_a_una.actualizar(velas_de(maximos[:k], minimos[:k]))
    assert de_golpe.zigzag == una_a_una.zigzag and de_golpe.zigzag


def test_dos_altos_seguidos_se_quedan_en_el_mayor_y_uno_menor_se_ignora():
    # Altos en las velas 5 (112) y 8 (115) sin ningún bajo entre medias (los mínimos suben siempre).
    maximos = [105, 103, 101, 104, 108, 112, 109, 107, 115, 111, 108, 104, 106, 108, 109]
    minimos = [90 + i for i in range(len(maximos))]
    p = Pivotes(2)
    p.actualizar(velas_de(maximos, minimos))
    assert [(x.indice, x.precio) for x in p.zigzag] == [(8, 115)]
    # Un alto posterior más bajo (113 en la vela 14) no lo cambia.
    maximos = maximos[:12] + [106, 113, 108, 105, 104]
    p = Pivotes(2)
    p.actualizar(velas_de(maximos, [90 + i for i in range(len(maximos))]))
    assert [x.precio for x in p.zigzag] == [115]


def test_el_zigzag_alterna_altos_y_bajos():
    maximos = [100, 105, 110, 106, 102, 98, 101, 106, 111, 108, 104, 100, 97, 99, 103]
    minimos = [m - 2 for m in maximos]
    p = Pivotes(2)
    p.actualizar(velas_de(maximos, minimos))
    tipos = [x.alto for x in p.zigzag]
    assert len(tipos) >= 3 and all(a != b for a, b in zip(tipos, tipos[1:]))


def test_impulso_alcista_y_bajista():
    maximos = [105, 103, 101, 104, 108, 112, 109, 107, 105, 103, 102, 104, 105]
    minimos = [m - 2 for m in maximos]
    p = Pivotes(2)
    p.actualizar(velas_de(maximos, minimos))
    origen, final = p.impulso
    assert origen.alto != final.alto
    assert final.indice > origen.indice
