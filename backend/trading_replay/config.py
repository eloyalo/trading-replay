"""Configuración común: rutas, instrumentos y horarios."""

import os
from dataclasses import dataclass
from datetime import date, time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
ZONA_MERCADO = "America/New_York"

# Primer día del histórico (4 años antes del inicio del proyecto).
FECHA_INICIO = date(2022, 10, 15)


def carpeta_datos() -> Path:
    """Carpeta de datos; se puede cambiar con TRADING_REPLAY_DATOS (útil en tests)."""
    return Path(os.environ.get("TRADING_REPLAY_DATOS", RAIZ / "datos"))


def carpeta_estrategias() -> Path:
    """Carpeta de las estrategias del backtest (spec 008); se puede cambiar con TRADING_REPLAY_ESTRATEGIAS."""
    return Path(os.environ.get("TRADING_REPLAY_ESTRATEGIAS", RAIZ / "estrategias"))


@dataclass(frozen=True)
class Instrumento:
    simbolo: str
    nombre: str
    dukascopy: str
    unidad_precio: float
    # Hora ET a la que el CFD deja de cotizar antes de la pausa diaria (reabre a las 18:00 ET).
    cierre_diario: time


INSTRUMENTOS = {
    i.simbolo: i
    for i in (
        Instrumento("NQ", "Nasdaq 100", "USATECHIDXUSD", 0.001, time(16, 15)),
        Instrumento("ES", "S&P 500", "USA500IDXUSD", 0.001, time(16, 15)),
        Instrumento("GC", "Oro", "XAUUSD", 0.001, time(17, 0)),
    )
}
