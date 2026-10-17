"""El backtest en marcha (spec 008, RF-7): corre en un hilo, con progreso y cancelación.

Solo hay uno a la vez. Con el GIL, la API sigue respondiendo mientras tanto, algo más lenta. "Cancelar"
no puede cortar un bucle infinito dentro de la estrategia: en ese caso hay que reiniciar el servidor.
"""

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from trading_replay.backtest import almacen_bt, ejecutor, metricas
from trading_replay.backtest.cargador import ErrorEstrategia, InfoEstrategia
from trading_replay.operativa.motor import Costes
from trading_replay.operativa.perfiles import Perfil


class EnMarcha(Exception):
    """Ya hay un backtest en marcha."""


@dataclass
class Trabajo:
    estrategia: str
    nombre: str
    simbolo: str
    estado: str = "en_marcha"  # en_marcha | hecho | error | cancelado
    progreso: float = 0.0
    ejecucion: int | None = None  # id en el historial, al terminar
    error: dict | None = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    _cancelar: threading.Event = field(default_factory=threading.Event, repr=False)
    _hilo: threading.Thread | None = field(default=None, repr=False)

    def api(self) -> dict:
        return {
            "id": self.id,
            "estrategia": self.estrategia,
            "nombre": self.nombre,
            "simbolo": self.simbolo,
            "estado": self.estado,
            "progreso": round(self.progreso, 4),
            "ejecucion": self.ejecucion,
            "error": self.error,
        }


_cerrojo = threading.Lock()
_actual: Trabajo | None = None


def actual() -> Trabajo | None:
    return _actual


def en_marcha() -> bool:
    return _actual is not None and _actual.estado == "en_marcha"


def lanzar(
    info: InfoEstrategia, valores: dict, simbolo: str, desde: datetime, hasta: datetime, costes: Costes, perfil: Perfil | None = None
) -> Trabajo:
    """Lanza el backtest en un hilo, con las reglas del reto `perfil` si se da (spec 009). `valores` ya validados
    y `info` sin error de carga."""
    global _actual
    with _cerrojo:
        if en_marcha():
            raise EnMarcha("Ya hay un backtest en marcha")
        trabajo = Trabajo(info.id, info.nombre, simbolo)
        meta = {
            "estrategia": info.id,
            "nombre": info.nombre,
            "huella": info.huella,
            "codigo": info.codigo,
            "parametros": valores,
            "simbolo": simbolo,
            "timeframe": info.clase.timeframe,
            "desde": desde,
            "hasta": hasta,
            "costes": vars(costes),
            "perfil": perfil.id if perfil else None,
        }
        trabajo._hilo = threading.Thread(target=_correr, args=(trabajo, info, meta, costes, perfil), daemon=True, name="backtest")
        _actual = trabajo
        trabajo._hilo.start()
    return trabajo


def _correr(trabajo: Trabajo, info: InfoEstrategia, meta: dict, costes: Costes, perfil: Perfil | None) -> None:
    try:
        resultado = ejecutor.ejecutar(
            info.clase,
            meta["parametros"],
            meta["simbolo"],
            meta["desde"],
            meta["hasta"],
            costes,
            progreso=lambda p: setattr(trabajo, "progreso", p),
            cancelado=trabajo._cancelar.is_set,
            perfil=perfil,
        )
        resumen = metricas.resumen(resultado.operaciones, metricas.meses_entre(meta["desde"], meta["hasta"]))
        reto = None
        if resultado.reto is not None:
            reto = {"titulo": perfil.titulo, **metricas.resumen_reto(resultado.reto.intentos, resultado.reto.rechazadas)}
        trabajo.ejecucion = almacen_bt.guardar(meta, resultado, resumen, reto)
        trabajo.progreso = 1.0
        trabajo.estado = "hecho"
    except ejecutor.Cancelado:
        trabajo.estado = "cancelado"
    except ErrorEstrategia as error:
        trabajo.error = error.api()
        trabajo.estado = "error"
    except Exception as excepcion:  # un fallo inesperado no puede dejar el trabajo "en marcha" para siempre
        trabajo.error = {"mensaje": f"{type(excepcion).__name__}: {excepcion}", "archivo": None, "linea": None, "vela": None}
        trabajo.estado = "error"


def cancelar() -> Trabajo | None:
    trabajo = _actual
    if trabajo is not None and trabajo.estado == "en_marcha":
        trabajo._cancelar.set()
    return trabajo


def esperar(segundos: float | None = None) -> Trabajo | None:
    """Espera a que termine el trabajo actual (para los tests)."""
    trabajo = _actual
    if trabajo is not None and trabajo._hilo is not None:
        trabajo._hilo.join(segundos)
    return trabajo
