import lzma
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from trading_replay.historico.dukascopy import REGISTRO, ruta_crudo

ET = ZoneInfo("America/New_York")


def bi5(filas: list[tuple[int, float, float, float, float, float]], unidad: float = 0.001) -> bytes:
    """Construye un .bi5 a partir de (segundos desde 00:00 UTC, open, high, low, close, volumen)."""
    registros = np.array(
        [
            (seg, round(o / unidad), round(c / unidad), round(l / unidad), round(h / unidad), v)
            for seg, o, h, l, c, v in filas
        ],
        dtype=REGISTRO,
    )
    return lzma.compress(registros.tobytes())


@pytest.fixture
def datos(tmp_path, monkeypatch):
    """Carpeta de datos temporal y una función para añadir velas de 1m en hora ET."""
    monkeypatch.setenv("TRADING_REPLAY_DATOS", str(tmp_path))
    por_dia: dict[tuple[str, date], list] = {}

    def anadir(simbolo: str, hora_et: datetime, o: float, h: float, l: float, c: float, v: float = 1.0):
        utc = hora_et.replace(tzinfo=ET).astimezone(timezone.utc)
        dia = utc.date()
        segundos = int((utc - datetime.combine(dia, datetime.min.time(), timezone.utc)).total_seconds())
        por_dia.setdefault((simbolo, dia), []).append((segundos, o, h, l, c, v))
        ruta = ruta_crudo(simbolo, dia)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_bytes(bi5(sorted(por_dia[(simbolo, dia)])))

    def serie(simbolo: str, inicio_et: datetime, minutos: int, precio: float = 100.0):
        """Velas consecutivas de 1m que suben 1 punto por minuto."""
        for i in range(minutos):
            p = precio + i
            anadir(simbolo, inicio_et + timedelta(minutes=i), p, p + 0.5, p - 0.5, p + 0.25)

    anadir.serie = serie
    return anadir
