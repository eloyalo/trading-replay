"""Motor de órdenes (spec 005): ejecuta órdenes con velas de 1m y lleva posiciones, operaciones y balance.

No toca disco ni HTTP. Las horas son las del mercado (ET sin zona), como el reloj del replay.

Los datos son el BID del CFD. Para operar se redondea al tick y el ASK es el BID más el spread.
Los cálculos se hacen en ticks enteros y los precios se guardan en puntos, siempre en la rejilla.

Con velas de 1m no se sabe el orden de los precios dentro del minuto: se elige siempre lo peor
para el trader (RF-14).
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from trading_replay.operativa.contratos import CONTRATOS, Contrato

UN_MINUTO = timedelta(minutes=1)
COMPRA, VENTA = 1, -1
TIPOS = ("mercado", "limite", "stop")
MAX_CONTRATOS = 50


class OrdenNoValida(ValueError):
    pass


def nuevo_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class Costes:
    spread_ticks: int = 1
    deslizamiento_ticks: int = 0
    comision_mini: float = 2.5  # $ por contrato y lado
    comision_micro: float = 0.75

    def comision(self, contrato: Contrato, cantidad: int) -> float:
        return round(cantidad * (self.comision_micro if contrato.micro else self.comision_mini), 2)


@dataclass
class Minuto:
    """Vela de 1m del CFD (BID), con la hora de inicio."""

    inicio: datetime
    open: float
    high: float
    low: float
    close: float


@dataclass
class Orden:
    contrato: str
    lado: int  # COMPRA o VENTA
    tipo: str  # mercado | limite | stop
    cantidad: int
    precio: float | None = None
    sl_puntos: float | None = None
    tp_puntos: float | None = None
    papel: str = "entrada"  # entrada | sl | tp | cierre; las que no son de entrada solo cierran
    grupo: str | None = None  # OCO: el SL y el TP de una misma entrada
    activa_desde: datetime | None = None  # primer minuto en que se evalúa
    nacida_en: datetime | None = None  # minuto dentro del cual se creó (su apertura fue anterior)
    estado: str = "pendiente"  # pendiente | ejecutada | cancelada
    precio_ejecucion: float | None = None
    ejecutada: datetime | None = None
    id: str = field(default_factory=nuevo_id)

    @property
    def solo_cierre(self) -> bool:
        return self.papel != "entrada"


@dataclass
class Ejecucion:
    orden: str
    contrato: str
    lado: int
    cantidad: int
    precio: float
    comision: float
    instante: datetime
    papel: str = "entrada"
    id: str = field(default_factory=nuevo_id)


@dataclass
class Operacion:
    """De plano a plano: se abre con la primera ejecución y se cierra al volver a cero."""

    contrato: str
    lado: int
    apertura: datetime
    cantidad: int = 0  # la máxima que llegó a tener
    suma_entrada: float = 0.0
    contratos_entrada: int = 0
    suma_salida: float = 0.0
    contratos_salida: int = 0
    pnl_bruto: float = 0.0
    comisiones: float = 0.0
    cierre: datetime | None = None
    sl_inicial: float | None = None
    id: str = field(default_factory=nuevo_id)

    @property
    def entrada(self) -> float:
        return self.suma_entrada / self.contratos_entrada

    @property
    def salida(self) -> float | None:
        return self.suma_salida / self.contratos_salida if self.contratos_salida else None

    @property
    def pnl_neto(self) -> float:
        return round(self.pnl_bruto - self.comisiones, 2)


@dataclass
class Posicion:
    contrato: str
    cantidad: int = 0  # con signo: positiva larga, negativa corta
    precio_medio: float = 0.0
    operacion: Operacion | None = None


@dataclass
class Cambios:
    """Lo que ha cambiado desde la última vez, para guardarlo."""

    ordenes: list[Orden]
    ejecuciones: list[Ejecucion]
    operaciones: list[Operacion]
    posiciones: list[Posicion]


def _ticks(contrato: Contrato, precio: float) -> int:
    return round(precio / contrato.tick)


def _precio(contrato: Contrato, ticks: int) -> float:
    return round(ticks * contrato.tick, 2)


class Motor:
    def __init__(self, costes: Costes, balance: float, ordenes=(), posiciones=()):
        self.costes = costes
        self.balance = balance
        self.ordenes: list[Orden] = [o for o in ordenes if o.estado == "pendiente"]
        self.posiciones: dict[str, Posicion] = {p.contrato: p for p in posiciones}
        self.ultimo: dict[str, Minuto] = {}  # último minuto visto de cada instrumento; lo pone el servicio
        self._ordenes_tocadas: dict[str, Orden] = {}
        self._ejecuciones: list[Ejecucion] = []
        self._operaciones_tocadas: dict[str, Operacion] = {}
        self._posiciones_tocadas: set[str] = set()

    # --- Consultas ---

    def simbolos_con_exposicion(self) -> set[str]:
        simbolos = {CONTRATOS[o.contrato].simbolo for o in self.ordenes if o.estado == "pendiente"}
        simbolos |= {CONTRATOS[p.contrato].simbolo for p in self.posiciones.values() if p.cantidad}
        return simbolos

    def hay_exposicion(self) -> bool:
        return bool(self.simbolos_con_exposicion())

    def bid_ask(self, contrato: Contrato) -> tuple[int, int] | None:
        """BID y ASK actuales en ticks (cierre del último minuto visto)."""
        ultimo = self.ultimo.get(contrato.simbolo)
        if ultimo is None:
            return None
        bid = _ticks(contrato, ultimo.close)
        return bid, bid + self.costes.spread_ticks

    def pnl_abierto(self, posicion: Posicion) -> float:
        """Lo que se ganaría cerrando ahora: los largos al BID y los cortos al ASK."""
        precios = self.bid_ask(CONTRATOS[posicion.contrato])
        if not posicion.cantidad or precios is None:
            return 0.0
        return self.pnl_con_bid(posicion, precios[0])

    def pnl_con_bid(self, posicion: Posicion, bid: int) -> float:
        """PnL abierto si el BID estuviera en `bid` ticks."""
        constante, pendiente = self.recta_pnl(posicion)
        return round(constante + pendiente * bid, 2)

    def recta_pnl(self, posicion: Posicion) -> tuple[float, float]:
        """El PnL abierto es lineal en el BID (en ticks): constante + pendiente × bid."""
        contrato = CONTRATOS[posicion.contrato]
        spread = self.costes.spread_ticks if posicion.cantidad < 0 else 0  # los cortos cierran al ASK
        pendiente = contrato.valor_tick * posicion.cantidad
        return (spread - posicion.precio_medio / contrato.tick) * pendiente, pendiente

    def vaciar_cambios(self) -> Cambios:
        cambios = Cambios(
            list(self._ordenes_tocadas.values()),
            self._ejecuciones,
            list(self._operaciones_tocadas.values()),
            [self.posiciones[c] for c in self._posiciones_tocadas],
        )
        self._ordenes_tocadas, self._ejecuciones, self._operaciones_tocadas = {}, [], {}
        self._posiciones_tocadas = set()
        self.ordenes = [o for o in self.ordenes if o.estado == "pendiente"]
        return cambios

    # --- Órdenes ---

    def enviar(self, orden: Orden, instante: datetime) -> list[Ejecucion]:
        """Recibe una orden con el reloj en `instante`. Las de mercado se ejecutan en el acto si el
        mercado está abierto; las demás se evalúan desde el minuto que empieza en `instante`."""
        contrato = self._validar(orden)
        precios = self.bid_ask(contrato)
        if precios is None:
            raise OrdenNoValida(f"Todavía no hay precio de {contrato.simbolo}")
        if orden.precio is not None:
            orden.precio = _precio(contrato, _ticks(contrato, orden.precio))
        self._comprobar_stop(orden, contrato, orden.precio)
        orden.activa_desde = instante
        orden.nacida_en = None
        self.ordenes.append(orden)
        self._tocar_orden(orden)

        ultimo = self.ultimo[contrato.simbolo]
        if orden.tipo == "mercado" and ultimo.inicio + UN_MINUTO == instante:
            return self._ejecutar(orden, self._precio_a_mercado(orden, contrato), instante, None, True)
        return []

    def modificar(self, id_orden: str, precio: float) -> Orden:
        orden = self._pendiente(id_orden)
        if orden.tipo == "mercado":
            raise OrdenNoValida("Una orden a mercado no tiene precio")
        contrato = CONTRATOS[orden.contrato]
        nuevo = _precio(contrato, _ticks(contrato, precio))
        if nuevo <= 0:
            raise OrdenNoValida("El precio tiene que ser positivo")
        self._comprobar_stop(orden, contrato, nuevo)
        orden.precio = nuevo
        self._tocar_orden(orden)
        return orden

    def cancelar(self, id_orden: str) -> Orden:
        orden = self._pendiente(id_orden)
        self._cancelar(orden)
        return orden

    def cerrar(self, codigo: str, instante: datetime) -> list[Ejecucion]:
        """Cancela las órdenes del contrato y cierra su posición a mercado."""
        for orden in [o for o in self.ordenes if o.contrato == codigo and o.estado == "pendiente"]:
            self._cancelar(orden)
        posicion = self.posiciones.get(codigo)
        if not posicion or not posicion.cantidad:
            return []
        lado = VENTA if posicion.cantidad > 0 else COMPRA
        return self.enviar(Orden(codigo, lado, "mercado", abs(posicion.cantidad), papel="cierre"), instante)

    def liquidar(self, instante: datetime) -> list[Ejecucion]:
        """Cancela todo y cierra todas las posiciones al último precio, esté o no abierto el
        mercado: se usa al saltar a otro momento o salir del replay (RF-17)."""
        for orden in list(self.ordenes):
            if orden.estado == "pendiente":
                self._cancelar(orden)
        ejecuciones = []
        for posicion in self.posiciones.values():
            contrato = CONTRATOS[posicion.contrato]
            if not posicion.cantidad or contrato.simbolo not in self.ultimo:
                continue
            lado = VENTA if posicion.cantidad > 0 else COMPRA
            orden = Orden(posicion.contrato, lado, "mercado", abs(posicion.cantidad), papel="cierre", activa_desde=instante)
            self.ordenes.append(orden)
            ejecuciones += self._ejecutar(orden, self._precio_a_mercado(orden, contrato), instante, None, True)
        return ejecuciones

    # --- Avance del reloj ---

    def procesar(self, simbolo: str, minuto: Minuto) -> list[Ejecucion]:
        """Evalúa las órdenes de `simbolo` con un minuto nuevo."""
        ejecuciones = []
        vistas: set[str] = set()
        while True:
            # Las órdenes que nacen en este minuto (SL y TP de una entrada) se evalúan en la vuelta siguiente.
            candidatas = [
                o
                for o in self.ordenes
                if o.estado == "pendiente"
                and o.id not in vistas
                and CONTRATOS[o.contrato].simbolo == simbolo
                and o.activa_desde <= minuto.inicio
            ]
            if not candidatas:
                break
            for orden in candidatas:
                # Cancelada por otra de esta misma vuelta, o ya evaluada junto a su pareja del OCO.
                if orden.estado != "pendiente" or orden.id in vistas:
                    continue
                elegida = self._elegir_en_oco(orden, minuto, vistas)
                if elegida:
                    ejecuciones += self._ejecutar(elegida[0], elegida[1], minuto.inicio, minuto.inicio, elegida[2])
        self.ultimo[simbolo] = minuto
        return ejecuciones

    def _elegir_en_oco(self, orden: Orden, minuto: Minuto, vistas: set[str]) -> tuple[Orden, float, bool] | None:
        """Orden que se ejecuta en este minuto (con su precio y si fue en la apertura), o None.
        Si es parte de un OCO activo, se evalúa junto a su pareja (RF-14)."""
        parejas = [orden]
        if orden.grupo:
            parejas += [
                o
                for o in self.ordenes
                if o.grupo == orden.grupo and o is not orden and o.estado == "pendiente" and o.activa_desde <= minuto.inicio
            ]
        posibles = []
        for o in parejas:
            vistas.add(o.id)
            resultado = self._precio_si_ejecuta(o, minuto)
            if resultado:
                posibles.append((o, *resultado))
        if len(posibles) < 2:
            return posibles[0] if posibles else None
        # Las dos se ejecutarían: gana la que lo hace en la apertura; si ninguna (o las dos), el SL.
        en_apertura = [p for p in posibles if p[2]]
        if len(en_apertura) == 1:
            return en_apertura[0]
        return next(p for p in posibles if p[0].papel == "sl")

    def _precio_si_ejecuta(self, orden: Orden, minuto: Minuto) -> tuple[float, bool] | None:
        """Precio de ejecución en este minuto y si es en la apertura, o None si no se ejecuta."""
        contrato = CONTRATOS[orden.contrato]
        compra = orden.lado == COMPRA
        # Las compras se hacen al ASK y las ventas al BID.
        extra = self.costes.spread_ticks if compra else 0
        o, h, l = (_ticks(contrato, x) + extra for x in (minuto.open, minuto.high, minuto.low))
        desliz = orden.lado * self.costes.deslizamiento_ticks
        # Si la orden nació dentro de este minuto, la apertura fue antes que ella: no hay "hueco".
        hueco = orden.nacida_en != minuto.inicio
        if orden.tipo == "mercado":
            return _precio(contrato, o + desliz), True
        p = _ticks(contrato, orden.precio)
        if orden.tipo == "limite":
            if hueco and (o <= p if compra else o >= p):
                return _precio(contrato, o), True
            if l <= p if compra else h >= p:
                return _precio(contrato, p), False
            return None
        if hueco and (o >= p if compra else o <= p):
            return _precio(contrato, o + desliz), True
        if h >= p if compra else l <= p:
            return _precio(contrato, p + desliz), False
        return None

    # --- Ejecución y posiciones ---

    def _precio_a_mercado(self, orden: Orden, contrato: Contrato) -> float:
        bid, ask = self.bid_ask(contrato)
        desliz = orden.lado * self.costes.deslizamiento_ticks
        return _precio(contrato, (ask if orden.lado == COMPRA else bid) + desliz)

    def _ejecutar(
        self, orden: Orden, precio: float, instante: datetime, minuto: datetime | None, en_apertura: bool
    ) -> list[Ejecucion]:
        """Ejecuta `orden` a `precio`. `minuto` es el minuto en curso (None si se ejecuta entre dos
        minutos, como una orden a mercado en el acto)."""
        contrato = CONTRATOS[orden.contrato]
        posicion = self.posiciones.setdefault(orden.contrato, Posicion(orden.contrato))
        cantidad = orden.cantidad
        if orden.solo_cierre:
            if posicion.cantidad * orden.lado >= 0:  # no queda posición contraria que cerrar
                self._cancelar(orden)
                return []
            cantidad = min(cantidad, abs(posicion.cantidad))
            orden.cantidad = cantidad
        orden.estado = "ejecutada"
        orden.precio_ejecucion = precio
        orden.ejecutada = instante
        self._tocar_orden(orden)
        if orden.grupo:
            for otra in self.ordenes:
                if otra.grupo == orden.grupo and otra.estado == "pendiente":
                    self._cancelar(otra)

        comision = self.costes.comision(contrato, cantidad)
        ejecucion = Ejecucion(orden.id, orden.contrato, orden.lado, cantidad, precio, comision, instante, orden.papel)
        self._ejecuciones.append(ejecucion)
        self.balance = round(self.balance - comision, 2)
        abiertos = self._aplicar(posicion, ejecucion, contrato)

        if orden.papel == "entrada" and abiertos and (orden.sl_puntos or orden.tp_puntos):
            self._crear_sl_tp(orden, contrato, abiertos, precio, instante, minuto, en_apertura)
        if not posicion.cantidad:
            for otra in self.ordenes:
                if otra.contrato == orden.contrato and otra.solo_cierre and otra.estado == "pendiente":
                    self._cancelar(otra)
        return [ejecucion]

    def _aplicar(self, posicion: Posicion, ejecucion: Ejecucion, contrato: Contrato) -> int:
        """Suma la ejecución a la posición. Devuelve los contratos abiertos en su sentido."""
        lado, cantidad, precio = ejecucion.lado, ejecucion.cantidad, ejecucion.precio
        self._posiciones_tocadas.add(posicion.contrato)
        if not posicion.cantidad or (posicion.cantidad > 0) == (lado > 0):
            self._abrir(posicion, lado, cantidad, precio, ejecucion.comision, ejecucion.instante)
            return cantidad

        cierra = min(cantidad, abs(posicion.cantidad))
        sentido = 1 if posicion.cantidad > 0 else -1
        pnl = round((precio - posicion.precio_medio) / contrato.tick * contrato.valor_tick * cierra * sentido, 2)
        self.balance = round(self.balance + pnl, 2)
        comision_cierre = round(ejecucion.comision * cierra / cantidad, 2)
        operacion = posicion.operacion
        operacion.pnl_bruto = round(operacion.pnl_bruto + pnl, 2)
        operacion.suma_salida += precio * cierra
        operacion.contratos_salida += cierra
        operacion.comisiones = round(operacion.comisiones + comision_cierre, 2)
        self._operaciones_tocadas[operacion.id] = operacion
        posicion.cantidad += lado * cierra
        if not posicion.cantidad:
            operacion.cierre = ejecucion.instante
            posicion.operacion = None
            posicion.precio_medio = 0.0

        resto = cantidad - cierra
        if resto:  # da la vuelta: lo que sobra abre una operación nueva
            self._abrir(posicion, lado, resto, precio, round(ejecucion.comision - comision_cierre, 2), ejecucion.instante)
        return resto

    def _abrir(self, posicion: Posicion, lado: int, cantidad: int, precio: float, comision: float, instante: datetime):
        if posicion.operacion is None:
            posicion.operacion = Operacion(posicion.contrato, lado, instante)
        operacion = posicion.operacion
        total = abs(posicion.cantidad) + cantidad
        posicion.precio_medio = (abs(posicion.cantidad) * posicion.precio_medio + cantidad * precio) / total
        posicion.cantidad = lado * total
        operacion.cantidad = max(operacion.cantidad, total)
        operacion.suma_entrada += precio * cantidad
        operacion.contratos_entrada += cantidad
        operacion.comisiones = round(operacion.comisiones + comision, 2)
        self._operaciones_tocadas[operacion.id] = operacion

    def _crear_sl_tp(
        self,
        entrada: Orden,
        contrato: Contrato,
        cantidad: int,
        precio: float,
        instante: datetime,
        minuto: datetime | None,
        en_apertura: bool,
    ):
        """SL y TP de una entrada ejecutada, como OCO. Criterio conservador (RF-14): si la entrada fue
        a mitad del minuto, el SL ya cuenta en ese minuto y el TP solo desde el siguiente."""
        grupo = nuevo_id()
        lado = -entrada.lado
        base = _ticks(contrato, precio)
        nuevas = []
        if entrada.sl_puntos:
            sl = _precio(contrato, base - entrada.lado * _ticks(contrato, entrada.sl_puntos))
            nuevas.append(Orden(contrato.codigo, lado, "stop", cantidad, sl, papel="sl", grupo=grupo, activa_desde=minuto or instante))
            operacion = self.posiciones[contrato.codigo].operacion
            if operacion.sl_inicial is None:
                operacion.sl_inicial = sl
        if entrada.tp_puntos:
            tp = _precio(contrato, base + entrada.lado * _ticks(contrato, entrada.tp_puntos))
            desde = minuto if minuto is None or en_apertura else minuto + UN_MINUTO
            nuevas.append(Orden(contrato.codigo, lado, "limite", cantidad, tp, papel="tp", grupo=grupo, activa_desde=desde or instante))
        for orden in nuevas:
            orden.nacida_en = minuto
            self.ordenes.append(orden)
            self._tocar_orden(orden)

    # --- Ayudantes ---

    def _validar(self, orden: Orden) -> Contrato:
        contrato = CONTRATOS.get(orden.contrato)
        if contrato is None:
            raise OrdenNoValida(f"Contrato desconocido: {orden.contrato}")
        if orden.lado not in (COMPRA, VENTA):
            raise OrdenNoValida("El lado tiene que ser compra o venta")
        if orden.tipo not in TIPOS:
            raise OrdenNoValida(f"Tipo de orden no válido: {orden.tipo}")
        if not 1 <= orden.cantidad <= MAX_CONTRATOS:
            raise OrdenNoValida(f"La cantidad va de 1 a {MAX_CONTRATOS} contratos")
        if orden.tipo == "mercado":
            orden.precio = None
        elif orden.precio is None or orden.precio <= 0:
            raise OrdenNoValida("Las órdenes límite y stop necesitan un precio")
        for nombre in ("sl_puntos", "tp_puntos"):
            valor = getattr(orden, nombre)
            if valor is not None and _ticks(contrato, valor) < 1:
                raise OrdenNoValida("El SL y el TP tienen que estar al menos a un tick")
        return contrato

    def _comprobar_stop(self, orden: Orden, contrato: Contrato, precio: float | None):
        """Un stop de compra tiene que quedar por encima del ASK y uno de venta por debajo del BID."""
        if orden.tipo != "stop":
            return
        precios = self.bid_ask(contrato)
        if precios is None:
            return
        bid, ask = precios
        p = _ticks(contrato, precio)
        if orden.lado == COMPRA and p <= ask:
            raise OrdenNoValida(f"Un stop de compra tiene que estar por encima del precio ({_precio(contrato, ask)})")
        if orden.lado == VENTA and p >= bid:
            raise OrdenNoValida(f"Un stop de venta tiene que estar por debajo del precio ({_precio(contrato, bid)})")

    def _pendiente(self, id_orden: str) -> Orden:
        for orden in self.ordenes:
            if orden.id == id_orden and orden.estado == "pendiente":
                return orden
        raise KeyError(id_orden)

    def _cancelar(self, orden: Orden):
        orden.estado = "cancelada"
        self._tocar_orden(orden)

    def _tocar_orden(self, orden: Orden):
        self._ordenes_tocadas[orden.id] = orden
