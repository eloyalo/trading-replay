"""Informe de huecos: tramos sin velas en horas en que el mercado debería estar abierto."""

import csv
from datetime import datetime, time, timedelta

from trading_replay.config import ZONA_MERCADO, Instrumento, carpeta_datos
from trading_replay.historico.almacen import conexion, ruta_parquet

REAPERTURA = time(18, 0)
UN_MINUTO = timedelta(minutes=1)


def mercado_abierto(momento: datetime, cierre_diario: time) -> bool:
    """Horario del CFD en hora ET: de domingo 18:00 a viernes `cierre_diario`, con pausa diaria."""
    dia, hora = momento.weekday(), momento.time()
    if dia == 5:  # sábado
        return False
    if dia == 6:  # domingo
        return hora >= REAPERTURA
    if dia == 4 and hora >= cierre_diario:  # viernes
        return False
    return not (cierre_diario <= hora < REAPERTURA)


def minutos_abiertos(desde: datetime, hasta: datetime, cierre_diario: time) -> int:
    """Minutos de [desde, hasta) en que el mercado debería estar abierto."""
    total, momento = 0, desde
    while momento < hasta:
        total += mercado_abierto(momento, cierre_diario)
        momento += UN_MINUTO
    return total


def buscar(instrumento: Instrumento, umbral_minutos: int) -> list[tuple[datetime, datetime, int]]:
    """Huecos con más de `umbral_minutos` de mercado abierto sin velas: (desde, hasta, minutos)."""
    horas = [
        fila[0]
        for fila in conexion().execute(
            f"SELECT timezone('{ZONA_MERCADO}', ts) FROM '{ruta_parquet(instrumento.simbolo)}' ORDER BY ts"
        ).fetchall()
    ]
    huecos = []
    for anterior, siguiente in zip(horas, horas[1:]):
        if siguiente - anterior <= timedelta(minutes=umbral_minutos + 1):
            continue
        desde = anterior + UN_MINUTO
        minutos = minutos_abiertos(desde, siguiente, instrumento.cierre_diario)
        if minutos > umbral_minutos:
            huecos.append((desde, siguiente, minutos))
    return huecos


def generar_informe(instrumento: Instrumento, umbral_minutos: int) -> list[tuple[datetime, datetime, int]]:
    huecos = buscar(instrumento, umbral_minutos)
    destino = carpeta_datos() / "huecos" / f"{instrumento.simbolo}.csv"
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("w", newline="") as archivo:
        escritor = csv.writer(archivo)
        escritor.writerow(["desde_et", "hasta_et", "minutos_abiertos_sin_datos"])
        for desde, hasta, minutos in huecos:
            escritor.writerow([desde.isoformat(sep=" "), hasta.isoformat(sep=" "), minutos])
    return huecos
