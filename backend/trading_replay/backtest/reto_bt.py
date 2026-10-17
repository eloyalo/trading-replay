"""Un reto de prop firm dentro del backtest (spec 009).

Las reglas son las del replay: las de `operativa/reto.py`, vigiladas minuto a minuto con `operativa/vigilancia.py`.
Lo propio del backtest: cada día de trading es un día del reto (RF-3) y los intentos se encadenan (RF-5).
"""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from trading_replay.operativa import reto, vigilancia
from trading_replay.operativa.motor import Minuto, Motor, Orden, OrdenNoValida
from trading_replay.operativa.perfiles import Perfil
from trading_replay.operativa.reto import EN_CURSO, HORA_CIERRE, LIMITE_DIARIO, Dia

FIN_INTENTO = "Fin del intento"
HORA_CIERRE_RETO = "Hora de cierre del reto"


@dataclass
class Intento:
    numero: int
    inicio: datetime  # instante en que empezó
    fin: datetime | None = None  # instante en que se aprobó o se suspendió, o el final de los datos
    resultado: str = EN_CURSO  # en_curso | aprobado | suspendido
    motivo: str | None = None
    dias: int = 0  # días del reto con ejecuciones
    beneficio: float = 0.0
    mejor_dia: float = 0.0
    operaciones: int = 0


def motivo_de(evento: dict) -> str:
    """Motivo de salida de las operaciones que cierra el reto, según el evento."""
    if evento["tipo"] == "hora_cierre":
        return HORA_CIERRE_RETO
    return "Pérdida máxima" if evento["mensaje"].startswith("Pérdida máxima") else "Límite diario"


class RetoBacktest:
    def __init__(self, perfil: Perfil, motor: Motor):
        self.perfil = perfil
        self.motor = motor
        self.intentos: list[Intento] = []
        self.rechazadas: Counter = Counter()  # órdenes que el reto no admitió, por motivo (RF-4)
        self.estado: reto.EstadoReto | None = None
        self.intento: Intento | None = None
        self.dias: list[Dia] = []
        self._fecha_dia: str | None = None

    @property
    def numero(self) -> int | None:
        return self.intento.numero if self.intento else None

    @property
    def en_curso(self) -> bool:
        return self.estado is not None and self.estado.estado == EN_CURSO

    # --- Intentos y días ---

    def empezar(self, instante: datetime) -> None:
        """Intento nuevo: balance inicial del perfil y reglas a cero."""
        numero = len(self.intentos) + 1
        self.estado = reto.nuevo(0, self.perfil, numero)
        self.intento = Intento(numero, instante)
        self.dias = []
        self.motor.balance = self.perfil.balance_inicial

    def empezar_dia(self, fecha: str) -> None:
        estado = self.estado
        estado.balance_inicio_dia, estado.operado = self.motor.balance, False
        estado.bloqueo = estado.bloqueo_hasta = None
        self._fecha_dia = fecha

    def cerrar_dia(self, instante: datetime) -> None:
        """Al acabar un día de trading: si tuvo ejecuciones, cuenta como día del reto, con su trailing al
        cierre y la comprobación de aprobado (spec 006, RF-13)."""
        estado = self.estado
        if estado is None or not estado.operado:
            return
        self.dias.append(Dia(self._fecha_dia, round(self.motor.balance - estado.balance_inicio_dia, 2)))
        reto.cerrar_dia(estado, self.perfil, self.motor.balance, self.dias, instante)

    def terminar(self, instante: datetime) -> Intento:
        """Apunta el intento en curso con su resultado. Si sigue en curso, es que se han acabado los datos."""
        intento, estado = self.intento, self.estado
        intento.resultado, intento.motivo = estado.estado, estado.motivo
        intento.fin = estado.fin or instante
        intento.dias = len(self.dias)
        intento.beneficio = round(self.motor.balance - self.perfil.balance_inicial, 2)
        intento.mejor_dia = round(max((d.pnl for d in self.dias), default=0.0), 2)
        self.intentos.append(intento)
        self.intento = None
        return intento

    def operado(self) -> None:
        if self.estado is not None:
            self.estado.operado = True

    # --- Reglas ---

    def validar(self, orden: Orden, instante: datetime) -> bool:
        """Si el reto admite la orden. Si no, cuenta el motivo (RF-4)."""
        try:
            vigilancia.validar_orden(self.estado, self.perfil, self.motor, orden, instante)
        except OrdenNoValida:
            self.rechazadas[self._motivo_rechazo(orden, instante)] += 1
            return False
        return True

    def _motivo_rechazo(self, orden: Orden, instante: datetime) -> str:
        estado = self.estado
        if estado.estado != EN_CURSO:
            return "Intento terminado (el siguiente empieza al día siguiente)"
        if estado.bloqueo == LIMITE_DIARIO:
            return "Límite diario alcanzado"
        if estado.bloqueo == HORA_CIERRE or (self.perfil.hora_cierre and self.perfil.hora_cierre <= instante.time() < vigilancia.REAPERTURA):
            return "Fuera del horario del reto"
        return "Contratos máximos"

    def antes_del_minuto(self, simbolo: str, minuto: Minuto) -> str | None:
        """Hora de cierre. Devuelve el motivo si ha cerrado todo."""
        if not self.en_curso:
            return None
        evento = vigilancia.hora_de_cierre(self.estado, self.perfil, self.motor, simbolo, minuto)
        return motivo_de(evento) if evento else None

    def despues_del_minuto(self, simbolo: str, minuto: Minuto) -> str | None:
        """Pérdida máxima y límite diario con el peor precio del minuto. Devuelve el motivo si ha roto una regla."""
        if not self.en_curso:
            return None
        evento = vigilancia.vigilar(self.estado, self.perfil, self.motor, simbolo, minuto)
        return motivo_de(evento) if evento else None

    def tras_ejecucion(self, instante: datetime) -> str | None:
        """Tras una ejecución en el acto (una orden a mercado al cierre de una vela)."""
        if not self.en_curso:
            return None
        evento = vigilancia.vigilar_ahora(self.estado, self.perfil, self.motor, instante)
        return motivo_de(evento) if evento else None
