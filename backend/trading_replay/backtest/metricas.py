"""Métricas de un backtest (spec 008, RF-10 a RF-12): funciones puras sobre la lista de operaciones.

Una operación es ganadora o perdedora según su PnL neto (con comisiones). La curva, el drawdown y las
rachas siguen el orden de cierre de las operaciones.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from trading_replay.backtest.ejecutor import OperacionBT
from trading_replay.backtest.estrategia import DIAS
from trading_replay.historico import almacen

DESFASE_DIA = timedelta(hours=6)  # 18:00 ET + 6 h = 00:00 del día de trading
DIAS_POR_MES = 365.25 / 12
SESIONES = ("asia", "londres", "nueva_york")
LADOS = {"largos": 1, "cortos": -1}


def sesion_de(momento: datetime) -> str | None:
    """Sesión de una hora ET, con los horarios del botón de momento aleatorio."""
    return almacen.sesion(momento.hour * 60 + momento.minute)


def dia_de(momento: datetime) -> str:
    """Día de la semana del día de trading: el domingo a las 19:00 ET ya cuenta como lunes."""
    return DIAS[(momento + DESFASE_DIA).weekday()]


def _drawdown(valores: Iterable[float]) -> float:
    """Mayor caída desde un máximo de la suma acumulada (empezando en 0), en positivo."""
    acumulado = pico = peor = 0.0
    for valor in valores:
        acumulado += valor
        pico = max(pico, acumulado)
        peor = max(peor, pico - acumulado)
    return round(peor, 2)


def _racha(ops: list[OperacionBT], ganadora: bool) -> int:
    mejor = actual = 0
    for op in ops:
        actual = actual + 1 if (op.pnl_neto > 0 if ganadora else op.pnl_neto < 0) else 0
        mejor = max(mejor, actual)
    return mejor


def _media(valores: list[float]) -> float | None:
    return sum(valores) / len(valores) if valores else None


def _redondear(valor: float | None, decimales: int = 2) -> float | None:
    return round(valor, decimales) if valor is not None else None


def profit_factor(ops: list[OperacionBT]) -> float | None:
    """Ganancias netas ÷ pérdidas netas en valor absoluto. None si no hay pérdidas (la interfaz pone ∞)."""
    ganado = sum(op.pnl_neto for op in ops if op.pnl_neto > 0)
    perdido = -sum(op.pnl_neto for op in ops if op.pnl_neto < 0)
    return round(ganado / perdido, 3) if perdido else None


def resumen(ops: list[OperacionBT], meses: float | None = None) -> dict:
    """Todas las métricas de RF-10. `meses` es lo que dura el periodo analizado, para las operaciones
    por mes; sin él, va de la primera entrada a la última salida."""
    n = len(ops)
    ganadoras = [op for op in ops if op.pnl_neto > 0]
    perdedoras = [op for op in ops if op.pnl_neto < 0]
    rs = [op.r for op in ops if op.r is not None]
    ganancia_media = _media([op.pnl_neto for op in ganadoras])
    perdida_media = _media([op.pnl_neto for op in perdedoras])
    if meses is None and ops:
        meses = (max(op.cierre for op in ops) - min(op.apertura for op in ops)) / timedelta(days=DIAS_POR_MES)
    duraciones = [(op.cierre - op.apertura) / timedelta(minutes=1) for op in ops]
    return {
        "operaciones": n,
        "ganadoras": len(ganadoras),
        "perdedoras": len(perdedoras),
        "acierto": round(len(ganadoras) / n, 4) if n else None,
        "neto": round(sum(op.pnl_neto for op in ops), 2),
        "bruto": round(sum(op.pnl_bruto for op in ops), 2),
        "comisiones": round(sum(op.comisiones for op in ops), 2),
        "ganancia_media": _redondear(ganancia_media),
        "perdida_media": _redondear(perdida_media),
        "proporcion": _redondear(ganancia_media / -perdida_media if ganancia_media and perdida_media else None, 3),
        "profit_factor": profit_factor(ops),
        "esperanza": _redondear(sum(op.pnl_neto for op in ops) / n if n else None),
        "esperanza_r": _redondear(_media(rs), 3),
        "r_ganadoras": _redondear(_media([op.r for op in ganadoras if op.r is not None]), 3),
        "r_perdedoras": _redondear(_media([op.r for op in perdedoras if op.r is not None]), 3),
        "drawdown": _drawdown(op.pnl_neto for op in ops),
        "drawdown_r": _drawdown(rs),
        "racha_ganadoras": _racha(ops, True),
        "racha_perdedoras": _racha(ops, False),
        "duracion_media": _redondear(_media(duraciones), 1),  # minutos
        "por_mes": round(n / meses, 2) if meses else None,
        "dudosas": sum(op.dudosa for op in ops),
    }


def reducido(ops: list[OperacionBT]) -> dict:
    """Las métricas de cada fila del desglose (RF-11)."""
    n = len(ops)
    rs = [op.r for op in ops if op.r is not None]
    return {
        "operaciones": n,
        "acierto": round(sum(op.pnl_neto > 0 for op in ops) / n, 4) if n else None,
        "neto": round(sum(op.pnl_neto for op in ops), 2),
        "profit_factor": profit_factor(ops),
        "esperanza_r": _redondear(_media(rs), 3),
    }


def segundos_grafico(momento: datetime) -> int:
    """Hora ET como segundos "UTC", como `time` en las velas del gráfico."""
    return int(momento.replace(tzinfo=timezone.utc).timestamp())


def curva(ops: list[OperacionBT]) -> list[dict]:
    """Neto acumulado al cierre de cada operación. Si varias cierran en el mismo minuto, un solo punto."""
    puntos: list[dict] = []
    acumulado = 0.0
    for op in sorted(ops, key=lambda o: o.cierre):
        acumulado = round(acumulado + op.pnl_neto, 2)
        t = segundos_grafico(op.cierre)
        if puntos and puntos[-1]["time"] == t:
            puntos[-1]["value"] = acumulado
        else:
            puntos.append({"time": t, "value": acumulado})
    return puntos


def desglose(ops: list[OperacionBT]) -> dict:
    """Por año, sesión, día de la semana y lado (de la entrada), solo con los grupos que tienen operaciones."""

    def agrupar(clave, orden):
        grupos: dict = {}
        for op in ops:
            grupos.setdefault(clave(op), []).append(op)
        return [{"grupo": g, **reducido(grupos[g])} for g in orden if g in grupos]

    return {
        "anio": agrupar(lambda op: op.apertura.year, sorted({op.apertura.year for op in ops})),
        "sesion": agrupar(lambda op: sesion_de(op.apertura), SESIONES + (None,)),
        "dia": agrupar(lambda op: dia_de(op.apertura), DIAS),
        "lado": agrupar(lambda op: "largos" if op.lado > 0 else "cortos", tuple(LADOS)),
    }


@dataclass
class Filtro:
    """Qué operaciones se miran (RF-12). Vacío = todas."""

    desde: datetime | None = None  # entrada en [desde, hasta)
    hasta: datetime | None = None
    anios: set[int] | None = None
    sesiones: set[str] | None = None
    dias: set[str] | None = None
    lado: str | None = None  # largos | cortos

    def admite(self, op: OperacionBT) -> bool:
        return (
            (self.desde is None or op.apertura >= self.desde)
            and (self.hasta is None or op.apertura < self.hasta)
            and (not self.anios or op.apertura.year in self.anios)
            and (not self.sesiones or sesion_de(op.apertura) in self.sesiones)
            and (not self.dias or dia_de(op.apertura) in self.dias)
            and (self.lado is None or op.lado == LADOS[self.lado])
        )


def filtrar(ops: list[OperacionBT], filtro: Filtro) -> list[OperacionBT]:
    return [op for op in ops if filtro.admite(op)]


def meses_entre(desde: datetime, hasta: datetime) -> float:
    return max((hasta - desde) / timedelta(days=DIAS_POR_MES), 0.0)


def resumen_reto(intentos: list, rechazadas: dict) -> dict:
    """Resumen de un backtest con reto (spec 009, RF-7). `intentos`: los de `RetoBacktest`, terminados o no."""
    aprobados = [i for i in intentos if i.resultado == "aprobado"]
    suspendidos = [i for i in intentos if i.resultado == "suspendido"]
    terminados = len(aprobados) + len(suspendidos)

    def media(valores):
        return round(sum(valores) / len(valores), 2) if valores else None

    def naturales(i):
        return (i.fin - i.inicio) / timedelta(days=1)

    motivos: dict[str, int] = {}
    for i in suspendidos:
        motivo = "Límite diario" if (i.motivo or "").startswith("Límite diario") else "Pérdida máxima"
        motivos[motivo] = motivos.get(motivo, 0) + 1
    return {
        "intentos": len(intentos),
        "aprobados": len(aprobados),
        "suspendidos": len(suspendidos),
        "en_curso": len(intentos) - terminados,
        "aprobacion": round(len(aprobados) / terminados, 4) if terminados else None,
        "dias_hasta_aprobar": media([i.dias for i in aprobados]),
        "dias_hasta_suspender": media([i.dias for i in suspendidos]),
        "naturales_hasta_aprobar": media([naturales(i) for i in aprobados]),
        "naturales_hasta_suspender": media([naturales(i) for i in suspendidos]),
        "motivos_suspension": [{"motivo": m, "intentos": n} for m, n in sorted(motivos.items(), key=lambda x: -x[1])],
        "beneficio_aprobados": media([i.beneficio for i in aprobados]),
        "beneficio_suspendidos": media([i.beneficio for i in suspendidos]),
        "rechazadas": [{"motivo": m, "ordenes": n} for m, n in sorted(rechazadas.items(), key=lambda x: -x[1])],
    }
