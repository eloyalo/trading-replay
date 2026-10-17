"""Danny strategy (versión 1: zonas de oferta y demanda y sus niveles).

Basada en el vídeo "The Only Futures Trading Strategy You Need" de Dannystrades. Lo que dice el vídeo:
- Una zona la forma una vela pequeña de color contrario (vela base) seguida de un movimiento agresivo. El cuerpo de la vela base es menos de la mitad del de la agresiva, y la agresiva no tiene una mecha grande en contra.
- La zona va de la apertura de la vela base a la mecha más extrema de las dos velas. Tiene tres niveles: el borde (nivel 1), el 50 % y el borde opuesto (nivel 3). El AOI es la mecha de la vela base, antes de la zona.
- Si el precio rompe el 50 %, la zona deja de valer.
- Se entra a mercado al ver la reacción en un nivel, no con órdenes límite. Stop de 100 ticks como mucho.

Lo que se ha decidido para poder programarlo (la versión 1 la eligió el usuario el 2026-10-17):
- Zonas de 15m, 30m, 1h y 4h, armadas con velas de 5m. Entrada en 5m.
- Reacción = una vela de 5m que toca el AOI, el nivel 1 o el 50 % y cierra de vuelta a favor.
- Stop al otro lado de la zona; si pasa de 100 ticks, no se entra. Objetivo a 2 R; la mitad a 1 R y el resto con el stop en break-even.
- Solo entra de 9:30 a 15:45 ET y cierra lo que siga abierto a las 16:00.
- Una operación por zona y una posición a la vez.
Elegido por Claude, porque el vídeo no da números: qué es "agresivo", cuánta mecha en contra es "grande" y cuánto tiempo se guarda una zona. Están en los parámetros.
Fuera de esta versión: splits, desequilibrios, VWAP, trampas en el 50 % y añadir contratos.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from trading_replay.backtest import Estrategia, OrdenNoValida, Parametro

# Del timeframe más fiable al menos fiable: si el precio reacciona en varias zonas a la vez, manda la mayor.
TIMEFRAMES_ZONAS = ("4h", "1h", "30m", "15m")


@dataclass
class Zona:
    tipo: str  # "demanda" (se espera rebote hacia arriba) u "oferta" (hacia abajo)
    timeframe: str
    inicio: datetime  # inicio de la vela base, para dibujarla
    creada: datetime  # cierre de la vela agresiva
    aoi: float  # mecha de la vela base: primer sitio donde se espera reacción
    nivel1: float  # apertura de la vela base: borde de entrada de la zona
    medio: float  # el 50 %: si el precio lo rompe, la zona deja de valer
    nivel3: float  # mecha más extrema: el otro borde, detrás va el stop
    operada: bool = False


class DannyStrategy(Estrategia):
    nombre = "Danny strategy"
    timeframe = "5m"
    parametros = {
        "zonas_4h": Parametro(True, "Zonas de 4h"),
        "zonas_1h": Parametro(True, "Zonas de 1h"),
        "zonas_30m": Parametro(True, "Zonas de 30m"),
        "zonas_15m": Parametro(True, "Zonas de 15m"),
        "usar_aoi": Parametro(True, "Entrar también en el AOI"),
        "agresiva": Parametro(2.0, "Vela agresiva: cuerpo, en veces la media de las 20 anteriores", minimo=1.0, maximo=5.0, paso=0.25),
        "base_max": Parametro(0.5, "Vela base: cuerpo máximo, en parte del de la agresiva", minimo=0.1, maximo=1.0, paso=0.05),
        "mecha_max": Parametro(0.3, "Vela agresiva: mecha en contra máxima, en parte de su rango", minimo=0.05, maximo=1.0, paso=0.05),
        "dias_zona": Parametro(20, "Días que se guarda una zona sin usar", minimo=1, maximo=200),
        "stop_max_ticks": Parametro(100, "Stop máximo (ticks)", minimo=10, maximo=400, paso=10),
        "margen_stop_ticks": Parametro(2, "Margen del stop detrás de la zona (ticks)", minimo=0, maximo=40),
        "objetivo_r": Parametro(2.0, "Objetivo en R", minimo=0.5, maximo=10, paso=0.5),
        "parcial_r": Parametro(1.0, "Toma parcial (la mitad) en R", minimo=0.25, maximo=10, paso=0.25),
        "contratos": Parametro(2, "Contratos", minimo=1, maximo=20),
    }

    def al_empezar(self):
        self.zonas: list[Zona] = []
        self.velas_vistas = {tf: 0 for tf in TIMEFRAMES_ZONAS}  # velas de cada timeframe ya revisadas
        self.en_break_even = False

    def al_cerrar_vela(self, vela):
        self.buscar_zonas_nuevas()
        self.quitar_zonas_rotas(vela)

        if self.posicion:
            self.gestionar_posicion()
            return
        # Solo se entra en la sesión de Nueva York, y no en el último cuarto de hora.
        if self.entre("09:30", "15:45"):
            self.buscar_entrada(vela)

    # --- Zonas ---

    def buscar_zonas_nuevas(self):
        """Cada vez que cierra una vela de 15m, 30m, 1h o 4h, mira si con la anterior forma una zona."""
        for tf in TIMEFRAMES_ZONAS:
            if not getattr(self.p, f"zonas_{tf}"):
                continue
            velas = self.velas_de(tf)
            if len(velas) == self.velas_vistas[tf]:
                continue  # no ha cerrado ninguna vela nueva de este timeframe
            self.velas_vistas[tf] = len(velas)
            if len(velas) < 22:
                continue  # hacen falta 20 velas previas para saber qué es un cuerpo "normal"
            zona = self.zona_con(velas[-2], velas[-1], velas, tf)
            if zona:
                self.zonas.append(zona)

    def zona_con(self, base, agresiva, velas, tf):
        """La zona que forman la vela base y la agresiva, o None si no la forman."""
        cuerpo_base = abs(base.close - base.open)
        cuerpo_agresiva = abs(agresiva.close - agresiva.open)
        rango_agresiva = agresiva.high - agresiva.low
        # Movimiento agresivo: cuerpo mucho mayor que los de las 20 velas anteriores.
        anteriores = [abs(c - o) for o, c in zip(velas.open[-22:-2], velas.close[-22:-2])]
        media = sum(anteriores) / len(anteriores)
        if media == 0 or cuerpo_agresiva < self.p.agresiva * media:
            return None
        # La vela base es pequeña al lado de la agresiva.
        if cuerpo_base > self.p.base_max * cuerpo_agresiva:
            return None

        base_roja, agresiva_verde = base.close < base.open, agresiva.close > agresiva.open
        if base_roja and agresiva_verde:
            # Demanda: la agresiva no puede tener una mecha grande arriba (vendedores que la frenan).
            if agresiva.high - agresiva.close > self.p.mecha_max * rango_agresiva:
                return None
            nivel1, nivel3, aoi, tipo = base.open, min(base.low, agresiva.low), base.high, "demanda"
        elif not base_roja and base.close != base.open and not agresiva_verde:
            # Oferta: lo mismo al revés.
            if agresiva.close - agresiva.low > self.p.mecha_max * rango_agresiva:
                return None
            nivel1, nivel3, aoi, tipo = base.open, max(base.high, agresiva.high), base.low, "oferta"
        else:
            return None  # la vela base tiene que ser de color contrario al movimiento
        return Zona(tipo, tf, base.inicio, agresiva.fin, aoi, nivel1, (nivel1 + nivel3) / 2, nivel3)

    def quitar_zonas_rotas(self, vela):
        """Una zona deja de valer si una vela cierra más allá de su 50 %, o si lleva demasiado sin usarse."""
        limite = self.instante - timedelta(days=self.p.dias_zona)
        self.zonas = [
            z
            for z in self.zonas
            if z.creada >= limite and (vela.close > z.medio if z.tipo == "demanda" else vela.close < z.medio)
        ]

    # --- Entrada ---

    def buscar_entrada(self, vela):
        for zona in sorted(self.zonas, key=lambda z: TIMEFRAMES_ZONAS.index(z.timeframe)):
            if zona.operada or zona.creada >= self.instante:
                continue  # una operación por zona, y nunca con la vela que la acaba de formar
            nivel = self.nivel_con_reaccion(zona, vela)
            if nivel is None:
                continue
            if self.entrar(zona, nivel, vela):
                return

    def nivel_con_reaccion(self, zona, vela):
        """El nivel más profundo que la vela ha tocado y del que ha cerrado de vuelta, o None.
        En demanda: el mínimo llega al nivel y el cierre queda por encima. En oferta, al revés."""
        niveles = [("el 50 %", zona.medio), ("el nivel 1", zona.nivel1)]
        if self.p.usar_aoi:
            niveles.append(("el AOI", zona.aoi))
        for nombre, precio in niveles:  # del más profundo al menos profundo
            if zona.tipo == "demanda" and vela.low <= precio < vela.close:
                return nombre
            if zona.tipo == "oferta" and vela.high >= precio > vela.close:
                return nombre
        return None

    def entrar(self, zona, nivel, vela):
        """Entra a mercado con el stop detrás de la zona. Devuelve si ha entrado."""
        margen = self.p.margen_stop_ticks * self.tick
        largo = zona.tipo == "demanda"
        stop = zona.nivel3 - margen if largo else zona.nivel3 + margen
        # Si el stop queda a más de 100 ticks (o lo elegido), la zona es demasiado grande para esta entrada.
        if abs(vela.close - stop) / self.tick > self.p.stop_max_ticks:
            return False

        motivo = f"Rechazo en {nivel} de {zona.tipo} de {zona.timeframe}"
        if largo:
            self.comprar(self.p.contratos, sl=stop, tp_r=self.p.objetivo_r, motivo=motivo)
        else:
            self.vender(self.p.contratos, sl=stop, tp_r=self.p.objetivo_r, motivo=motivo)
        zona.operada = True
        self.en_break_even = False
        self.dibujar(zona)

        # La mitad sale a 1 R (o lo elegido) con una orden límite.
        if self.posicion and self.p.contratos >= 2:
            riesgo = abs(self.precio_entrada - stop)
            parcial = self.precio_entrada + self.p.parcial_r * riesgo * (1 if largo else -1)
            self.tomar_parcial(self.p.contratos // 2, parcial)
        return True

    def dibujar(self, zona):
        borde = zona.aoi if self.p.usar_aoi else zona.nivel1
        self.rango(zona.inicio, self.instante, borde, zona.nivel3, f"{zona.tipo.capitalize()} {zona.timeframe}")
        self.rango(zona.inicio, self.instante, zona.medio, zona.medio, "50 %")
        self.rango(zona.inicio, self.instante, zona.nivel1, zona.nivel1, "Nivel 1")

    # --- Gestión ---

    def gestionar_posicion(self):
        # A las 16:00, fuera.
        if self.hora >= "16:00":
            self.cerrar("16:00")
            return
        # Tras la toma parcial, el resto con el stop en el precio de entrada.
        if not self.en_break_even and abs(self.posicion) < self.p.contratos:
            try:
                self.mover_sl(self.precio_entrada)
            except OrdenNoValida:
                self.cerrar("Break-even")  # el precio ya ha vuelto a la entrada: el stop no cabe ahí
            self.en_break_even = True
