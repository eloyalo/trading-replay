"""Parquet de velas de 1m por instrumento y consultas agregadas por timeframe.

Las horas se guardan en UTC. Las consultas trabajan en hora de Nueva York (ET),
y el día de trading empieza a las 18:00 ET de la víspera, como en el CME.
"""

import os
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb
import numpy as np
import pyarrow as pa

from trading_replay.config import ZONA_MERCADO, Instrumento, carpeta_datos
from trading_replay.historico.dukascopy import decodificar

# Minutos de cada timeframe. 4h y 1D se alinean al día de trading (18:00 ET).
TIMEFRAMES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1D": 1440}
DESFASE_DIA = timedelta(hours=6)  # 18:00 ET + 6 h = 00:00

SESION_SQL = """
    CASE
        WHEN m >= 18 * 60 OR m < 3 * 60 THEN 'asia'
        WHEN m < 9 * 60 + 30 THEN 'londres'
        WHEN m < 17 * 60 THEN 'nueva_york'
    END
"""


def ruta_parquet(simbolo: str) -> Path:
    return carpeta_datos() / "velas" / f"{simbolo}.parquet"


def conexion() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    return con


def construir(instrumento: Instrumento) -> int:
    """Genera el Parquet de 1m a partir de los crudos. Devuelve el número de velas."""
    carpeta = carpeta_datos() / "crudo" / instrumento.simbolo
    partes = []
    for archivo in sorted(carpeta.glob("*/*.bi5")):
        dia = date.fromisoformat(archivo.stem)
        registros = decodificar(archivo.read_bytes(), dia)
        registros = registros[registros["volume"] > 0]  # minutos sin cotizaciones: mercado cerrado
        if len(registros):
            inicio = np.datetime64(dia, "s")
            partes.append((inicio + registros["seg"].astype("timedelta64[s]"), registros))

    if not partes:
        return 0
    unidad = instrumento.unidad_precio
    tabla = pa.table(
        {
            "ts": pa.array(np.concatenate([ts for ts, _ in partes]), type=pa.timestamp("s", tz="UTC")),
            **{
                col: np.concatenate([r[col] for _, r in partes]).astype("f8") * unidad
                for col in ("open", "high", "low", "close")
            },
            "volume": np.concatenate([r["volume"] for _, r in partes]).astype("f8"),
        }
    )

    destino = ruta_parquet(instrumento.simbolo)
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_suffix(".tmp")
    con = conexion()
    con.register("crudas", tabla)
    con.execute(
        f"""
        COPY (
            SELECT ts, round(open, 3) AS open, round(high, 3) AS high, round(low, 3) AS low,
                   round(close, 3) AS close, volume, {SESION_SQL} AS sesion
            FROM (
                SELECT *, hour(timezone('{ZONA_MERCADO}', ts)) * 60 + minute(timezone('{ZONA_MERCADO}', ts)) AS m
                FROM crudas
            )
            ORDER BY ts
        ) TO '{temporal}' (FORMAT parquet, COMPRESSION zstd)
        """
    )
    os.replace(temporal, destino)
    return tabla.num_rows


def inicio_dia_trading(momento: datetime) -> datetime:
    """Inicio (18:00 ET) del día de trading al que pertenece `momento` (hora ET sin zona)."""
    dia = (momento + DESFASE_DIA).date()
    return datetime.combine(dia, datetime.min.time()) - DESFASE_DIA


def rango(simbolo: str) -> tuple[datetime, datetime] | None:
    """Primera y última vela disponibles, en hora ET."""
    ruta = ruta_parquet(simbolo)
    if not ruta.exists():
        return None
    return conexion().execute(
        f"SELECT min(timezone('{ZONA_MERCADO}', ts)), max(timezone('{ZONA_MERCADO}', ts)) FROM '{ruta}'"
    ).fetchone()


def consultar(simbolo: str, tf: str, desde: datetime, hasta: datetime) -> list[dict]:
    """Velas de `tf` cuyo inicio está en [desde, hasta), con horas ET sin zona.

    `time` es la hora ET expresada como segundos Unix, como si fuera UTC: es lo que
    Lightweight Charts necesita para mostrar la hora de Nueva York.
    """
    minutos = TIMEFRAMES[tf]
    if minutos >= 240:
        desde = inicio_dia_trading(desde)
        cubeta = f"time_bucket(INTERVAL {minutos} MINUTE, et + INTERVAL 6 HOUR) - INTERVAL 6 HOUR"
        if tf == "1D":
            # La vela diaria se etiqueta con la fecha del día de trading.
            cubeta = "date_trunc('day', et + INTERVAL 6 HOUR)"
    else:
        cubeta = f"time_bucket(INTERVAL {minutos} MINUTE, et)"

    filas = conexion().execute(
        f"""
        WITH v AS (
            SELECT timezone('{ZONA_MERCADO}', ts) AS et, open, high, low, close, volume
            FROM '{ruta_parquet(simbolo)}'
            WHERE ts >= timezone('{ZONA_MERCADO}', $desde::TIMESTAMP)
              AND ts < timezone('{ZONA_MERCADO}', $hasta::TIMESTAMP)
        )
        SELECT epoch({cubeta})::BIGINT AS t,
               arg_min(open, et), max(high), min(low), arg_max(close, et), sum(volume)
        FROM v
        GROUP BY t
        ORDER BY t
        """,
        {"desde": desde, "hasta": hasta},
    ).fetchall()
    return [
        {"time": t, "open": o, "high": h, "low": l, "close": c, "volume": round(vol, 4)}
        for t, o, h, l, c, vol in filas
    ]
