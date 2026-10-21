"""Fibonacci: entrar en el retroceso de un impulso, en la zona 0,618–0,65, y salir en sus extensiones.

Impulso: del último pivote bajo al pivote alto siguiente (o al revés), con pivotes de 5 velas a cada lado, que se
conocen 5 velas después de formarse, como en vivo. Tiene que medir al menos 1,5 ATR.
Entrada: orden límite en el 0,618 mientras el precio no haya llegado. Stop: dos ticks más allá del 0,786.
Objetivos: la mitad en la extensión 1,0 (el máximo del impulso), con el stop a break-even, y la otra mitad en 1,618.
El swing se descarta si el precio pierde el 0,786 o rompe el origen antes de entrar, si supera el máximo sin haber
entrado, o a las 100 velas de los pivotes. Cada swing se opera una vez.
Variantes: entrada por rechazo en la zona o escalonada, confirmación con EMA y RSI, otros niveles, stops y extensiones,
trailing en el último tramo, reanclar al nuevo máximo, reentrada, pivotes en un timeframe mayor, sesiones y límites.
"""

from trading_replay.backtest import TIMEFRAMES, Estrategia, Parametro, ParametroNoValido
from trading_replay.backtest.comunes import Operativa, parametros_gestion, parametros_operativa, parametros_sesion
from trading_replay.backtest.estrategia import a_fecha
from trading_replay.backtest.swings import Pivotes

G_SWING, G_ENTRADA, G_SALIDA = "Swing", "Niveles y entrada", "Stop y objetivos"


def lista_de_numeros(texto: str, nombre: str) -> list[float]:
    try:
        numeros = [float(x) for x in texto.replace(";", ",").split(",") if x.strip()]
    except ValueError:
        raise ParametroNoValido(f"«{nombre}» tiene que ser una lista de números separados por comas, por ejemplo 1.0, 1.618") from None
    if not numeros or any(n <= 0 for n in numeros):
        raise ParametroNoValido(f"«{nombre}» necesita al menos un número mayor que 0")
    return numeros


class Swing:
    """Un impulso (origen → final) y lo que se ha hecho con él."""

    def __init__(self, lado, origen_precio, origen_t, final_precio, final_t, clave):
        self.lado = lado  # 1: impulso al alza, se busca comprar el retroceso
        self.origen_precio, self.origen_t = origen_precio, origen_t
        self.final_precio, self.final_t = final_precio, final_t
        self.clave = clave
        self.nacio = 0  # velas de los pivotes que había al detectarlo
        self.valido = True
        self.orden = False  # ya se ha enviado la entrada
        self.operado = False  # la entrada se ha ejecutado
        self.toco = False  # el precio ha tocado la zona (entrada por rechazo)
        self.marca = None


class Fibonacci(Estrategia):
    nombre = "Fibonacci"
    timeframe = "15m"
    parametros = {
        "timeframe": Parametro("15m", "Timeframe", opciones=list(TIMEFRAMES), grupo="General"),
        "marcar": Parametro(True, "Dibujar la figura de Fibonacci en el gráfico", grupo="General"),
        "atr_periodo": Parametro(14, "Periodo del ATR", minimo=2, maximo=200, grupo="General"),
        # Swing
        "velas_pivote": Parametro(5, "Velas a cada lado de un pivote", minimo=1, maximo=50, grupo=G_SWING),
        "tf_pivotes": Parametro("mismo", "Timeframe de los pivotes", opciones=["mismo", "15m", "30m", "1h", "4h"], grupo=G_SWING),
        "impulso_min_atr": Parametro(1.5, "Impulso mínimo (en ATR)", minimo=0, maximo=100, paso=0.25, grupo=G_SWING),
        "impulso_max_atr": Parametro(0.0, "Impulso máximo en ATR (0 = sin tope)", minimo=0, maximo=500, paso=0.5, grupo=G_SWING),
        "reanclar": Parametro(False, "Reanclar al nuevo extremo si el precio sigue antes de entrar", grupo=G_SWING),
        "max_velas_swing": Parametro(100, "Descartar el swing a las N velas de los pivotes (0 = nunca)", minimo=0, maximo=5000, grupo=G_SWING),
        "reentrada": Parametro(False, "Permitir volver a entrar en el mismo swing", grupo=G_SWING),
        # Niveles y entrada
        "entrada": Parametro("limite", "Entrada", opciones=["limite", "rechazo", "escalonada"], grupo=G_ENTRADA),
        "nivel_entrada": Parametro(0.618, "Nivel de entrada", minimo=0.05, maximo=0.95, paso=0.001, grupo=G_ENTRADA),
        "zona_hasta": Parametro(0.65, "Fondo de la zona de entrada", minimo=0.05, maximo=0.95, paso=0.001, grupo=G_ENTRADA),
        "limite_en": Parametro("nivel_entrada", "El límite va en", opciones=["nivel_entrada", "zona_hasta"], grupo=G_ENTRADA),
        "nivel_inval": Parametro(0.786, "Nivel de invalidación", minimo=0.1, maximo=1.0, paso=0.001, grupo=G_ENTRADA),
        "invalidacion": Parametro("nivel", "Se invalida al perder", opciones=["nivel", "origen"], grupo=G_ENTRADA),
        "confirma_ema": Parametro(False, "Rechazo: cerrar por encima de la EMA (a favor)", grupo=G_ENTRADA),
        "confirma_ema_periodo": Parametro(9, "Periodo de la EMA de confirmación", minimo=2, maximo=500, grupo=G_ENTRADA),
        "confirma_rsi": Parametro(False, "Rechazo: RSI en sobreventa / sobrecompra reciente", grupo=G_ENTRADA),
        "rsi_periodo": Parametro(14, "Periodo del RSI", minimo=2, maximo=200, grupo=G_ENTRADA),
        "rsi_nivel": Parametro(40, "RSI: largos si fue ≤ N y cortos si fue ≥ 100 − N", minimo=1, maximo=49, grupo=G_ENTRADA),
        # Stop y objetivos
        "stop_ref": Parametro("nivel invalidacion", "Stop más allá de", opciones=["nivel invalidacion", "origen", "atr"], grupo=G_SALIDA),
        "stop_margen_ticks": Parametro(2, "Margen del stop (ticks)", minimo=0, maximo=1000, grupo=G_SALIDA),
        "stop_margen_atr": Parametro(0.0, "Margen del stop (ATR)", minimo=0, maximo=10, paso=0.1, grupo=G_SALIDA),
        "stop_atr_n": Parametro(1.5, "Stop a N ATR de la entrada (si es por ATR)", minimo=0.1, maximo=20, paso=0.1, grupo=G_SALIDA),
        "objetivos_modo": Parametro("tramos", "Objetivos", opciones=["tramos", "unico", "tramos con trailing"], grupo=G_SALIDA),
        "extensiones": Parametro("1.0, 1.618", "Extensiones (de menos a más)", grupo=G_SALIDA),
        "fracciones": Parametro("0.5, 0.5", "Fracción que se cierra en cada una", grupo=G_SALIDA),
        "extension_unica": Parametro(1.618, "Extensión del objetivo único", minimo=0.1, maximo=10, paso=0.001, grupo=G_SALIDA),
        **parametros_sesion(),
        **parametros_operativa(),
        **parametros_gestion(),
    }

    def al_empezar(self):
        p = self.p
        self.op = Operativa(self)
        if p.zona_hasta < p.nivel_entrada:
            raise ParametroNoValido("El fondo de la zona no puede estar por encima del nivel de entrada")
        if p.nivel_inval <= max(p.nivel_entrada, p.zona_hasta):
            raise ParametroNoValido("El nivel de invalidación tiene que estar más allá de la zona de entrada")
        if p.entrada == "limite" and (p.confirma_ema or p.confirma_rsi):
            raise ParametroNoValido("Las confirmaciones con EMA y RSI solo valen con la entrada por rechazo")
        self.exts = lista_de_numeros(p.extensiones, "Extensiones")
        self.fracs = lista_de_numeros(p.fracciones, "Fracciones")
        if len(self.exts) != len(self.fracs):
            raise ParametroNoValido("Tiene que haber tantas fracciones como extensiones")
        if self.exts != sorted(self.exts):
            raise ParametroNoValido("Las extensiones van de menos a más")
        if p.objetivos_modo == "tramos con trailing" and p.trailing == "no":
            raise ParametroNoValido("Con el último tramo a trailing hay que elegir un trailing en «Gestión de la posición»")
        if p.tf_pivotes != "mismo":
            try:
                self.velas_de(p.tf_pivotes)
            except ValueError as error:
                raise ParametroNoValido(f"Timeframe de los pivotes: {error}") from None
        self.pivotes = Pivotes(p.velas_pivote)
        self.swing = None
        self.ultima_clave = None  # el último impulso que se ha mirado
        self.muertas = set()  # impulsos ya descartados: no vuelven
        self.retrocesos_marca = sorted({0.382, 0.5, p.nivel_entrada, p.zona_hasta, p.nivel_inval})
        self.extensiones_marca = [p.extension_unica] if p.objetivos_modo == "unico" else self.exts

    # --- Niveles ---

    def velas_de_pivotes(self):
        return self.velas if self.p.tf_pivotes == "mismo" else self.velas_de(self.p.tf_pivotes)

    def redondear(self, precio: float) -> float:
        return round(precio / self.tick) * self.tick

    def nivel_de(self, s: Swing, retroceso: float) -> float:
        """Precio de un retroceso: 0 es el final del impulso y 1 su origen."""
        return s.final_precio - (s.final_precio - s.origen_precio) * retroceso

    def extension_de(self, s: Swing, extension: float) -> float:
        """Precio de una extensión: 1,0 es el final del impulso."""
        return s.origen_precio + (s.final_precio - s.origen_precio) * extension

    def precio_invalidacion(self, s: Swing) -> float:
        return s.origen_precio if self.p.invalidacion == "origen" else self.nivel_de(s, self.p.nivel_inval)

    # --- Cada vela ---

    def al_cerrar_vela(self, vela):
        self.op.gestionar(vela)
        self.actualizar_swing(vela)
        self.buscar_entrada(vela)
        s = self.swing
        if s is not None and s.marca is not None and (s.valido or self.posicion):
            s.marca.fin = self.instante

    def actualizar_swing(self, vela):
        p = self.p
        s = self.swing
        if s is not None and s.orden and self.posicion:
            s.operado = True
        if s is not None and s.operado and not self.posicion:  # la operación ha terminado
            self.op.cancelar_pendientes()  # por si quedaba el segundo escalón
            s.operado = s.orden = False
            if not p.reentrada:
                self.invalidar(s)
        self.pivotes.actualizar(self.velas_de_pivotes())
        impulso = self.pivotes.impulso
        if impulso is not None and not self.posicion:  # con algo abierto se sigue con esa operación
            clave = (impulso[0].indice, impulso[1].indice)
            if clave != self.ultima_clave and clave not in self.muertas:
                self.ultima_clave = clave
                if not self.sigue_el_actual(self.swing, impulso):
                    self.op.cancelar_pendientes()
                    self.swing = self.nuevo_swing(*impulso, clave)
                    return
        s = self.swing
        if s is None or not s.valido or s.operado:
            return
        lado = s.lado
        mejor, peor = (vela.high, vela.low) if lado > 0 else (vela.low, vela.high)
        if (mejor - s.final_precio) * lado > 0:
            if p.reanclar:
                s.final_precio, s.final_t = mejor, vela.inicio
                if s.orden:
                    self.op.cancelar_pendientes()
                    s.orden = False
            else:
                self.invalidar(s, "Se fue sin entrar")
                return
        if (peor - self.precio_invalidacion(s)) * lado < 0:
            self.invalidar(s, "Pierde el nivel de invalidación")
        elif (peor - s.origen_precio) * lado < 0:
            self.invalidar(s, "Rompe el origen")
        elif p.max_velas_swing and len(self.velas_de_pivotes()) - s.nacio > p.max_velas_swing:
            self.invalidar(s, "Swing antiguo")

    def sigue_el_actual(self, s: Swing | None, impulso) -> bool:
        """Si el impulso nuevo no sustituye al swing vivo: es su propio retroceso, o (con reentrada) no lo supera."""
        if s is None or not s.valido:
            return False
        origen, final = impulso
        if origen.indice == s.clave[1]:
            return True  # el tramo de vuelta desde el final del swing es el retroceso que se espera
        if self.p.reentrada:
            supera = final.alto == (s.lado > 0) and (final.precio - s.final_precio) * s.lado > 0
            return not supera
        return False

    def nuevo_swing(self, origen, final, clave):
        p = self.p
        atr = self.atr(p.atr_periodo)
        if atr is None:
            return None
        tamano = abs(final.precio - origen.precio)
        if tamano < p.impulso_min_atr * atr or (p.impulso_max_atr and tamano > p.impulso_max_atr * atr):
            return None
        lado = 1 if final.alto else -1
        if (lado > 0 and p.lados == "solo cortos") or (lado < 0 and p.lados == "solo largos"):
            return None
        velas = self.velas_de_pivotes()
        swing = Swing(lado, origen.precio, a_fecha(velas.time[origen.indice]), final.precio, a_fecha(velas.time[final.indice]), clave)
        swing.nacio = len(velas)
        return swing

    def invalidar(self, s: Swing, motivo: str = ""):
        s.valido = False
        self.muertas.add(s.clave)
        self.ultima_clave = None  # el impulso que había quedado de lado vuelve a mirarse
        if s.orden and motivo and self.p.marcar:
            self.texto(motivo)
        self.op.cancelar_pendientes()

    # --- Entrar ---

    def buscar_entrada(self, vela):
        p = self.p
        s = self.swing
        if s is None or not s.valido or self.posicion:
            return
        pendiente = any(o.papel == "entrada" for o in self.ordenes)
        if s.orden and (pendiente or self.op.plan is not None):
            return  # esperando a que se ejecute
        s.orden = False
        lado = s.lado
        if not self.op.puede_abrir(lado):
            return
        cerca = self.redondear(self.nivel_de(s, p.nivel_entrada))
        fondo = self.redondear(self.nivel_de(s, p.zona_hasta))
        if p.entrada == "limite":
            precio = cerca if p.limite_en == "nivel_entrada" else fondo
            if (vela.close - precio) * lado > self.tick:
                self.colocar(s, vela, precio, tipo="limite", precio=precio)
        elif p.entrada == "escalonada":
            if (vela.close - cerca) * lado > self.tick:
                self.colocar(s, vela, (cerca + fondo) / 2, tipo="limite", escalones=[(cerca, 0.5), (fondo, 0.5)])
        else:
            borde = max(cerca, fondo) if lado > 0 else min(cerca, fondo)
            if (borde - (vela.low if lado > 0 else vela.high)) * lado >= 0:
                s.toco = True
            if not s.toco or (vela.close - borde) * lado <= 0 or (vela.close - vela.open) * lado <= 0:
                return
            if self.confirma(lado):
                s.toco = False
                self.colocar(s, vela, vela.close + (self.tick if lado > 0 else 0), tipo="mercado")

    def confirma(self, lado: int) -> bool:
        p = self.p
        if p.confirma_ema:
            media = self.ema(p.confirma_ema_periodo)
            if media is None or (self.velas[-1].close - media) * lado <= 0:
                return False
        if p.confirma_rsi:
            valores = [v for v in (self.rsi(p.rsi_periodo, atras) for atras in range(3)) if v is not None]
            if not valores:
                return False
            if (lado > 0 and min(valores) > p.rsi_nivel) or (lado < 0 and max(valores) < 100 - p.rsi_nivel):
                return False
        return True

    def colocar(self, s: Swing, vela, entrada: float, tipo: str, precio: float | None = None, escalones=None) -> bool:
        p = self.p
        lado = s.lado
        stop = self.elegir_stop(s, entrada)
        if stop is None or (entrada - stop) * lado < self.tick:
            return False
        objetivos = self.elegir_objetivos(s, entrada)
        if not objetivos:
            return False
        motivo = f"Retroceso a Fibonacci {p.nivel_entrada}"
        if not self.op.entrar(lado, stop, objetivos, tipo=tipo, precio=precio, motivo=motivo, escalones=escalones):
            return False
        s.orden = True
        if s.marca is None and p.marcar:
            s.marca = self.fibonacci(
                (s.origen_t, s.origen_precio), (s.final_t, s.final_precio), self.retrocesos_marca, self.extensiones_marca, "Impulso"
            )
            self.texto("Orden " + ("larga" if lado > 0 else "corta"))
            self.nivel(stop, "Stop")
        return True

    def elegir_stop(self, s: Swing, entrada: float):
        p = self.p
        lado = s.lado
        if p.stop_ref == "atr":
            atr = self.atr(p.atr_periodo)
            return None if atr is None else self.redondear(entrada - lado * p.stop_atr_n * atr)
        base = s.origen_precio if p.stop_ref == "origen" else self.precio_invalidacion(s)
        atr = self.atr(p.atr_periodo) or 0.0
        margen = p.stop_margen_ticks * self.tick + p.stop_margen_atr * atr
        return self.redondear(base - lado * margen)

    def elegir_objetivos(self, s: Swing, entrada: float) -> list[tuple]:
        """(precio, fracción) de cada tramo que queda por delante de la entrada."""
        p = self.p
        if p.objetivos_modo == "unico":
            pares = [(self.extension_de(s, p.extension_unica), 1.0)]
        else:
            pares = [(self.extension_de(s, e), f) for e, f in zip(self.exts, self.fracs)]
        pares = [(self.redondear(precio), f) for precio, f in pares if (precio - entrada) * s.lado >= self.tick]
        if pares and p.objetivos_modo == "tramos con trailing":
            pares[-1] = (None, pares[-1][1])
        return pares
