"""Lo que comparten las estrategias con muchas variantes (spec 012): sesión y horario, lados, límites de
operaciones y gestión de la posición (tramos con parcial, break-even, trailing y cierre forzoso).

Una estrategia suma los parámetros de aquí a los suyos y se apoya en una `Operativa`:

    parametros = {**parametros_sesion(), **parametros_operativa(), **parametros_gestion(), ...}

    def al_empezar(self):
        self.op = Operativa(self)

    def al_cerrar_vela(self, vela):
        self.op.gestionar(vela)                   # primero lo que ya está abierto
        if self.op.puede_abrir(lado):
            self.op.entrar(lado, stop, [(objetivo, 1.0)], motivo="...")
"""

from dataclasses import dataclass, field

from trading_replay.backtest.estrategia import Estrategia, Parametro, ParametroNoValido
from trading_replay.operativa.motor import OrdenNoValida

GRUPO_SESION = "Sesión y horario"
GRUPO_OPERATIVA = "Operativa"
GRUPO_GESTION = "Gestión de la posición"

LADOS = ("ambos", "solo largos", "solo cortos")
TRAILING = ("no", "minimos", "ema")


def parametros_sesion() -> dict[str, Parametro]:
    return {
        "sesion_asia": Parametro(False, "Operar en Asia (18:00–3:00)", grupo=GRUPO_SESION),
        "sesion_londres": Parametro(False, "Operar en Londres (3:00–9:30)", grupo=GRUPO_SESION),
        "sesion_nueva_york": Parametro(True, "Operar en Nueva York (9:30–17:00)", grupo=GRUPO_SESION),
        "ventana_desde": Parametro("", "Ventana desde (HH:MM, vacío = usar las sesiones)", grupo=GRUPO_SESION),
        "ventana_hasta": Parametro("", "Ventana hasta (HH:MM)", grupo=GRUPO_SESION),
        "cerrar_fin_sesion": Parametro(False, "Cerrar al acabar la sesión o la ventana", grupo=GRUPO_SESION),
        "hora_cierre": Parametro("16:00", "Cierre forzoso (HH:MM, vacío = sin cierre)", grupo=GRUPO_SESION),
    }


def parametros_operativa(max_operaciones_dia: int = 3) -> dict[str, Parametro]:
    return {
        "lados": Parametro("ambos", "Lados", opciones=list(LADOS), grupo=GRUPO_OPERATIVA),
        "contratos": Parametro(1, "Contratos", minimo=1, maximo=100, grupo=GRUPO_OPERATIVA),
        "micro": Parametro(False, "Operar el micro (MNQ, MES, MGC)", grupo=GRUPO_OPERATIVA),
        "max_operaciones_dia": Parametro(
            max_operaciones_dia, "Máximo de operaciones al día (0 = sin límite)", minimo=0, maximo=100, grupo=GRUPO_OPERATIVA
        ),
        "max_seguidas_sentido": Parametro(0, "Máximo de seguidas en el mismo sentido (0 = sin límite)", minimo=0, maximo=100, grupo=GRUPO_OPERATIVA),
    }


def parametros_gestion() -> dict[str, Parametro]:
    return {
        "be_tras_parcial": Parametro(True, "Stop a break-even tras la toma parcial", grupo=GRUPO_GESTION),
        "be_r": Parametro(0.0, "Stop a break-even al llegar a N R (0 = no)", minimo=0, maximo=20, paso=0.25, grupo=GRUPO_GESTION),
        "trailing": Parametro("no", "Trailing del stop", opciones=list(TRAILING), grupo=GRUPO_GESTION),
        "trailing_velas": Parametro(5, "Trailing por mínimos/máximos de N velas", minimo=1, maximo=100, grupo=GRUPO_GESTION),
        "trailing_ema": Parametro(20, "Trailing por EMA de N periodos", minimo=2, maximo=500, grupo=GRUPO_GESTION),
        "trailing_tras_parcial": Parametro(True, "El trailing empieza tras la toma parcial", grupo=GRUPO_GESTION),
        "trailing_margen_ticks": Parametro(2, "Margen del trailing (ticks)", minimo=0, maximo=500, grupo=GRUPO_GESTION),
    }


def _hora(texto: str, nombre: str) -> str:
    texto = texto.strip()
    try:
        horas, minutos = texto.split(":")
        if len(horas) != 2 or len(minutos) != 2 or not (0 <= int(horas) < 24 and 0 <= int(minutos) < 60):
            raise ValueError
    except ValueError:
        raise ParametroNoValido(f"«{nombre}» tiene que ser una hora HH:MM, por ejemplo 09:30") from None
    return texto


@dataclass
class _Plan:
    """La operación en curso: lo que hay que hacer cuando se abra y mientras dure."""

    lado: int
    stop: float
    tramos: list[tuple[float | None, int]]  # (precio, contratos); el último, si tiene precio, es el TP
    contratos: int
    confirmado: bool = False  # la posición ya se ha abierto
    riesgo: float = 0.0
    entrada: float = 0.0
    sl_actual: float = 0.0
    break_even: bool = False
    sin_parcial: bool = False  # entrada escalonada: nada que esperar de una toma parcial
    avisos: list = field(default_factory=list)


class Operativa:
    """Sesión, lados, límites y gestión de la posición de una estrategia."""

    def __init__(self, estrategia: Estrategia):
        self.e = estrategia
        self.p = estrategia.p
        p = self.p
        self.cierre = _hora(p.hora_cierre, "Cierre forzoso") if p.hora_cierre.strip() else None
        desde, hasta = p.ventana_desde.strip(), p.ventana_hasta.strip()
        if bool(desde) != bool(hasta):
            raise ParametroNoValido("La ventana horaria necesita las dos horas, «desde» y «hasta», o ninguna")
        self.ventana = (_hora(desde, "Ventana desde"), _hora(hasta, "Ventana hasta")) if desde else None
        self.sesiones = {"asia": p.sesion_asia, "londres": p.sesion_londres, "nueva_york": p.sesion_nueva_york}
        self.plan: _Plan | None = None
        self._fecha = None
        self._del_dia = 0
        self._seguidas = 0
        self._ultimo_lado = 0

    # --- Lo que permite abrir ---

    def en_horario(self) -> bool:
        """Si la hora de la vela que acaba de cerrar cae en la ventana, o en una sesión elegida."""
        if self.ventana:
            return self.e.entre(*self.ventana)
        return bool(self.sesiones.get(self.e.sesion))

    def pasada_la_hora_de_cierre(self) -> bool:
        if self.cierre is None:
            return False
        hora = self.e.hora
        return self.cierre <= hora < "18:00" if self.cierre < "18:00" else hora >= self.cierre

    def puede_abrir(self, lado: int) -> bool:
        """Si ahora se puede abrir una operación de ese lado (1 largo, -1 corto)."""
        p, e = self.p, self.e
        if (lado > 0 and p.lados == "solo cortos") or (lado < 0 and p.lados == "solo largos"):
            return False
        if self.plan is not None or e.posicion or any(o.papel == "entrada" for o in e.ordenes):
            return False
        if not self.en_horario() or self.pasada_la_hora_de_cierre():
            return False
        if e.fecha != self._fecha:
            self._fecha, self._del_dia = e.fecha, 0
        if p.max_operaciones_dia and self._del_dia >= p.max_operaciones_dia:
            return False
        if p.max_seguidas_sentido and lado == self._ultimo_lado and self._seguidas >= p.max_seguidas_sentido:
            return False
        return True

    # --- Entrar ---

    def entrar(
        self,
        lado: int,
        stop: float,
        objetivos: list[tuple[float | None, float]],
        tipo: str = "mercado",
        precio: float | None = None,
        motivo: str = "",
        escalones: list[tuple[float, float]] | None = None,
    ) -> bool:
        """Envía la entrada con su stop. `objetivos` son (precio, fracción) en orden de cercanía: se cierra esa
        fracción de los contratos en cada precio. El último precio es el TP; si es None, el último trozo no
        tiene TP (sale por el stop, el trailing o el cierre forzoso). Con menos contratos que objetivos se
        saltan los primeros. Devuelve si la orden se ha enviado.

        Con `escalones` [(precio, fracción), (precio, fracción)] se entra con una orden límite en cada precio,
        repartiendo los contratos, y todo sale en el último objetivo: sin tomas parciales. Con un solo contrato,
        solo en el primer escalón."""
        p = self.p
        if escalones:
            return self._escalonada(lado, stop, objetivos[-1][0], escalones, motivo)
        tramos = _repartir(p.contratos, objetivos)
        tp = tramos[-1][0]
        envia = self.e.comprar if lado > 0 else self.e.vender
        try:
            envia(p.contratos, tipo=tipo, precio=precio, sl=stop, tp=tp, micro=p.micro, motivo=motivo)
        except OrdenNoValida:
            return False
        self.plan = _Plan(lado, stop, tramos, p.contratos, sl_actual=stop)
        self._confirmar()
        return True

    def _escalonada(self, lado: int, stop: float, tp: float | None, escalones, motivo: str) -> bool:
        p = self.p
        envia = self.e.comprar if lado > 0 else self.e.vender
        if p.contratos == 1:
            reparto = [(escalones[0][0], 1)]
        else:
            primero = max(1, min(p.contratos - 1, round(p.contratos * escalones[0][1] / sum(f for _, f in escalones))))
            reparto = [(escalones[0][0], primero), (escalones[1][0], p.contratos - primero)]
        try:
            for precio, n in reparto:
                envia(n, tipo="limite", precio=precio, sl=stop, tp=tp, micro=p.micro, motivo=motivo)
        except OrdenNoValida:
            self.e.cancelar()
            return False
        self.plan = _Plan(lado, stop, [(tp, p.contratos)], p.contratos, sl_actual=stop, sin_parcial=True)
        return True

    def _confirmar(self) -> None:
        """Si la entrada ya se ha ejecutado: apunta la operación y pone las tomas parciales."""
        plan, e = self.plan, self.e
        if plan.confirmado or not e.posicion:
            return
        plan.confirmado = True
        plan.entrada = e.precio_entrada
        plan.riesgo = abs(plan.entrada - plan.stop)
        if e.fecha != self._fecha:
            self._fecha, self._del_dia = e.fecha, 0
        self._del_dia += 1
        self._seguidas = self._seguidas + 1 if plan.lado == self._ultimo_lado else 1
        self._ultimo_lado = plan.lado
        for precio, contratos in plan.tramos[:-1]:
            try:
                e.tomar_parcial(contratos, precio)
            except OrdenNoValida:
                plan.avisos.append(f"Parcial a {precio} no válida")

    def cancelar_pendientes(self) -> None:
        """Cancela las órdenes de entrada que no se han ejecutado y, si no había posición, olvida la operación."""
        self.e.cancelar()
        if self.plan is not None and not self.e.posicion:
            self.plan = None

    # --- Mientras dura ---

    def gestionar(self, vela) -> None:
        """Llamar al principio de cada vela cerrada: confirma entradas, mueve el stop y cierra a su hora."""
        plan, e, p = self.plan, self.e, self.p
        if plan is None:
            return
        if not plan.confirmado:
            if e.posicion:
                self._confirmar()
            elif not any(o.papel == "entrada" for o in e.ordenes):
                self.plan = None  # la orden se canceló o no llegó a ejecutarse
                return
        if not e.posicion:
            if plan.confirmado:
                self.plan = None  # ya se cerró por su stop, su objetivo o el cierre forzoso
            elif self._fuera_de_hora():
                e.cancelar()
                self.plan = None
            return
        if self._fuera_de_hora():
            e.cerrar("Cierre forzoso" if self.pasada_la_hora_de_cierre() else "Fin de la sesión")
            self.plan = None
            return
        parcial_hecha = not plan.sin_parcial and abs(e.posicion) < plan.contratos
        if not plan.break_even:
            llego = p.be_r and plan.riesgo and (
                vela.high >= plan.entrada + p.be_r * plan.riesgo if plan.lado > 0 else vela.low <= plan.entrada - p.be_r * plan.riesgo
            )
            if (p.be_tras_parcial and parcial_hecha) or llego:
                self._llevar_stop(plan.entrada)
                plan.break_even = True
        if p.trailing != "no" and (parcial_hecha or not p.trailing_tras_parcial):
            self._trailing(vela)

    def _fuera_de_hora(self) -> bool:
        if self.pasada_la_hora_de_cierre():
            return True
        return bool(self.p.cerrar_fin_sesion) and not self.en_horario()

    def _llevar_stop(self, precio: float) -> None:
        plan = self.plan
        mejor = precio > plan.sl_actual if plan.lado > 0 else precio < plan.sl_actual
        if not mejor:
            return
        try:
            self.e.mover_sl(precio)
            plan.sl_actual = precio
        except OrdenNoValida:
            self.e.cerrar("Stop alcanzado al moverlo")  # el precio ya está más allá del nuevo stop

    def _trailing(self, vela) -> None:
        plan, e, p = self.plan, self.e, self.p
        margen = p.trailing_margen_ticks * e.tick
        if p.trailing == "ema":
            media = e.ema(p.trailing_ema)
            if media is None:
                return
            nuevo = media - margen if plan.lado > 0 else media + margen
        else:
            n = p.trailing_velas
            if len(e.velas) < n:
                return
            nuevo = min(e.velas.low[-n:]) - margen if plan.lado > 0 else max(e.velas.high[-n:]) + margen
        # El stop solo avanza, y tiene que quedar al otro lado del precio.
        if (plan.lado > 0 and nuevo < vela.close) or (plan.lado < 0 and nuevo > vela.close):
            self._llevar_stop(round(nuevo / e.tick) * e.tick)


def _repartir(contratos: int, objetivos: list[tuple[float | None, float]]) -> list[tuple[float | None, int]]:
    """Contratos de cada objetivo según su fracción. El último se lleva el resto (al menos 1), así que con
    pocos contratos se saltan los primeros objetivos."""
    total = sum(f for _, f in objetivos)
    tramos, usados = [], 0
    for precio, fraccion in objetivos[:-1]:
        n = int(contratos * fraccion / total + 1e-9)
        n = min(n, contratos - usados - 1)
        if n > 0:
            tramos.append((precio, n))
            usados += n
    tramos.append((objetivos[-1][0], contratos - usados))
    return tramos
