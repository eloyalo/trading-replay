"""Cruce de medias.

Dos medias exponenciales del cierre: una rápida y una lenta.
Entrada: cuando la rápida cruza la lenta hacia arriba se compra; hacia abajo, se vende. Solo si no hay ya una posición abierta.
Stop a `atr_sl` veces el ATR de 14 velas desde la entrada; objetivo a `objetivo_r` veces el riesgo.
Con `solo_nueva_york`, solo entra de 9:30 a 15:45 ET y cierra lo que siga abierto a las 16:00.
"""

from trading_replay.backtest import Estrategia, Parametro


class CruceMedias(Estrategia):
    nombre = "Cruce de medias"
    timeframe = "15m"
    parametros = {
        "rapida": Parametro(9, "Velas de la EMA rápida", minimo=2, maximo=100),
        "lenta": Parametro(21, "Velas de la EMA lenta", minimo=3, maximo=300),
        "atr_sl": Parametro(1.5, "SL en ATR(14)", minimo=0.5, maximo=10, paso=0.5),
        "objetivo_r": Parametro(2.0, "Objetivo en R", minimo=0.5, maximo=10, paso=0.5),
        "contratos": Parametro(1, "Contratos", minimo=1, maximo=10),
        "solo_nueva_york": Parametro(True, "Solo en la sesión de Nueva York"),
    }

    def al_cerrar_vela(self, vela):
        # A las 16:00 se cierra lo que siga abierto (de 16:00 a 18:00 el mercado está parado).
        if self.p.solo_nueva_york and "16:00" <= self.hora < "18:00":
            if self.posicion:
                self.cerrar("16:00")
            return

        rapida, lenta = self.ema(self.p.rapida), self.ema(self.p.lenta)
        rapida_antes, lenta_antes = self.ema(self.p.rapida, atras=1), self.ema(self.p.lenta, atras=1)
        atr = self.atr(14)
        # Al principio del histórico las medias todavía no tienen valor.
        if None in (rapida, lenta, rapida_antes, lenta_antes, atr):
            return
        if self.posicion:
            return
        if self.p.solo_nueva_york and not self.entre("09:30", "15:45"):
            return

        cruza_arriba = rapida_antes <= lenta_antes and rapida > lenta
        cruza_abajo = rapida_antes >= lenta_antes and rapida < lenta
        distancia = self.p.atr_sl * atr
        if cruza_arriba:
            self.comprar(self.p.contratos, sl=vela.close - distancia, tp_r=self.p.objetivo_r, motivo="La EMA rápida cruza hacia arriba")
            self.nivel(vela.close - distancia, "SL a ATR")
        elif cruza_abajo:
            self.vender(self.p.contratos, sl=vela.close + distancia, tp_r=self.p.objetivo_r, motivo="La EMA rápida cruza hacia abajo")
            self.nivel(vela.close + distancia, "SL a ATR")
