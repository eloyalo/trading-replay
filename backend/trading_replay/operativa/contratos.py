"""Contratos de futuros que se operan con los datos de cada instrumento (spec 005, RF-1)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Contrato:
    codigo: str
    simbolo: str  # instrumento con cuyos datos se opera
    multiplicador: float  # $ por punto
    tick: float  # puntos
    valor_tick: float  # $ por tick, escrito a mano para no arrastrar 0,1 × 100 = 10,000000000000002
    micro: bool


CONTRATOS = {
    c.codigo: c
    for c in (
        Contrato("NQ", "NQ", 20, 0.25, 5.0, False),
        Contrato("MNQ", "NQ", 2, 0.25, 0.5, True),
        Contrato("ES", "ES", 50, 0.25, 12.5, False),
        Contrato("MES", "ES", 5, 0.25, 1.25, True),
        Contrato("GC", "GC", 100, 0.1, 10.0, False),
        Contrato("MGC", "GC", 10, 0.1, 1.0, True),
    )
}
