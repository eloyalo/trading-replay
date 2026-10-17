"""Ruptura del rango de apertura.

Rango: máximo y mínimo de los primeros `minutos_rango` minutos desde las 9:30 ET.
Entrada: una vela de 5m que cierra por encima del máximo compra; por debajo del mínimo, vende.
Stop al otro lado del rango; objetivo a `objetivo_r` veces el riesgo. Una operación al día.
Si a las 16:00 sigue abierta, se cierra.
"""

from trading_replay.backtest import Estrategia, Parametro


class RupturaRango(Estrategia):
    nombre = "Ruptura del rango de apertura"
    timeframe = "5m"
    parametros = {
        "minutos_rango": Parametro(15, "Minutos del rango desde las 9:30", minimo=5, maximo=120, paso=5),
        "objetivo_r": Parametro(2.0, "Objetivo en R", minimo=0.5, maximo=10, paso=0.5),
        "contratos": Parametro(1, "Contratos", minimo=1, maximo=10),
    }

    def al_empezar_dia(self):
        self.alto = self.bajo = None
        self.operado_hoy = False

    def al_cerrar_vela(self, vela):
        fin_rango = self.hora_mas("09:30", self.p.minutos_rango)
        # Mientras dura el rango, se van guardando el máximo y el mínimo.
        if self.entre("09:30", fin_rango):
            self.alto = vela.high if self.alto is None else max(self.alto, vela.high)
            self.bajo = vela.low if self.bajo is None else min(self.bajo, vela.low)
            if self.hora == fin_rango:
                self.rango("09:30", fin_rango, self.alto, self.bajo, "Rango de apertura")
            return
        # Antes de las 9:30 (o un día sin rango) no hay nada que hacer.
        if self.alto is None:
            return
        # A las 16:00, fuera.
        if self.hora >= "16:00":
            if self.posicion:
                self.cerrar("16:00")
            return
        if self.operado_hoy or self.posicion:
            return
        if vela.close > self.alto:
            self.comprar(self.p.contratos, sl=self.bajo, tp_r=self.p.objetivo_r, motivo="Cierra por encima del rango")
            self.operado_hoy = True
        elif vela.close < self.bajo:
            self.vender(self.p.contratos, sl=self.alto, tp_r=self.p.objetivo_r, motivo="Cierra por debajo del rango")
            self.operado_hoy = True
