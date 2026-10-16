"""Reglas de un reto de prop firm (spec 006). Lógica pura: no toca disco, motor ni HTTP.

Los importes son dólares de balance. El "balance en vivo" es el balance más el PnL abierto.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime

from trading_replay.operativa.contratos import CONTRATOS
from trading_replay.operativa.perfiles import Perfil

EN_CURSO, APROBADO, SUSPENDIDO = "en_curso", "aprobado", "suspendido"
PERDIDA_MAXIMA, LIMITE_DIARIO, HORA_CIERRE = "perdida_maxima", "limite_diario", "hora_cierre"


def dinero(x: float) -> str:
    """1234.5 → '1.234,50 $'."""
    texto = f"{abs(x):,.2f}".replace(",", " ").replace(".", ",").replace(" ", ".")
    return f"{'−' if x < 0 else ''}{texto} $"


@dataclass
class EstadoReto:
    cuenta: int
    perfil: str
    intento: int = 1
    estado: str = EN_CURSO
    motivo: str | None = None
    fin: datetime | None = None  # instante de mercado en que se aprobó o se suspendió
    umbral: float = 0.0  # nivel de la pérdida máxima
    pico: float = 0.0  # balance en vivo más alto (trailing intradía)
    sesion_dia: str | None = None  # sesión de replay del día en curso (RF-4)
    balance_inicio_dia: float = 0.0
    operado: bool = False
    bloqueo: str | None = None  # limite_diario (hasta el siguiente salto) | hora_cierre
    bloqueo_hasta: datetime | None = None


def nuevo(cuenta: int, perfil: Perfil, intento: int = 1) -> EstadoReto:
    inicial = perfil.balance_inicial
    return EstadoReto(
        cuenta, perfil.id, intento, umbral=inicial - perfil.perdida_maxima.importe, pico=inicial, balance_inicio_dia=inicial
    )


# --- Pérdida máxima y límite diario ---


def _subir_umbral(estado: EstadoReto, perfil: Perfil, nivel: float) -> None:
    """Sube el umbral hasta `nivel` − pérdida máxima, sin pasar del tope. Nunca baja."""
    nuevo_umbral = nivel - perfil.perdida_maxima.importe
    tope = perfil.tope_umbral
    if tope is not None:
        nuevo_umbral = min(nuevo_umbral, tope)
    estado.umbral = round(max(estado.umbral, nuevo_umbral), 2)


def actualizar_pico(estado: EstadoReto, perfil: Perfil, balance_vivo: float) -> None:
    """Trailing intradía: el umbral sigue al balance en vivo más alto (RF-6)."""
    if perfil.perdida_maxima.tipo != "trailing_intradia":
        return
    estado.pico = round(max(estado.pico, balance_vivo), 2)
    _subir_umbral(estado, perfil, estado.pico)


def nivel_liquidacion(estado: EstadoReto, perfil: Perfil) -> tuple[float, str]:
    """Balance en vivo al que se cierra todo y la regla que manda: la del nivel más alto.
    Con el día ya pausado por el límite diario, solo queda la pérdida máxima."""
    if perfil.limite_diario and estado.bloqueo != LIMITE_DIARIO:
        diario = round(estado.balance_inicio_dia - perfil.limite_diario.importe, 2)
        if diario > estado.umbral:
            return diario, LIMITE_DIARIO
    return estado.umbral, PERDIDA_MAXIMA


def precio_ruptura(nivel: float, constante: float, pendiente: float) -> int | None:
    """Primer BID (en ticks) con el que el balance en vivo `constante + pendiente × bid` llega a `nivel`.

    Con la posición larga (pendiente positiva) se rompe al bajar: el tick de debajo del punto exacto.
    Con la corta, al subir: el de encima. None si la posición no depende del precio (cubierta).
    """
    if not pendiente:
        return None
    exacto = (nivel - constante) / pendiente
    # El redondeo de coma flotante puede dejar 99.99999 en vez de 100: se corrige antes.
    exacto = round(exacto, 6)
    return math.floor(exacto) if pendiente > 0 else math.ceil(exacto)


def romper(estado: EstadoReto, perfil: Perfil, regla: str, balance: float, instante: datetime) -> dict:
    """Aplica la ruptura de `regla` y devuelve el evento para el frontend (RF-7, RF-8)."""
    if regla == PERDIDA_MAXIMA:
        motivo = f"Pérdida máxima: el balance llegó a {dinero(estado.umbral)}"
    else:
        motivo = f"Límite diario: {dinero(-perfil.limite_diario.importe)} en el día"
    if regla == LIMITE_DIARIO and perfil.limite_diario.efecto == "pausa":
        estado.bloqueo = LIMITE_DIARIO
        return {"tipo": "pausa", "mensaje": f"{motivo}. Se ha cerrado todo; podrás operar en el siguiente salto."}
    estado.estado, estado.motivo, estado.fin = SUSPENDIDO, motivo, instante
    return {"tipo": "suspendido", "mensaje": motivo, "balance": balance}


# --- Días ---


@dataclass
class Dia:
    sesion: str
    pnl: float  # neto, con comisiones
    en_curso: bool = False


@dataclass
class Progreso:
    beneficio: float
    mejor_dia: float
    objetivo_efectivo: float
    falta: float
    dias: int
    dias_validos: int
    faltan_dias: int
    aprobaria: bool
    validos: list[bool] = field(default_factory=list)


def objetivo_efectivo(perfil: Perfil, mejor_dia: float) -> float:
    """Con consistencia P, el beneficio total tiene que ser al menos mejor día ÷ P (RF-9)."""
    objetivo = perfil.objetivo
    if perfil.consistencia and mejor_dia > 0:
        objetivo = max(objetivo, mejor_dia / perfil.consistencia)
    return round(objetivo, 2)


def dia_valido(perfil: Perfil, pnl: float) -> bool:
    minimo = perfil.beneficio_minimo_dia
    return pnl >= minimo if minimo is not None else True


def progreso(perfil: Perfil, balance: float, dias: list[Dia]) -> Progreso:
    beneficio = round(balance - perfil.balance_inicial, 2)
    mejor = max((d.pnl for d in dias), default=0.0)
    mejor = max(mejor, 0.0)
    objetivo = objetivo_efectivo(perfil, mejor)
    validos = [dia_valido(perfil, d.pnl) for d in dias]
    n_validos = sum(validos)
    faltan_dias = max(0, perfil.dias_minimos - n_validos)
    falta = round(max(0.0, objetivo - beneficio), 2)
    return Progreso(beneficio, round(mejor, 2), objetivo, falta, len(dias), n_validos, faltan_dias, not falta and not faltan_dias, validos)


def cerrar_dia(estado: EstadoReto, perfil: Perfil, balance: float, dias: list[Dia], instante: datetime | None) -> dict | None:
    """Cierra el día en curso: trailing al cierre y, si se cumple todo, aprobado (RF-13)."""
    if perfil.perdida_maxima.tipo == "trailing_cierre":
        _subir_umbral(estado, perfil, balance)
    if estado.estado != EN_CURSO:
        return None
    hecho = progreso(perfil, balance, dias)
    if not hecho.aprobaria:
        return None
    estado.estado, estado.fin = APROBADO, instante
    estado.motivo = f"Objetivo de {dinero(hecho.objetivo_efectivo)} alcanzado en {hecho.dias} días"
    return {
        "tipo": "aprobado",
        "mensaje": estado.motivo,
        "perfil": perfil.titulo,
        "beneficio": hecho.beneficio,
        "dias": hecho.dias,
        "mejor_dia": hecho.mejor_dia,
    }


# --- Contratos ---


def contratos_en_uso(posiciones: dict[str, int]) -> float:
    """Suma de |posición| en minis; un micro cuenta 0,1 (RF-11)."""
    return round(sum(abs(c) * (0.1 if CONTRATOS[k].micro else 1) for k, c in posiciones.items()), 1)
