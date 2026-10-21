"""EMA pullback: operar a favor de la tendencia cuando el precio retrocede a una media y se gira.

Tendencia: con las medias apiladas (rápida > media > lenta en largos) y el precio al lado bueno de la lenta,
más los filtros que se activen (pendiente, tendencia de un timeframe mayor, distancia entre medias).
Pullback: una vela toca, cierra más allá o entra en la banda de la media elegida (por defecto la de 20).
Entrada: una vela a favor que cierra por encima de la media rápida, en las siguientes 3 velas (o en la misma).
Stop: bajo el mínimo del pullback, y objetivo a 2 R. Todo se puede cambiar: medias, filtros, contacto,
entrada (al cierre, por ruptura o con límite en la media), stops y objetivos, parcial, break-even, trailing,
sesiones y límites. Los cortos son el espejo de los largos.
"""

from trading_replay.backtest import TIMEFRAMES, Estrategia, Parametro, ParametroNoValido
from trading_replay.backtest.comunes import Operativa, parametros_gestion, parametros_operativa, parametros_sesion

MEDIAS = ("rapida", "media", "lenta")
G_MEDIAS, G_TENDENCIA, G_PULLBACK, G_ENTRADA, G_SALIDA = "Medias", "Tendencia", "Pullback", "Entrada", "Stop y objetivo"


class EmaPullback(Estrategia):
    nombre = "EMA pullback"
    timeframe = "5m"
    parametros = {
        "timeframe": Parametro("5m", "Timeframe", opciones=list(TIMEFRAMES), grupo="General"),
        "marcar": Parametro(True, "Marcar toques, entradas y stops en el gráfico", grupo="General"),
        "atr_periodo": Parametro(14, "Periodo del ATR", minimo=2, maximo=200, grupo="General"),
        # Medias (periodo 0 = desactivada)
        "tipo_media": Parametro("ema", "Tipo de media", opciones=["ema", "sma"], grupo=G_MEDIAS),
        "periodo_rapida": Parametro(9, "Media rápida (0 = no)", minimo=0, maximo=500, grupo=G_MEDIAS),
        "periodo_media": Parametro(20, "Media intermedia (0 = no)", minimo=0, maximo=500, grupo=G_MEDIAS),
        "periodo_lenta": Parametro(50, "Media lenta (0 = no)", minimo=0, maximo=1000, grupo=G_MEDIAS),
        # Tendencia
        "f_apiladas": Parametro(True, "Medias apiladas", grupo=G_TENDENCIA),
        "f_precio_lenta": Parametro(True, "Precio al lado bueno de la media lenta", grupo=G_TENDENCIA),
        "f_pendiente": Parametro(False, "Pendiente de una media a favor", grupo=G_TENDENCIA),
        "pendiente_media": Parametro("media", "Media de la pendiente", opciones=list(MEDIAS), grupo=G_TENDENCIA),
        "pendiente_velas": Parametro(3, "Velas para medir la pendiente", minimo=1, maximo=100, grupo=G_TENDENCIA),
        "f_tf_mayor": Parametro(False, "Tendencia de un timeframe mayor", grupo=G_TENDENCIA),
        "tf_mayor": Parametro("1h", "Timeframe mayor", opciones=["15m", "30m", "1h", "4h"], grupo=G_TENDENCIA),
        "periodo_tf_mayor": Parametro(50, "EMA del timeframe mayor", minimo=2, maximo=500, grupo=G_TENDENCIA),
        "f_distancia": Parametro(False, "Distancia mínima entre rápida y lenta", grupo=G_TENDENCIA),
        "distancia_min_atr": Parametro(0.5, "Distancia mínima (en ATR)", minimo=0, maximo=20, paso=0.1, grupo=G_TENDENCIA),
        # Pullback
        "media_objetivo": Parametro("media", "Media del pullback", opciones=[*MEDIAS, "media o lenta"], grupo=G_PULLBACK),
        "contacto": Parametro("toca", "Contacto", opciones=["toca", "cierra mas alla", "banda"], grupo=G_PULLBACK),
        "banda_atr": Parametro(0.25, "Banda / holgura del contacto (en ATR)", minimo=0, maximo=20, paso=0.05, grupo=G_PULLBACK),
        "primer_pullback": Parametro(True, "Solo el primer contacto (la vela anterior no tocó la media)", grupo=G_PULLBACK),
        "min_velas_retroceso": Parametro(0, "Mínimo de velas de retroceso seguidas", minimo=0, maximo=100, grupo=G_PULLBACK),
        "max_velas_retroceso": Parametro(10, "Máximo de velas de retroceso seguidas (0 = sin límite)", minimo=0, maximo=100, grupo=G_PULLBACK),
        "max_velas_confirmacion": Parametro(3, "Velas que puede tardar la confirmación tras el toque", minimo=0, maximo=50, grupo=G_PULLBACK),
        # Entrada
        "entrada": Parametro("cierre", "Entrada", opciones=["cierre", "ruptura", "limite"], grupo=G_ENTRADA),
        "confirma_sobre": Parametro("rapida", "La vela de confirmación cierra sobre", opciones=["rapida", "media objetivo", "ninguna"], grupo=G_ENTRADA),
        "cuerpo_min_pct": Parametro(0, "Cuerpo mínimo de la vela de confirmación (% del rango, 0 = no)", minimo=0, maximo=100, grupo=G_ENTRADA),
        "vela_max_atr": Parametro(0.0, "Vela de confirmación como mucho de N ATR (0 = no)", minimo=0, maximo=20, paso=0.1, grupo=G_ENTRADA),
        "max_velas_orden": Parametro(3, "Velas que vive una orden de ruptura o límite", minimo=1, maximo=100, grupo=G_ENTRADA),
        # Stop y objetivo
        "stop_pullback": Parametro(True, "Stop tras el extremo del pullback", grupo=G_SALIDA),
        "stop_lenta": Parametro(False, "Stop tras la media lenta (o la última activa)", grupo=G_SALIDA),
        "stop_atr": Parametro(False, "Stop a N ATR de la entrada", grupo=G_SALIDA),
        "stop_puntos": Parametro(False, "Stop a N puntos de la entrada", grupo=G_SALIDA),
        "stop_modo": Parametro("mas cercano", "Con varios stops activos, vale el", opciones=["mas cercano", "mas lejano"], grupo=G_SALIDA),
        "stop_margen_ticks": Parametro(2, "Margen del stop (ticks)", minimo=0, maximo=500, grupo=G_SALIDA),
        "stop_atr_n": Parametro(1.5, "ATR del stop", minimo=0.1, maximo=20, paso=0.1, grupo=G_SALIDA),
        "stop_puntos_n": Parametro(20.0, "Puntos del stop", minimo=0.25, maximo=2000, paso=0.25, grupo=G_SALIDA),
        "stop_max_ticks": Parametro(0, "No operar si el stop pasa de N ticks (0 = sin límite)", minimo=0, maximo=5000, grupo=G_SALIDA),
        "objetivo": Parametro("r", "Objetivo", opciones=["r", "swing", "atr", "ninguno"], grupo=G_SALIDA),
        "objetivo_r": Parametro(2.0, "Objetivo en R", minimo=0.25, maximo=20, paso=0.25, grupo=G_SALIDA),
        "objetivo_atr_n": Parametro(3.0, "Objetivo en ATR", minimo=0.25, maximo=50, paso=0.25, grupo=G_SALIDA),
        "swing_velas": Parametro(20, "Velas para buscar el swing anterior", minimo=2, maximo=500, grupo=G_SALIDA),
        "objetivo_min_r": Parametro(1.0, "No operar si el objetivo da menos de N R", minimo=0, maximo=20, paso=0.25, grupo=G_SALIDA),
        "parcial": Parametro(False, "Toma parcial", grupo=G_SALIDA),
        "parcial_r": Parametro(1.0, "Parcial a N R", minimo=0.25, maximo=20, paso=0.25, grupo=G_SALIDA),
        "parcial_fraccion": Parametro(0.5, "Fracción que se cierra en la parcial", minimo=0.1, maximo=0.9, paso=0.1, grupo=G_SALIDA),
        "salida_cierra_lenta": Parametro(False, "Salir si una vela cierra al otro lado de la media lenta", grupo=G_SALIDA),
        "salida_cruce": Parametro(False, "Salir si la rápida cruza la intermedia en contra", grupo=G_SALIDA),
        **parametros_sesion(),
        **parametros_operativa(),
        **parametros_gestion(),
    }

    def al_empezar(self):
        p = self.p
        self.op = Operativa(self)
        self.medias = {"rapida": p.periodo_rapida, "media": p.periodo_media, "lenta": p.periodo_lenta}
        activas = [clave for clave in MEDIAS if self.medias[clave]]
        if not activas:
            raise ParametroNoValido("Hace falta al menos una media activa")
        objetivo = ("media", "lenta") if p.media_objetivo == "media o lenta" else (p.media_objetivo,)
        if not all(self.medias[clave] for clave in objetivo):
            raise ParametroNoValido(f"La media del pullback («{p.media_objetivo}») está desactivada (periodo 0)")
        self.objetivo_medias = objetivo
        self.lenta = "lenta" if self.medias["lenta"] else activas[-1]
        self.rapida = "rapida" if self.medias["rapida"] else activas[0]
        if p.f_pendiente and not self.medias[p.pendiente_media]:
            raise ParametroNoValido(f"La media de la pendiente («{p.pendiente_media}») está desactivada")
        if p.entrada == "limite" and p.stop_pullback and not (p.stop_lenta or p.stop_atr or p.stop_puntos):
            raise ParametroNoValido("Con entrada límite el stop no puede ser el del pullback (aún no existe): activa otro stop")
        if not (p.stop_pullback or p.stop_lenta or p.stop_atr or p.stop_puntos):
            raise ParametroNoValido("Hace falta al menos un stop activo")
        if p.f_tf_mayor:
            try:
                self.velas_de(p.tf_mayor)
            except ValueError as error:
                raise ParametroNoValido(f"Timeframe mayor: {error}") from None
        self.pullback = {1: None, -1: None}
        self.orden_desde = None
        self._mayor = [0, None]  # velas del timeframe mayor ya vistas y su EMA

    # --- Cálculos ---

    def media(self, clave: str, atras: int = 0):
        periodo = self.medias[clave]
        return self.ema(periodo, atras) if self.p.tipo_media == "ema" else self.sma(periodo, atras)

    def ema_mayor(self):
        """EMA de los cierres del timeframe mayor (solo velas mayores ya cerradas)."""
        velas = self.velas_de(self.p.tf_mayor)
        visto, valor = self._mayor
        alfa = 2 / (self.p.periodo_tf_mayor + 1)
        for cierre in velas.close[visto:]:
            valor = cierre if valor is None else valor + alfa * (cierre - valor)
        self._mayor = [len(velas), valor]
        return valor if len(velas) >= self.p.periodo_tf_mayor else None

    def tendencia(self, lado: int, vela) -> bool:
        p = self.p
        valores = [self.media(clave) for clave in MEDIAS if self.medias[clave]]
        if any(v is None for v in valores):
            return False
        if p.f_apiladas and any((a - b) * lado <= 0 for a, b in zip(valores, valores[1:])):
            return False
        if p.f_precio_lenta and (vela.close - self.media(self.lenta)) * lado <= 0:
            return False
        if p.f_pendiente:
            antes = self.media(p.pendiente_media, p.pendiente_velas)
            if antes is None or (self.media(p.pendiente_media) - antes) * lado <= 0:
                return False
        if p.f_distancia:
            atr = self.atr(p.atr_periodo)
            if atr is None or (self.media(self.rapida) - self.media(self.lenta)) * lado < p.distancia_min_atr * atr:
                return False
        if p.f_tf_mayor:
            mayor = self.ema_mayor()
            velas = self.velas_de(p.tf_mayor)
            if mayor is None or (velas.close[-1] - mayor) * lado <= 0:
                return False
        return True

    def toca(self, lado: int, vela, atras: int = 0) -> str | None:
        """La media del pullback que toca la vela `atras` velas antes, según el contacto elegido, o None."""
        p = self.p
        atr = self.atr(p.atr_periodo, atras)
        holgura = p.banda_atr * atr if atr is not None else 0.0
        for clave in self.objetivo_medias:
            m = self.media(clave, atras)
            if m is None:
                continue
            if p.contacto == "toca":
                hecho = vela.low <= m if lado > 0 else vela.high >= m
            elif p.contacto == "cierra mas alla":
                hecho = (m - holgura <= vela.close < m) if lado > 0 else (m < vela.close <= m + holgura)
            else:
                hecho = vela.low <= m + holgura and vela.high >= m - holgura
            if hecho:
                return clave
        return None

    def velas_en_contra(self, lado: int) -> int:
        """Velas seguidas, hasta la última, que cierran contra la tendencia respecto a la anterior."""
        cierres, n = self.velas.close, 0
        while n < len(cierres) - 1 and (cierres[-1 - n] - cierres[-2 - n]) * lado < 0:
            n += 1
        return n

    # --- Cada vela ---

    def al_cerrar_vela(self, vela):
        self.op.gestionar(vela)
        self.salir_por_senal()
        self.caducar_ordenes()
        for lado in (1, -1):
            if self.p.lados == "solo largos" and lado < 0 or self.p.lados == "solo cortos" and lado > 0:
                continue
            if self.p.entrada == "limite":
                self.preparar_limite(lado, vela)
            else:
                self.revisar(lado, vela)

    def salir_por_senal(self):
        p = self.p
        if not self.posicion or not (p.salida_cierra_lenta or p.salida_cruce):
            return
        lado = 1 if self.posicion > 0 else -1
        if p.salida_cierra_lenta:
            lenta = self.media(self.lenta)
            if lenta is not None and (self.velas[-1].close - lenta) * lado < 0:
                self.cerrar("Cierre al otro lado de la media lenta")
                return
        if p.salida_cruce and self.medias["rapida"] and self.medias["media"]:
            ahora = self.media("rapida") - self.media("media")
            antes_r, antes_m = self.media("rapida", 1), self.media("media", 1)
            if antes_r is not None and antes_m is not None and ahora * lado < 0 <= (antes_r - antes_m) * lado:
                self.cerrar("Cruce de medias en contra")

    def caducar_ordenes(self):
        if self.orden_desde is None:
            return
        pendiente = any(o.papel == "entrada" for o in self.ordenes)
        if not pendiente:
            self.orden_desde = None
        elif len(self.velas) - self.orden_desde > self.p.max_velas_orden:
            self.cancelar()
            self.orden_desde = None

    def revisar(self, lado: int, vela):
        """Busca el contacto con la media y, tras él, la vela que confirma."""
        p = self.p
        indice = len(self.velas) - 1
        estado = self.pullback[lado]
        if estado is not None:
            estado["extremo"] = min(estado["extremo"], vela.low) if lado > 0 else max(estado["extremo"], vela.high)
            if indice - estado["inicio"] > p.max_velas_confirmacion:
                estado = self.pullback[lado] = None
        if estado is None:
            clave = self.toca(lado, vela)
            if clave is None or not self.tendencia(lado, vela):
                return
            if p.primer_pullback and len(self.velas) > 1 and self.toca(lado, self.velas[-2], atras=1):
                return
            n = self.velas_en_contra(lado)
            if n < p.min_velas_retroceso or (p.max_velas_retroceso and n > p.max_velas_retroceso):
                return
            extremo = vela.low if lado > 0 else vela.high
            estado = self.pullback[lado] = {"inicio": indice, "extremo": extremo, "media": clave}
            if p.marcar:
                self.texto("Toque", self.media(clave))
        if not self.confirma(lado, vela, estado):
            return
        self.pullback[lado] = None
        if self.tendencia(lado, vela) and self.op.puede_abrir(lado):
            self.abrir(lado, vela, estado)

    def confirma(self, lado: int, vela, estado) -> bool:
        p = self.p
        if (vela.close - vela.open) * lado <= 0:
            return False
        if p.confirma_sobre != "ninguna":
            clave = self.rapida if p.confirma_sobre == "rapida" else estado["media"]
            if (vela.close - self.media(clave)) * lado <= 0:
                return False
        rango = vela.high - vela.low
        if p.cuerpo_min_pct and (rango <= 0 or abs(vela.close - vela.open) / rango * 100 < p.cuerpo_min_pct):
            return False
        if p.vela_max_atr:
            atr = self.atr(p.atr_periodo)
            if atr is None or rango > p.vela_max_atr * atr:
                return False
        return True

    def preparar_limite(self, lado: int, vela):
        """Entrada con orden límite en la media del pullback, mientras el precio sigue de su lado."""
        p = self.p
        if not self.op.puede_abrir(lado) or not self.tendencia(lado, vela):
            return
        clave = self.objetivo_medias[0]
        m = self.media(clave)
        precio = round(m / self.tick) * self.tick
        if (vela.close - precio) * lado <= self.tick:
            return  # el precio ya está en la media o al otro lado: el límite se ejecutaría en el acto
        if self.abrir(lado, vela, {"media": clave, "extremo": None}, tipo="limite", precio=precio):
            self.orden_desde = len(self.velas) - 1

    # --- Entrar ---

    def abrir(self, lado: int, vela, estado, tipo: str | None = None, precio: float | None = None) -> bool:
        p = self.p
        tipo = tipo or ("mercado" if p.entrada == "cierre" else "stop")
        if tipo == "stop":
            precio = vela.high + self.tick if lado > 0 else vela.low - self.tick
        entrada = precio if precio is not None else vela.close + (self.tick if lado > 0 else 0)  # a mercado: compra al ASK, venta al BID
        atr = self.atr(p.atr_periodo)
        stop = self.elegir_stop(lado, entrada, estado, atr)
        if stop is None:
            return False
        riesgo = abs(entrada - stop)
        if p.stop_max_ticks and riesgo / self.tick > p.stop_max_ticks:
            return False
        final = self.elegir_objetivo(lado, entrada, riesgo, estado, atr)
        if final == "descartado":
            return False
        objetivos = [(final, 1.0)]
        if p.parcial and final is not None:
            objetivos.insert(0, (entrada + lado * p.parcial_r * riesgo, p.parcial_fraccion))
            objetivos[1] = (final, 1 - p.parcial_fraccion)
        motivo = f"Pullback a la media de {self.medias[estado['media']]}"
        if not self.op.entrar(lado, stop, objetivos, tipo=tipo, precio=precio, motivo=motivo):
            return False
        if tipo == "stop":
            self.orden_desde = len(self.velas) - 1
        if p.marcar:
            self.texto("Entrada " + ("larga" if lado > 0 else "corta"))
            self.nivel(stop, "Stop")
        return True

    def elegir_stop(self, lado: int, entrada: float, estado, atr):
        p = self.p
        margen = p.stop_margen_ticks * self.tick
        candidatos = []
        if p.stop_pullback and estado["extremo"] is not None:
            candidatos.append(estado["extremo"] - lado * margen)
        if p.stop_lenta:
            lenta = self.media(self.lenta)
            if lenta is not None:
                candidatos.append(lenta - lado * margen)
        if p.stop_atr and atr is not None:
            candidatos.append(entrada - lado * p.stop_atr_n * atr)
        if p.stop_puntos:
            candidatos.append(entrada - lado * p.stop_puntos_n)
        validos = [round(s / self.tick) * self.tick for s in candidatos if (entrada - s) * lado >= self.tick]
        if not validos:
            return None
        cerca = min if p.stop_modo == "mas cercano" else max
        return cerca(validos, key=lambda s: abs(entrada - s))

    def elegir_objetivo(self, lado: int, entrada: float, riesgo: float, estado, atr):
        """El precio del objetivo, None si no hay, o "descartado" si da menos de lo mínimo."""
        p = self.p
        if p.objetivo == "ninguno":
            return None
        if p.objetivo == "r":
            precio = entrada + lado * p.objetivo_r * riesgo
        elif p.objetivo == "atr":
            if atr is None:
                return "descartado"
            precio = entrada + lado * p.objetivo_atr_n * atr
        else:
            previas = self.velas.high[-p.swing_velas - 1 : -1] if lado > 0 else self.velas.low[-p.swing_velas - 1 : -1]
            if not len(previas):
                return "descartado"
            precio = max(previas) if lado > 0 else min(previas)
        if (precio - entrada) * lado < p.objetivo_min_r * riesgo:
            return "descartado"
        return round(precio / self.tick) * self.tick
