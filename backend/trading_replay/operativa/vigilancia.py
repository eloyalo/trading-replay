"""Reglas de un reto aplicadas a un motor de órdenes, minuto a minuto (spec 006, y spec 009 para el backtest).

Lo usan el replay (`servicio.py`, con la cuenta activa) y el backtest (`backtest/reto_bt.py`), para que las
reglas sean las mismas en los dos. Cada función recibe el estado del reto, su perfil y el motor, y devuelve el
evento si ha pasado algo (o None). Quien la llama decide qué hacer con el evento.
"""

from datetime import datetime, time

from trading_replay.operativa import reto
from trading_replay.operativa.contratos import CONTRATOS
from trading_replay.operativa.motor import Minuto, Motor, Orden, OrdenNoValida
from trading_replay.operativa.perfiles import Perfil
from trading_replay.operativa.reto import EN_CURSO, HORA_CIERRE, LIMITE_DIARIO, EstadoReto

REAPERTURA = time(18, 0)  # ET: después de la pausa diaria se puede volver a operar (spec 006, RF-12)


def validar_orden(estado: EstadoReto, perfil: Perfil, m: Motor, orden: Orden, instante: datetime) -> None:
    """Lanza `OrdenNoValida` si el reto no admite la orden (RF-11 y RF-12 de la spec 006)."""
    if estado.estado != EN_CURSO:
        raise OrdenNoValida(f"El reto está {'aprobado' if estado.estado == reto.APROBADO else 'suspendido'}: {estado.motivo}")
    if estado.bloqueo == LIMITE_DIARIO:
        raise OrdenNoValida("Límite diario alcanzado: podrás operar en el siguiente salto")
    cerrado = estado.bloqueo == HORA_CIERRE and estado.bloqueo_hasta and instante < estado.bloqueo_hasta
    if cerrado or (perfil.hora_cierre and perfil.hora_cierre <= instante.time() < REAPERTURA):
        raise OrdenNoValida(f"Fuera del horario del reto: se puede operar desde las {REAPERTURA:%H:%M}")
    if perfil.contratos_maximos and orden.papel == "entrada":
        # Como si se ejecutaran todas las entradas pendientes y la nueva (RF-11).
        posiciones = {c: p.cantidad for c, p in m.posiciones.items()}
        for o in [*m.ordenes, orden]:
            if o.papel == "entrada" and o.estado == "pendiente":
                posiciones[o.contrato] = posiciones.get(o.contrato, 0) + o.lado * o.cantidad
        if reto.contratos_en_uso(posiciones) > perfil.contratos_maximos:
            maximo = f"{perfil.contratos_maximos:g}"
            raise OrdenNoValida(f"El reto permite {maximo} contratos como mucho (o {maximo}0 micros)")


def recta_balance(m: Motor, simbolo: str) -> tuple[float, float]:
    """Balance en vivo como recta en el BID de `simbolo`: los demás instrumentos, quietos en su último precio."""
    constante, pendiente = m.balance, 0.0
    for posicion in m.posiciones.values():
        if not posicion.cantidad:
            continue
        if CONTRATOS[posicion.contrato].simbolo == simbolo:
            c, k = m.recta_pnl(posicion)
            constante, pendiente = constante + c, pendiente + k
        else:
            constante += m.pnl_abierto(posicion)
    return constante, pendiente


def tick_de(simbolo: str) -> float:
    return next(c.tick for c in CONTRATOS.values() if c.simbolo == simbolo)


def liquidar_a(m: Motor, simbolo: str, minuto: Minuto, bid: int) -> None:
    """Cierra todo con el BID de `simbolo` en `bid` ticks, dentro de `minuto`; los demás, a su último precio."""
    anterior = m.ultimo.get(simbolo)
    precio = bid * tick_de(simbolo)
    m.ultimo[simbolo] = Minuto(minuto.inicio, minuto.open, minuto.high, minuto.low, precio)
    m.liquidar(minuto.inicio)
    if anterior is not None:
        m.ultimo[simbolo] = anterior


def hora_de_cierre(estado: EstadoReto, perfil: Perfil, m: Motor, simbolo: str, minuto: Minuto) -> dict | None:
    """A la hora de cierre del perfil se cierra todo en la apertura del minuto (RF-12)."""
    if not perfil.hora_cierre or estado.estado != EN_CURSO:
        return None
    if not perfil.hora_cierre <= minuto.inicio.time() < REAPERTURA or not m.hay_exposicion():
        return None
    liquidar_a(m, simbolo, minuto, round(minuto.open / tick_de(simbolo)))
    estado.bloqueo = HORA_CIERRE
    estado.bloqueo_hasta = datetime.combine(minuto.inicio.date(), REAPERTURA)
    hora = f"{perfil.hora_cierre:%H:%M}"
    return {"tipo": "hora_cierre", "mensaje": f"Hora de cierre del reto ({hora} ET): se ha cerrado todo. Se puede volver a operar a las 18:00."}


def vigilar(estado: EstadoReto, perfil: Perfil, m: Motor, simbolo: str, minuto: Minuto) -> dict | None:
    """Pérdida máxima y límite diario en el peor precio del minuto; después, el pico con el mejor (RF-6 a RF-8)."""
    if estado.estado != EN_CURSO:
        return None
    nivel, regla = reto.nivel_liquidacion(estado, perfil)
    constante, pendiente = recta_balance(m, simbolo)
    tick = tick_de(simbolo)
    bajo, alto = round(minuto.low / tick), round(minuto.high / tick)
    peor, mejor = (bajo, alto) if pendiente >= 0 else (alto, bajo)
    if constante + pendiente * peor <= nivel:
        ruptura = reto.precio_ruptura(nivel, constante, pendiente)
        if ruptura is not None:
            apertura = round(minuto.open / tick)
            if pendiente > 0:
                bid = apertura if apertura <= ruptura else max(ruptura, bajo)
            else:
                bid = apertura if apertura >= ruptura else min(ruptura, alto)
            liquidar_a(m, simbolo, minuto, bid)
        return reto.romper(estado, perfil, regla, m.balance, minuto.inicio)
    reto.actualizar_pico(estado, perfil, constante + pendiente * mejor)
    return None


def vigilar_ahora(estado: EstadoReto, perfil: Perfil, m: Motor, instante: datetime) -> dict | None:
    """Tras una ejecución en el acto: comprueba las reglas con el precio actual."""
    vivo = m.balance + sum(m.pnl_abierto(p) for p in m.posiciones.values() if p.cantidad)
    nivel, regla = reto.nivel_liquidacion(estado, perfil)
    if vivo <= nivel:
        m.liquidar(instante)
        return reto.romper(estado, perfil, regla, m.balance, instante)
    reto.actualizar_pico(estado, perfil, vivo)
    return None
