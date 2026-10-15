"""Servidor principal: API bajo /api y frontend estático en /."""

from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from trading_replay import __version__
from trading_replay.config import INSTRUMENTOS
from trading_replay.historico import almacen

RAIZ = Path(__file__).resolve().parents[2]
FRONTEND = RAIZ / "frontend"

# Cuánta historia se devuelve por defecto en cada timeframe, para que la carga sea ágil.
VENTANA_POR_DEFECTO = {
    "1m": timedelta(days=3),
    "5m": timedelta(days=14),
    "15m": timedelta(days=31),
    "30m": timedelta(days=62),
    "1h": timedelta(days=92),
    "4h": timedelta(days=366),
    "1D": timedelta(days=366 * 10),
}

app = FastAPI(title="trading-replay", version=__version__)


@app.get("/api/estado")
def estado() -> dict:
    return {"ok": True, "version": __version__}


@app.get("/api/instrumentos")
def instrumentos() -> list[dict]:
    """Instrumentos disponibles y el rango de datos descargado de cada uno (hora ET)."""
    resultado = []
    for instrumento in INSTRUMENTOS.values():
        disponible = almacen.rango(instrumento.simbolo)
        resultado.append(
            {
                "simbolo": instrumento.simbolo,
                "nombre": instrumento.nombre,
                "desde": disponible[0].isoformat() if disponible else None,
                "hasta": disponible[1].isoformat() if disponible else None,
            }
        )
    return resultado


@app.get("/api/velas")
def velas(
    simbolo: str,
    tf: str = "15m",
    desde: datetime | None = Query(None, description="hora ET; por defecto, una ventana según el timeframe"),
    hasta: datetime | None = Query(None, description="hora ET, excluida; por defecto, el final de los datos"),
) -> dict:
    simbolo = simbolo.upper()
    if simbolo not in INSTRUMENTOS:
        raise HTTPException(404, f"Instrumento desconocido: {simbolo}")
    if tf not in almacen.TIMEFRAMES:
        raise HTTPException(422, f"Timeframe no válido: {tf}. Opciones: {', '.join(almacen.TIMEFRAMES)}")
    disponible = almacen.rango(simbolo)
    if not disponible:
        raise HTTPException(404, f"No hay datos de {simbolo}: ejecuta `trading-replay datos descargar`")

    hasta = hasta or disponible[1] + timedelta(minutes=1)
    desde = desde or hasta - VENTANA_POR_DEFECTO[tf]
    return {
        "simbolo": simbolo,
        "tf": tf,
        "inicio_datos": disponible[0].isoformat(),
        "velas": almacen.consultar(simbolo, tf, desde, hasta),
    }


# Se monta al final para que no tape las rutas de /api.
app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
