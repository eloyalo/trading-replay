"""Ejecutor del backtest (spec 008, RF-7 y RF-8): pasa una estrategia por el histórico con el mismo
`Motor` de órdenes que el trading manual.

Recorre las velas del timeframe de la estrategia. Mientras hay órdenes o posición, el motor ve cada
minuto de 1m, igual que en el replay; si no, se salta hasta el cierre de la vela. Al cerrar cada vela
la estrategia decide con el reloj en el fin de la vela: una orden a mercado sale al cierre del último
minuto, y las límite y stop se evalúan desde el minuto siguiente.

Los minutos se leen por columnas (numpy y `array`) para no crear un objeto por minuto: 4 años de 1m
son 1,4 millones.
"""

import time as reloj
from array import array
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np

from trading_replay.backtest.cargador import ErrorEstrategia, error_desde
from trading_replay.backtest.estrategia import Estrategia, ParametroNoValido, Vela, a_fecha
from trading_replay.backtest.indicadores import SEIS_HORAS, UN_DIA
from trading_replay.backtest.reto_bt import FIN_INTENTO, RetoBacktest
from trading_replay.historico import almacen
from trading_replay.operativa.contratos import CONTRATOS
from trading_replay.operativa.perfiles import Perfil
from trading_replay.operativa.motor import COMPRA, VENTA, Costes, Minuto, Motor, Operacion, Orden, OrdenNoValida, _precio, _ticks

UN_MINUTO = timedelta(minutes=1)
CADA_VELAS = 2000  # cada cuántas velas se avisa del progreso y se mira si hay que cancelar
TEXTO_PAPEL = {"sl": "SL", "tp": "TP", "cierre": "Cierre", "entrada": "Cambio de sentido"}
FIN_DATOS = "Fin de los datos"


class Cancelado(Exception):
    pass


@dataclass
class OperacionBT:
    """Una operación del backtest, de plano a plano (RF-13)."""

    numero: int
    contrato: str
    lado: int
    cantidad: int
    apertura: datetime
    cierre: datetime
    entrada: float
    salida: float
    sl_inicial: float | None
    sl_final: float | None
    tp_final: float | None
    motivo_entrada: str
    motivo_salida: str
    pnl_bruto: float
    comisiones: float
    riesgo: float | None  # $ de la entrada al SL inicial
    dudosa: bool  # SL y TP en el mismo minuto: se dio por bueno el SL
    # Minuto de 1m cuyo precio dio la entrada y la salida: el anterior a la apertura si fue a mercado en el
    # acto (al cierre de una vela), o el de la apertura si se ejecutó dentro de un minuto (límite, stop, SL, TP).
    minuto_entrada: datetime | None = None
    minuto_salida: datetime | None = None
    intento: int | None = None  # con reto (spec 009): el intento en el que se abrió

    @property
    def pnl_neto(self) -> float:
        return round(self.pnl_bruto - self.comisiones, 2)

    @property
    def r(self) -> float | None:
        return self.pnl_neto / self.riesgo if self.riesgo else None


@dataclass
class Marca:
    """Algo que la estrategia dibuja para explicarse (RF-4)."""

    tipo: str  # nivel | rango | texto
    instante: datetime
    fin: datetime | None
    precio: float | None
    precio2: float | None
    texto: str
    datos: dict | None = None  # solo la marca `fibonacci` (spec 012): origen, final, retrocesos y extensiones


@dataclass
class Resultado:
    operaciones: list[OperacionBT]
    marcas: list[Marca]
    minutos: int
    velas: int
    segundos: float
    reto: RetoBacktest | None = None  # con reto (spec 009): intentos y órdenes rechazadas


class MotorBacktest(Motor):
    """El motor de siempre, con lo que el backtest necesita además:

    - SL y TP en precio o en R: el motor trabaja con distancias desde el precio de ejecución, así que
      se calculan al ejecutarse la entrada. Si el precio ya está rebasado, se apunta para cerrar.
    - Qué operación abre y cierra cada ejecución, y el SL y el TP que tenía al cerrar.
    """

    def __init__(self, costes: Costes):
        super().__init__(costes, 0.0)
        self.niveles: dict[str, tuple] = {}  # id de la orden de entrada → (sl, tp, tp_r) pedidos
        self.rebasadas: list[tuple[str, str]] = []  # (contrato, motivo) que hay que cerrar ya
        self.abiertas_por: dict[str, tuple[str, datetime, int | None]] = {}  # id de la operación → (orden, minuto, intento)
        self.intento_actual: int | None = None  # con reto: el intento en curso
        self.cerradas: list[tuple[Operacion, str, str, float | None, float | None, datetime]] = []
        self._minuto_precio: datetime | None = None  # el de la ejecución en curso

    def _ejecutar(self, orden, precio, instante, minuto, en_apertura):
        # `minuto` es None cuando se ejecuta en el acto, al último precio: el del minuto anterior al instante.
        self._minuto_precio = minuto if minuto is not None else instante - UN_MINUTO
        return super()._ejecutar(orden, precio, instante, minuto, en_apertura)

    def _crear_sl_tp(self, entrada: Orden, contrato, cantidad, precio, instante, minuto, en_apertura):
        pedidos = self.niveles.pop(entrada.id, None)
        if pedidos:
            sl, tp, tp_r = pedidos
            base = _ticks(contrato, precio)
            if sl is not None:
                distancia = (base - _ticks(contrato, sl)) * entrada.lado
                if distancia < 1:
                    self.rebasadas.append((contrato.codigo, "SL rebasado al entrar"))
                    return
                entrada.sl_puntos = _precio(contrato, distancia)
            if tp_r is not None:
                riesgo = _ticks(contrato, entrada.sl_puntos)
                entrada.tp_puntos = _precio(contrato, max(1, round(tp_r * riesgo)))
            elif tp is not None:
                distancia = (_ticks(contrato, tp) - base) * entrada.lado
                if distancia < 1:
                    self.rebasadas.append((contrato.codigo, "TP rebasado al entrar"))
                    return
                entrada.tp_puntos = _precio(contrato, distancia)
        super()._crear_sl_tp(entrada, contrato, cantidad, precio, instante, minuto, en_apertura)

    def _aplicar(self, posicion, ejecucion, contrato):
        previa = posicion.operacion
        if previa is not None:
            # El SL y el TP siguen en la lista hasta `vaciar_cambios`, aunque ya no estén pendientes.
            sl = next((o.precio for o in reversed(self.ordenes) if o.contrato == contrato.codigo and o.papel == "sl"), None)
            tp = next((o.precio for o in reversed(self.ordenes) if o.contrato == contrato.codigo and o.papel == "tp"), None)
        abiertos = super()._aplicar(posicion, ejecucion, contrato)
        if previa is not None and previa.cierre is not None:
            self.cerradas.append((previa, ejecucion.orden, ejecucion.papel, sl, tp, self._minuto_precio))
        if posicion.operacion is not None and posicion.operacion is not previa:
            self.abiertas_por[posicion.operacion.id] = (ejecucion.orden, self._minuto_precio, self.intento_actual)
        return abiertos


def cubetas(t: np.ndarray, tf: str) -> np.ndarray:
    """Inicio de la vela de `tf` de cada minuto. Misma regla que `almacen.consultar` y `cubeta()` de
    `calculos.js`: 4h se alinea a las 18:00 ET."""
    segundos = almacen.TIMEFRAMES[tf] * 60
    if tf == "1D":
        return (t + SEIS_HORAS) // UN_DIA * UN_DIA
    if segundos >= 4 * 3600:
        return (t + SEIS_HORAS) // segundos * segundos - SEIS_HORAS
    return t // segundos * segundos


def _columna(valores: np.ndarray, tipo: str = "d") -> array:
    """De numpy a `array`: se lee elemento a elemento mucho más rápido y ocupa lo mismo."""
    resultado = array(tipo)
    resultado.frombytes(np.ascontiguousarray(valores, dtype="i8" if tipo == "q" else "f8").tobytes())
    return resultado


def armar_velas(columnas: dict[str, np.ndarray], tf: str) -> dict[str, np.ndarray]:
    """Velas de `tf` a partir de los minutos: inicio (`t`), OHLCV y la posición del primer y del
    último minuto de cada una."""
    t = columnas["t"]
    if not len(t):
        vacia = np.array([], dtype="i8")
        return {"t": vacia, "open": vacia, "high": vacia, "low": vacia, "close": vacia, "volume": vacia, "primero": vacia, "ultimo": vacia}
    cubeta = cubetas(t, tf)
    primeros = np.flatnonzero(np.r_[True, cubeta[1:] != cubeta[:-1]])
    ultimos = np.r_[primeros[1:] - 1, len(t) - 1]
    return {
        "t": cubeta[primeros],
        "open": columnas["open"][primeros],
        "high": np.maximum.reduceat(columnas["high"], primeros),
        "low": np.minimum.reduceat(columnas["low"], primeros),
        "close": columnas["close"][ultimos],
        "volume": np.add.reduceat(columnas["volume"], primeros),
        "primero": primeros,
        "ultimo": ultimos,
    }


class Ejecutor:
    """Una pasada de una estrategia por un instrumento y un periodo."""

    def __init__(self, estrategia: Estrategia, simbolo: str, costes: Costes | None = None, perfil: Perfil | None = None):
        self.estrategia = estrategia
        self.simbolo = simbolo
        self.motor = MotorBacktest(costes or Costes())
        self.reto = RetoBacktest(perfil, self.motor) if perfil else None
        self.contratos = [c for c in CONTRATOS.values() if c.simbolo == simbolo]
        self.operaciones: list[OperacionBT] = []
        self.marcas: list[Marca] = []
        self._motivos: dict[str, str] = {}  # id de la orden de entrada → motivo que dio la estrategia
        self._motivo_cierre: dict[str, str] = {}  # contrato → motivo del próximo cierre pedido
        self._fin: datetime | None = None  # reloj: fin de la vela que acaba de cerrar
        estrategia._bt = self
        estrategia.simbolo = simbolo
        estrategia.tick = CONTRATOS[simbolo].tick
        self._motivos_salida: dict[str, str] = {}  # id de una orden de cierre → motivo, si cierra la operación

    # --- Bucle ---

    def ejecutar(
        self,
        columnas: dict[str, np.ndarray],
        progreso: Callable[[float], None] | None = None,
        cancelado: Callable[[], bool] | None = None,
    ) -> Resultado:
        inicio_real = reloj.perf_counter()
        e = self.estrategia
        velas = armar_velas(columnas, e.timeframe)
        duracion = almacen.TIMEFRAMES[e.timeframe] * 60
        t, o, h, l, c = (_columna(columnas[k], "q" if k == "t" else "d") for k in ("t", "open", "high", "low", "close"))
        vt = _columna(velas["t"], "q")
        vo, vh, vl, vc, vv = (_columna(velas[k]) for k in ("open", "high", "low", "close", "volume"))
        primeros, ultimos = _columna(velas["primero"], "q"), _columna(velas["ultimo"], "q")
        total = len(vt)
        motor, simbolo = self.motor, self.simbolo

        self._llamar(e.al_empezar, None)
        reto = self.reto
        dia_anterior = dia_reto = None
        for k in range(total):
            if reto:
                dia = (vt[k] + SEIS_HORAS) // UN_DIA
                if dia != dia_reto:
                    dia_reto = dia
                    self._cambiar_dia_reto(dia)
            if motor.ordenes or any(p.cantidad for p in motor.posiciones.values()):
                for i in range(primeros[k], ultimos[k] + 1):
                    minuto = Minuto(a_fecha(t[i]), o[i], h[i], l[i], c[i])
                    # Con reto, en el mismo orden que el replay: hora de cierre, órdenes y después las reglas.
                    if reto:
                        self._etiquetar(reto.antes_del_minuto(simbolo, minuto))
                    motor.procesar(simbolo, minuto)
                    if reto:
                        self._etiquetar(reto.despues_del_minuto(simbolo, minuto))
                    self._recoger()
                    if not motor.ordenes and not any(p.cantidad for p in motor.posiciones.values()):
                        break
            u = ultimos[k]
            motor.ultimo[simbolo] = Minuto(a_fecha(t[u]), o[u], h[u], l[u], c[u])

            e.velas.anadir(vt[k], vo[k], vh[k], vl[k], vc[k], vv[k])
            e._avanzar_indicadores()
            e._fin = vt[k] + duracion
            self._fin = a_fecha(e._fin)
            dia = (vt[k] + SEIS_HORAS) // UN_DIA
            if dia != dia_anterior:
                dia_anterior = dia
                self._llamar(e.al_empezar_dia, None)
            vela = Vela(a_fecha(vt[k]), self._fin, vo[k], vh[k], vl[k], vc[k], vv[k])
            self._llamar(e.al_cerrar_vela, vela, vela)

            if k % CADA_VELAS == 0:
                if cancelado and cancelado():
                    raise Cancelado
                if progreso:
                    progreso(k / total)

        if total:
            ultimo = motor.ultimo[simbolo]
            for contrato in self.contratos:
                self._motivo_cierre[contrato.codigo] = FIN_DATOS
            motor.liquidar(ultimo.inicio + UN_MINUTO)
            self._recoger()
            if reto and reto.intento:
                reto.cerrar_dia(ultimo.inicio + UN_MINUTO)
                reto.terminar(ultimo.inicio + UN_MINUTO)
        if reto:
            for intento in reto.intentos:
                intento.operaciones = sum(op.intento == intento.numero for op in self.operaciones)
        for marca in self.marcas:
            if marca.tipo == "fibonacci" and marca.fin is None:
                marca.fin = a_fecha(self._fin)  # la figura que nadie cerró llega hasta el final de los datos
        return Resultado(self.operaciones, self.marcas, len(t), total, reloj.perf_counter() - inicio_real, reto)

    def _cambiar_dia_reto(self, dia: int) -> None:
        """Empieza un día de trading del reto: cierra el anterior y, si el intento ha terminado, empieza otro (RF-3, RF-5)."""
        reto = self.reto
        inicio = a_fecha(dia * UN_DIA - SEIS_HORAS)
        if reto.intento is None:
            reto.empezar(inicio)
        else:
            reto.cerrar_dia(inicio)
            if not reto.en_curso:
                if self.motor.hay_exposicion():  # aprobado con algo abierto
                    self._etiquetar(FIN_INTENTO)
                    self.motor.liquidar(self.motor.ultimo[self.simbolo].inicio + UN_MINUTO)
                    self._recoger()
                reto.terminar(inicio)
                reto.empezar(inicio)
        reto.empezar_dia(a_fecha(dia * UN_DIA).date().isoformat())
        self.motor.intento_actual = reto.numero

    def _etiquetar(self, motivo: str | None) -> None:
        """Motivo de salida de lo que acaba de cerrar el reto (se apunta al recoger las operaciones)."""
        if motivo:
            for contrato in self.contratos:
                self._motivo_cierre[contrato.codigo] = motivo

    def _llamar(self, aviso, vela: Vela | None, *argumentos):
        """Llama a la estrategia y traduce sus errores a archivo, línea y vela (RF-5)."""
        try:
            aviso(*argumentos)
        except (ErrorEstrategia, Cancelado):
            raise
        except Exception as excepcion:
            error = error_desde(excepcion)
            if isinstance(excepcion, OrdenNoValida):
                error.mensaje = f"Orden no válida: {excepcion}"
            if vela is not None:
                error.vela = f"{vela.inicio:%Y-%m-%d %H:%M}"
            raise error from excepcion

    def _recoger(self) -> None:
        """Cierra lo rebasado al entrar y apunta las operaciones que se han cerrado."""
        motor = self.motor
        while motor.rebasadas:
            codigo, motivo = motor.rebasadas.pop(0)
            self._motivo_cierre[codigo] = motivo
            motor.cerrar(codigo, motor.ultimo[self.simbolo].inicio + UN_MINUTO)
        for cerrada in motor.cerradas:
            self._apuntar(*cerrada)
        motor.cerradas.clear()
        if motor.vaciar_cambios().ejecuciones and self.reto:
            self.reto.operado()

    def _apuntar(self, op: Operacion, orden: str, papel: str, sl: float | None, tp: float | None, minuto: datetime) -> None:
        contrato = CONTRATOS[op.contrato]
        orden_entrada, minuto_entrada, intento = self.motor.abiertas_por.pop(op.id, ("", None, None))
        if orden in self._motivos_salida:
            motivo = self._motivos_salida.pop(orden)
        elif papel == "cierre":
            motivo = self._motivo_cierre.pop(op.contrato, None) or "Cierre"
        else:
            motivo = TEXTO_PAPEL[papel]
        riesgo = None
        if op.sl_inicial is not None:
            riesgo = round(abs(op.entrada - op.sl_inicial) * contrato.multiplicador * op.cantidad, 2) or None
        self.operaciones.append(
            OperacionBT(
                numero=len(self.operaciones) + 1,
                contrato=op.contrato,
                lado=op.lado,
                cantidad=op.cantidad,
                apertura=op.apertura,
                cierre=op.cierre,
                entrada=round(op.entrada, 2),
                salida=round(op.salida, 2),
                sl_inicial=op.sl_inicial,
                sl_final=sl,
                tp_final=tp,
                motivo_entrada=self._motivos.get(orden_entrada, ""),
                motivo_salida=motivo,
                pnl_bruto=op.pnl_bruto,
                comisiones=op.comisiones,
                riesgo=riesgo,
                dudosa=orden in self.motor.dudosas,
                minuto_entrada=minuto_entrada,
                minuto_salida=minuto,
                intento=intento,
            )
        )

    # --- Lo que la estrategia puede pedir ---

    def _contrato(self, micro: bool) -> str:
        return ("M" if micro else "") + self.simbolo

    def posicion(self) -> int:
        return sum(p.cantidad for c, p in self.motor.posiciones.items() if CONTRATOS[c].simbolo == self.simbolo)

    def precio_entrada(self) -> float | None:
        for p in self.motor.posiciones.values():
            if p.cantidad and CONTRATOS[p.contrato].simbolo == self.simbolo:
                return round(p.precio_medio, 2)
        return None

    def pendientes(self) -> list[Orden]:
        return [o for o in self.motor.ordenes if o.estado == "pendiente"]

    def enviar(self, lado, contratos, tipo, precio, sl, sl_puntos, tp, tp_puntos, tp_r, micro, motivo) -> str:
        if sl is not None and sl_puntos is not None:
            raise OrdenNoValida("El SL va en precio (sl) o en puntos (sl_puntos), no en los dos")
        if sum(x is not None for x in (tp, tp_puntos, tp_r)) > 1:
            raise OrdenNoValida("El TP va en precio (tp), en puntos (tp_puntos) o en R (tp_r), solo uno")
        if tp_r is not None and sl is None and sl_puntos is None:
            raise OrdenNoValida("Para poner el TP en R hace falta un SL")
        if tp_r is not None and tp_r <= 0:
            raise OrdenNoValida("El TP en R tiene que ser positivo")
        contrato = CONTRATOS[self._contrato(micro)]
        orden = Orden(contrato.codigo, lado, tipo, int(contratos), precio, sl_puntos, tp_puntos)
        if self.reto and not self.reto.validar(orden, self._fin):
            return None  # el reto no la admite: no se envía, y la estrategia sigue (spec 009, RF-4)
        if sl is not None or tp is not None or tp_r is not None:
            # El motor solo crea el SL y el TP si la entrada trae distancias; las de verdad se calculan
            # al ejecutarse (`MotorBacktest._crear_sl_tp`).
            if sl is not None:
                orden.sl_puntos = contrato.tick
            if (tp is not None or tp_r is not None) and orden.tp_puntos is None:
                orden.tp_puntos = contrato.tick
            self.motor.niveles[orden.id] = (sl, tp, tp_r)
        self._motivos[orden.id] = motivo
        try:
            self.motor.enviar(orden, self._fin)
        except OrdenNoValida:
            self.motor.niveles.pop(orden.id, None)
            raise
        self._recoger()
        if self.reto:
            self._etiquetar(self.reto.tras_ejecucion(self._fin))
            self._recoger()
        return orden.id

    def cerrar(self, motivo: str) -> None:
        for contrato in self.contratos:
            self._motivo_cierre[contrato.codigo] = motivo or "Cierre"
            self.motor.cerrar(contrato.codigo, self._fin)
        self._recoger()

    def cancelar(self, id_orden: str | None) -> None:
        entradas = [o for o in self.pendientes() if o.papel == "entrada" and (id_orden is None or o.id == id_orden)]
        if id_orden is not None and not entradas:
            raise OrdenNoValida("No hay ninguna orden de entrada pendiente con ese id")
        for orden in entradas:
            self.motor.cancelar(orden.id)
        self._recoger()

    def tomar_parcial(self, contratos: int, precio: float) -> None:
        abiertas = [p for p in self.motor.posiciones.values() if p.cantidad and CONTRATOS[p.contrato].simbolo == self.simbolo]
        if not abiertas:
            raise OrdenNoValida("No hay ninguna posición de la que tomar una parte")
        posicion = abiertas[0]
        lado = VENTA if posicion.cantidad > 0 else COMPRA
        orden = Orden(posicion.contrato, lado, "limite", int(contratos), precio, papel="cierre")
        if self.reto and not self.reto.validar(orden, self._fin):
            return
        self._motivos_salida[orden.id] = "Toma parcial"
        self.motor.enviar(orden, self._fin)
        self._recoger()

    def mover_sl(self, precio: float) -> None:
        stops = [o for o in self.pendientes() if o.papel == "sl"]
        if not stops:
            raise OrdenNoValida("No hay ningún SL que mover")
        for orden in stops:
            self.motor.modificar(orden.id, precio)

    def marcar(self, tipo, instante, fin, precio, precio2, texto, datos=None) -> Marca:
        marca = Marca(tipo, instante, fin, precio, precio2, texto, datos)
        self.marcas.append(marca)
        return marca


def ejecutar(
    clase: type[Estrategia],
    valores: dict | None,
    simbolo: str,
    desde: datetime,
    hasta: datetime,
    costes: Costes | None = None,
    progreso: Callable[[float], None] | None = None,
    cancelado: Callable[[], bool] | None = None,
    perfil: Perfil | None = None,
) -> Resultado:
    """Pasa la estrategia por los minutos de `simbolo` con inicio en [desde, hasta) (hora ET), con las reglas
    del reto `perfil` si se da (spec 009)."""
    try:
        estrategia = clase(valores)
    except ParametroNoValido:
        raise
    except Exception as excepcion:
        raise error_desde(excepcion) from excepcion
    columnas = almacen.columnas_1m(simbolo, desde, hasta)
    return Ejecutor(estrategia, simbolo, costes, perfil).ejecutar(columnas, progreso, cancelado)
