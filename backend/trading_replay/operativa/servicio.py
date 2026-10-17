"""Operativa de la cuenta activa: el motor de órdenes conectado al reloj del replay y a la base de datos.

Todo pasa por `cerrojo`, que hace atómicos el avance del reloj y las órdenes (FastAPI atiende los
endpoints síncronos en varios hilos).
"""

import threading
from datetime import datetime, timezone

from trading_replay import replay
from trading_replay.operativa import bd, perfiles, reto, vigilancia
from trading_replay.operativa.bd import Cuenta
from trading_replay.operativa.contratos import CONTRATOS
from trading_replay.operativa.motor import COMPRA, Costes, Ejecucion, Minuto, Motor, Orden, OrdenNoValida
from trading_replay.operativa.perfiles import Perfil
from trading_replay.operativa.reto import EN_CURSO, HORA_CIERRE, LIMITE_DIARIO, EstadoReto
from trading_replay.replay import SesionReplay

BALANCE_DEMO = 50_000.0
CAMPOS_COSTES = ("spread_ticks", "deslizamiento_ticks", "comision_mini", "comision_micro")
REAPERTURA = vigilancia.REAPERTURA

cerrojo = threading.RLock()


class ConExposicion(Exception):
    """Hay posiciones u órdenes abiertas y la acción no lo permite."""


class CuentaNoValida(Exception):
    """La acción no se puede hacer sobre esa cuenta."""


class _Estado:
    """Conexión, cuenta activa y su motor. Se rehace si cambia la carpeta de datos (tests)."""

    def __init__(self):
        self.ruta = bd.ruta()
        self.con = bd.conectar(self.ruta)
        self.cuenta: Cuenta | None = None
        self.motor: Motor | None = None
        self.reto: tuple[EstadoReto, Perfil] | None = None
        self.reto_leido = False
        self.eventos: list[dict] = []  # del reto de la cuenta activa, para el frontend (spec 006)

    def olvidar(self) -> None:
        """La cuenta activa ha cambiado: se recarga todo desde la base de datos."""
        self.cuenta, self.motor, self.reto, self.reto_leido = None, None, None, False
        self.eventos = []


_estado: _Estado | None = None


def _e() -> _Estado:
    global _estado
    if _estado is None or _estado.ruta != bd.ruta():
        _estado = _Estado()
    return _estado


def cuenta_activa() -> Cuenta:
    e = _e()
    if e.cuenta is None:
        todas = bd.cuentas(e.con)
        if not todas:
            todas = [bd.crear_cuenta(e.con, Cuenta("Demo", BALANCE_DEMO, BALANCE_DEMO, activa=True))]
        e.cuenta = next((c for c in todas if c.activa), todas[0])
        bd.activar(e.con, e.cuenta.id)
    return e.cuenta


def motor() -> Motor:
    e = _e()
    if e.motor is None:
        cuenta = cuenta_activa()
        costes = Costes(**{c: getattr(cuenta, c) for c in CAMPOS_COSTES})
        e.motor = Motor(costes, cuenta.balance, bd.ordenes_pendientes(e.con, cuenta.id), bd.posiciones_abiertas(e.con, cuenta.id))
    return e.motor


def simbolos_con_exposicion() -> set[str]:
    return motor().simbolos_con_exposicion()


def reto_activo() -> tuple[EstadoReto, Perfil] | None:
    """Estado y perfil del reto de la cuenta activa, o None si es una cuenta libre."""
    e = _e()
    if not e.reto_leido:
        estado = bd.reto(e.con, cuenta_activa().id)
        e.reto = (estado, perfiles.buscar(estado.perfil)) if estado else None
        e.reto_leido = True
    return e.reto


# --- Precio actual ---


def _minuto(fila: tuple) -> Minuto:
    return Minuto(*fila[:5])


def _preparar(sesion: SesionReplay, simbolos) -> Motor:
    """Pone en el motor el último minuto visto de cada instrumento de `simbolos`."""
    m = motor()
    for simbolo in simbolos:
        fila = sesion.ultimo(simbolo)
        if fila is not None:
            m.ultimo[simbolo] = _minuto(fila)
    return m


# --- Guardado ---


def _guardar(sesion: SesionReplay | None) -> list[Ejecucion]:
    """Escribe en la base de datos lo que ha cambiado en el motor. Devuelve las ejecuciones nuevas."""
    e = _e()
    m = motor()
    cuenta = cuenta_activa()
    cambios = m.vaciar_cambios()
    id_sesion = sesion.id if sesion else None
    real = bd.ahora_real()
    con = e.con
    con.execute("BEGIN")
    try:
        for orden in cambios.ordenes:
            bd.guardar(con, "ordenes", orden, cuenta=cuenta.id, sesion=id_sesion, creada_real=real)
        for ejecucion in cambios.ejecuciones:
            bd.guardar(con, "ejecuciones", ejecucion, cuenta=cuenta.id, sesion=id_sesion, creada_real=real)
        for operacion in cambios.operaciones:
            bd.guardar(con, "operaciones", operacion, cuenta=cuenta.id, sesion=id_sesion)
        for posicion in cambios.posiciones:
            bd.guardar(con, "posiciones", posicion, clave=("cuenta", "contrato"), cuenta=cuenta.id)
        cuenta.balance = m.balance
        activo = reto_activo()
        if activo:
            if cambios.ejecuciones:
                activo[0].operado = True
            bd.guardar(con, "retos", activo[0], clave=("cuenta",))
        # Para retomar el replay si se reinicia el servidor con algo abierto (RF-6).
        expuesta = m.hay_exposicion() and sesion is not None
        cuenta.instante_replay = sesion.instante if expuesta else None
        cuenta.sesion_replay = sesion.id if expuesta else None
        bd.guardar(con, "cuentas", cuenta, conservar=("creada",))
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        # El motor y el reto tienen cambios que no están en disco: se recargan desde la base de datos.
        e.motor, e.reto, e.reto_leido = None, None, False
        raise
    return cambios.ejecuciones


# --- Acciones ---


def enviar(sesion: SesionReplay, orden: Orden) -> tuple[Orden, list[Ejecucion]]:
    contrato = CONTRATOS.get(orden.contrato)
    if contrato is None:
        raise OrdenNoValida(f"Contrato desconocido: {orden.contrato}")
    m = _preparar(sesion, {contrato.simbolo})
    activo = sincronizar(sesion)
    if activo:
        _validar_en_reto(activo, m, orden, sesion.instante)
    m.enviar(orden, sesion.instante)  # si no es válida, falla antes de cambiar nada
    if activo:
        _preparar(sesion, simbolos_con_exposicion())
        _vigilar_ahora(activo, sesion.instante)
    return orden, _guardar(sesion)


def modificar(sesion: SesionReplay, id_orden: str, precio: float) -> None:
    m = _preparar(sesion, simbolos_con_exposicion())
    m.modificar(id_orden, precio)
    _guardar(sesion)


def cancelar(sesion: SesionReplay, id_orden: str) -> None:
    motor().cancelar(id_orden)
    _guardar(sesion)


def cerrar(sesion: SesionReplay, codigo: str) -> list[Ejecucion]:
    contrato = CONTRATOS.get(codigo)
    if contrato is None:
        raise OrdenNoValida(f"Contrato desconocido: {codigo}")
    m = _preparar(sesion, {contrato.simbolo})
    m.cerrar(codigo, sesion.instante)
    return _guardar(sesion)


def cerrar_todo(sesion: SesionReplay) -> list[Ejecucion]:
    m = _preparar(sesion, simbolos_con_exposicion())
    for codigo in {o.contrato for o in m.ordenes} | {c for c, p in m.posiciones.items() if p.cantidad}:
        m.cerrar(codigo, sesion.instante)
    return _guardar(sesion)


def liquidar(sesion: SesionReplay) -> list[Ejecucion]:
    """Cierra todo al precio del instante actual: antes de saltar a otro momento o salir (RF-17)."""
    if not simbolos_con_exposicion():
        return []
    m = _preparar(sesion, simbolos_con_exposicion())
    m.liquidar(sesion.instante)
    return _guardar(sesion)


def procesar_avance(sesion: SesionReplay, minutos: dict[str, list[tuple]]) -> list[Ejecucion]:
    """Pasa por el motor los minutos que acaba de avanzar el reloj, de todos los instrumentos, por orden de hora.
    En una cuenta de reto, además, vigila sus reglas en cada minuto (spec 006)."""
    m = motor()
    activo = sincronizar(sesion)
    por_hora = sorted((fila[0], simbolo, fila) for simbolo, filas in minutos.items() for fila in filas)
    hubo = False
    for _, simbolo, fila in por_hora:
        minuto = _minuto(fila)
        if activo and _hora_de_cierre(activo, simbolo, minuto):
            hubo = True
        if m.procesar(simbolo, minuto):
            hubo = True
        if activo and _vigilar(activo, simbolo, minuto):
            hubo = True
    return _guardar(sesion) if hubo or (activo and por_hora) else []


# --- Reglas del reto (spec 006) ---


def _cambiar_dia(cuenta_id: int, estado: EstadoReto, perfil: Perfil, balance: float, id_sesion, instante) -> dict | None:
    """Cierra el día en curso si tuvo operaciones y empieza el de `id_sesion` (RF-4, plan "Días")."""
    evento = None
    if estado.operado:
        evento = reto.cerrar_dia(estado, perfil, balance, bd.dias(_e().con, cuenta_id), instante)
    estado.sesion_dia, estado.balance_inicio_dia, estado.operado = id_sesion, balance, False
    estado.bloqueo = estado.bloqueo_hasta = None
    return evento


def sincronizar(sesion: SesionReplay | None) -> tuple[EstadoReto, Perfil] | None:
    """Si la cuenta activa es de reto y el día ha cambiado (otro salto), cierra el anterior y empieza el nuevo."""
    activo = reto_activo()
    id_sesion = sesion.id if sesion else None
    if activo and activo[0].sesion_dia != id_sesion:
        estado, perfil = activo
        evento = _cambiar_dia(cuenta_activa().id, estado, perfil, motor().balance, id_sesion, None)
        if evento:
            _e().eventos.append(evento)
        bd.guardar(_e().con, "retos", estado, clave=("cuenta",))
    return activo


def terminar_dia(sesion: SesionReplay | None) -> None:
    """Al saltar o salir del replay, después de liquidar: cierra el día de la cuenta activa."""
    activo = reto_activo()
    if activo and sesion and activo[0].sesion_dia == sesion.id:
        estado, perfil = activo
        evento = _cambiar_dia(cuenta_activa().id, estado, perfil, motor().balance, None, sesion.instante)
        if evento:
            _e().eventos.append(evento)
        bd.guardar(_e().con, "retos", estado, clave=("cuenta",))


# La vigilancia está en `vigilancia.py`, común con el backtest (spec 009). Aquí se aplica a la cuenta activa
# y sus eventos van a la lista que recoge el frontend.


def _validar_en_reto(activo: tuple[EstadoReto, Perfil], m: Motor, orden: Orden, instante: datetime) -> None:
    vigilancia.validar_orden(*activo, m, orden, instante)


def _avisar(evento: dict | None) -> bool:
    if evento:
        _e().eventos.append(evento)
    return evento is not None


def _hora_de_cierre(activo: tuple[EstadoReto, Perfil], simbolo: str, minuto: Minuto) -> bool:
    return _avisar(vigilancia.hora_de_cierre(*activo, motor(), simbolo, minuto))


def _vigilar(activo: tuple[EstadoReto, Perfil], simbolo: str, minuto: Minuto) -> bool:
    return _avisar(vigilancia.vigilar(*activo, motor(), simbolo, minuto))


def _vigilar_ahora(activo: tuple[EstadoReto, Perfil], instante: datetime) -> None:
    _avisar(vigilancia.vigilar_ahora(*activo, motor(), instante))


# --- Cuentas ---


def cuentas() -> list[dict]:
    activa = cuenta_activa()
    de_reto = bd.perfiles_de_cuentas(_e().con)
    return [_cuenta_api(c, c.id == activa.id, de_reto.get(c.id)) for c in bd.cuentas(_e().con)]


def perfiles_api() -> list[dict]:
    return [
        {"id": p.id, "empresa": p.empresa, "nombre": p.nombre, "titulo": p.titulo, "balance_inicial": p.balance_inicial}
        for p in perfiles.todos().values()
    ]


def crear_cuenta(nombre: str | None, balance_inicial: float | None, id_perfil: str | None = None) -> dict:
    """Cuenta libre, o de reto con el balance inicial y el nombre del perfil (spec 006, RF-3)."""
    _sin_exposicion()
    perfil = perfiles.buscar(id_perfil) if id_perfil else None
    if perfil:
        nombre, balance_inicial = nombre or perfil.titulo, perfil.balance_inicial
    if not nombre or not balance_inicial:
        raise CuentaNoValida("La cuenta nueva necesita nombre y balance inicial")
    creada = []

    def accion(con):
        cuenta = bd.crear_cuenta(con, Cuenta(nombre, balance_inicial, balance_inicial))
        if perfil:
            bd.guardar(con, "retos", reto.nuevo(cuenta.id, perfil), clave=("cuenta",))
        creada.append(cuenta)

    _transaccion(accion)
    _activar(creada[0].id)
    return _cuenta_api(cuenta_activa(), True, id_perfil)


def _buscar(id_cuenta: int) -> Cuenta:
    cuenta = next((c for c in bd.cuentas(_e().con) if c.id == id_cuenta), None)
    if cuenta is None:
        raise KeyError(id_cuenta)
    return cuenta


def _transaccion(accion) -> None:
    con = _e().con
    con.execute("BEGIN")
    try:
        accion(con)
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise


def actualizar_cuenta(id_cuenta: int, cambios: dict) -> dict:
    e = _e()
    cuenta = _buscar(id_cuenta)
    es_activa = cuenta.id == cuenta_activa().id
    if cambios.get("activa") and not es_activa or es_activa and any(cambios.get(c) is not None for c in CAMPOS_COSTES):
        _sin_exposicion()
    if cambios.get("activa") and not es_activa:
        _activar(id_cuenta)
        cuenta = cuenta_activa()
    for campo in (*CAMPOS_COSTES, "nombre"):
        if cambios.get(campo) is not None:
            setattr(cuenta, campo, cambios[campo])
    bd.guardar(e.con, "cuentas", cuenta, conservar=("creada",))
    if cuenta.id == cuenta_activa().id:
        e.olvidar()  # se recargan con los costes nuevos
    return _cuenta_api(cuenta, cuenta.id == cuenta_activa().id, bd.perfiles_de_cuentas(e.con).get(cuenta.id))


def reiniciar_cuenta(id_cuenta: int) -> dict:
    """Vuelve al balance inicial y borra el historial; conserva nombre y costes (RF-27)."""
    cuenta = _buscar(id_cuenta)
    es_activa = cuenta.id == cuenta_activa().id
    if es_activa:
        _sin_exposicion()
    estado = bd.reto(_e().con, cuenta.id)

    def accion(con):
        if estado:
            _cerrar_intento(con, cuenta, estado)
        cuenta.balance = cuenta.balance_inicial
        cuenta.instante_replay = cuenta.sesion_replay = None
        bd.borrar_historial(con, cuenta.id)
        bd.guardar(con, "cuentas", cuenta, conservar=("creada",))

    _transaccion(accion)
    if es_activa:
        _e().olvidar()
    return _cuenta_api(cuenta, es_activa, estado.perfil if estado else None)


def _cerrar_intento(con, cuenta: Cuenta, estado: EstadoReto) -> None:
    """Reiniciar un reto guarda el intento en el historial y empieza el siguiente (spec 006, RF-14)."""
    perfil = perfiles.buscar(estado.perfil)
    dias = bd.dias(con, cuenta.id)
    siguiente = estado.intento
    if dias or estado.estado != EN_CURSO:
        hecho = reto.progreso(perfil, cuenta.balance, dias)
        resultado = estado.estado if estado.estado != EN_CURSO else "abandonado"
        bd.guardar_intento(
            con, cuenta.id, perfil=perfil.id, numero=estado.intento, resultado=resultado, motivo=estado.motivo,
            dias=len(dias), beneficio=hecho.beneficio, mejor_dia=hecho.mejor_dia,
        )
        siguiente += 1
    bd.guardar(con, "retos", reto.nuevo(cuenta.id, perfil, siguiente), clave=("cuenta",))


def borrar_cuenta(id_cuenta: int) -> None:
    """Elimina la cuenta y su historial; si era la activa, pasa a serlo la más antigua (RF-28)."""
    cuenta = _buscar(id_cuenta)
    if len(bd.cuentas(_e().con)) == 1:
        raise CuentaNoValida("No se puede borrar la única cuenta")
    es_activa = cuenta.id == cuenta_activa().id
    if es_activa:
        _sin_exposicion()
    _transaccion(lambda con: bd.borrar_cuenta(con, cuenta.id))
    if es_activa:
        _activar(bd.cuentas(_e().con)[0].id)


def _activar(id_cuenta: int) -> None:
    e = _e()
    bd.activar(e.con, id_cuenta)
    e.olvidar()


def _sin_exposicion() -> None:
    if simbolos_con_exposicion():
        raise ConExposicion("Cierra las posiciones y órdenes de la cuenta activa antes de cambiar de cuenta, de costes, reiniciarla o borrarla")


def _cuenta_api(cuenta: Cuenta, activa: bool, id_perfil: str | None = None) -> dict:
    return {
        "id": cuenta.id,
        "nombre": cuenta.nombre,
        "balance_inicial": cuenta.balance_inicial,
        "balance": cuenta.balance,
        "activa": activa,
        "costes": {c: getattr(cuenta, c) for c in CAMPOS_COSTES},
        "perfil": id_perfil,
    }


# --- Consultas para la API ---

LADOS = {1: "compra", -1: "venta"}


def _hora_grafico(momento: datetime) -> int:
    """Hora ET como la usa el gráfico: segundos Unix como si fuera UTC."""
    return int(momento.replace(tzinfo=timezone.utc).timestamp())


def ejecucion_api(ejecucion: Ejecucion) -> dict:
    return {
        "id": ejecucion.id,
        "contrato": ejecucion.contrato,
        "simbolo": CONTRATOS[ejecucion.contrato].simbolo,
        "lado": LADOS[ejecucion.lado],
        "cantidad": ejecucion.cantidad,
        "precio": ejecucion.precio,
        "papel": ejecucion.papel,
        "time": _hora_grafico(ejecucion.instante),
    }


def resumen(sesion: SesionReplay | None) -> dict:
    """Estado de la cuenta activa: balance, PnL abierto, posiciones y órdenes pendientes."""
    m = motor()
    cuenta = cuenta_activa()
    abiertas = [p for p in m.posiciones.values() if p.cantidad]
    if sesion:
        _preparar(sesion, {CONTRATOS[p.contrato].simbolo for p in abiertas})
    posiciones = [
        {
            "contrato": p.contrato,
            "simbolo": CONTRATOS[p.contrato].simbolo,
            "cantidad": p.cantidad,
            "precio_medio": round(p.precio_medio, 4),
            "pnl": m.pnl_abierto(p),
            # Apertura de la operación, donde empiezan las zonas de SL y TP del gráfico (RF-22).
            "desde": _hora_grafico(p.operacion.apertura) if p.operacion else None,
        }
        for p in abiertas
    ]
    ordenes = [
        {
            "id": o.id,
            "contrato": o.contrato,
            "simbolo": CONTRATOS[o.contrato].simbolo,
            "lado": LADOS[o.lado],
            "tipo": o.tipo,
            "cantidad": o.cantidad,
            "precio": o.precio,
            "papel": o.papel,
            "grupo": o.grupo,
        }
        for o in m.ordenes
        if o.estado == "pendiente"
    ]
    pnl_abierto = round(sum(p["pnl"] for p in posiciones), 2)
    activo = sincronizar(sesion)
    e = _e()
    eventos, e.eventos = e.eventos, []
    return {
        **_cuenta_api(cuenta, True, activo[1].id if activo else None),
        "balance": m.balance,
        "pnl_abierto": pnl_abierto,
        "pnl_sesion": bd.pnl_sesion(e.con, cuenta.id, sesion.id) if sesion else 0.0,
        "posiciones": posiciones,
        "ordenes": ordenes,
        "reto": _reto_api(cuenta.id, *activo, m.balance, m.balance + pnl_abierto, sesion, m) if activo else None,
        "eventos": eventos,
    }


def _reto_api(
    cuenta_id: int, estado: EstadoReto, perfil: Perfil, balance: float, vivo: float, sesion: SesionReplay | None, m: Motor | None
) -> dict:
    """Estado del reto para el panel de operar y el resumen de cuentas (RF-15, RF-21)."""
    dias = bd.dias(_e().con, cuenta_id)
    id_sesion = sesion.id if sesion else None
    hecho = reto.progreso(perfil, balance, dias)
    nivel, regla = reto.nivel_liquidacion(estado, perfil)
    en_curso = estado.estado == EN_CURSO
    hoy = en_curso and id_sesion is not None and estado.sesion_dia == id_sesion
    consistencia = None
    if perfil.consistencia:
        beneficio, mejor, porcentaje = hecho.beneficio, hecho.mejor_dia, perfil.consistencia
        consistencia = {
            "porcentaje": porcentaje,
            "mejor_dia": mejor,
            "porcentaje_mejor": round(mejor / beneficio, 4) if beneficio > 0 else None,
            "maximo_mejor_dia": round(beneficio * porcentaje, 2) if beneficio > 0 else None,
            "beneficio_necesario": round(mejor / porcentaje, 2),
            "falta": round(max(0.0, mejor / porcentaje - beneficio), 2),
            "sube_objetivo": hecho.objetivo_efectivo > perfil.objetivo,
        }
    liquidacion = {}
    if m and hoy:
        for simbolo in {CONTRATOS[p.contrato].simbolo for p in m.posiciones.values() if p.cantidad}:
            ruptura = reto.precio_ruptura(nivel, *vigilancia.recta_balance(m, simbolo))
            if ruptura is not None:
                liquidacion[simbolo] = round(ruptura * vigilancia.tick_de(simbolo), 2)
    bloqueo = None
    if hoy and estado.bloqueo == LIMITE_DIARIO:
        bloqueo = "Límite diario alcanzado: podrás operar en el siguiente salto"
    elif hoy and sesion and perfil.hora_cierre:
        cerrado = estado.bloqueo == HORA_CIERRE and estado.bloqueo_hasta and sesion.instante < estado.bloqueo_hasta
        if cerrado or perfil.hora_cierre <= sesion.instante.time() < REAPERTURA:
            bloqueo = f"Fuera del horario del reto: se puede operar desde las {REAPERTURA:%H:%M}"
    posiciones = {c: p.cantidad for c, p in m.posiciones.items()} if m else {}
    return {
        "perfil": perfil.id,
        "titulo": perfil.titulo,
        "empresa": perfil.empresa,
        "intento": estado.intento,
        "estado": estado.estado,
        "motivo": estado.motivo,
        "dia": len(dias) + (1 if hoy and not estado.operado else 0),
        "objetivo": perfil.objetivo,
        "objetivo_efectivo": hecho.objetivo_efectivo,
        "beneficio": hecho.beneficio,
        "falta": hecho.falta,
        "mejor_dia": hecho.mejor_dia,
        "consistencia": consistencia,
        "dias_validos": hecho.dias_validos,
        "dias_minimos": perfil.dias_minimos,
        "faltan_dias": hecho.faltan_dias,
        "beneficio_minimo_dia": perfil.beneficio_minimo_dia,
        "umbral": estado.umbral,
        "tipo_perdida": perfil.perdida_maxima.tipo,
        "perdida_maxima": perfil.perdida_maxima.importe,
        "distancia": round(vivo - estado.umbral, 2),
        "limite_diario": perfil.limite_diario.importe if perfil.limite_diario else None,
        "pnl_dia": round(vivo - estado.balance_inicio_dia, 2) if hoy else None,
        "nivel": nivel,
        "regla": regla,
        "liquidacion": liquidacion,
        "contratos_en_uso": reto.contratos_en_uso(posiciones),
        "contratos_maximos": perfil.contratos_maximos,
        "hora_cierre": f"{perfil.hora_cierre:%H:%M}" if perfil.hora_cierre else None,
        "bloqueo": bloqueo,
        "dias": [
            {"numero": i + 1, "pnl": d.pnl, "valido": v, "en_curso": hoy and d.sesion == id_sesion}
            for i, (d, v) in enumerate(zip(dias, hecho.validos))
        ],
    }


def resumen_cuentas(sesion: SesionReplay | None) -> list[dict]:
    """Una tarjeta por cuenta: estadísticas y, en las de reto, cómo va (spec 006, RF-21)."""
    e = _e()
    activa = cuenta_activa()
    sincronizar(sesion)
    de_reto = bd.perfiles_de_cuentas(e.con)
    id_sesion = sesion.id if sesion else None
    tarjetas = []
    for cuenta in bd.cuentas(e.con):
        es_activa = cuenta.id == activa.id
        m = motor() if es_activa else None
        balance = m.balance if m else cuenta.balance
        vivo = balance + (sum(m.pnl_abierto(p) for p in m.posiciones.values() if p.cantidad) if m else 0)
        beneficio = round(balance - cuenta.balance_inicial, 2)
        estadisticas = bd.estadisticas(e.con, cuenta.id)
        tarjeta = {
            **_cuenta_api(cuenta, es_activa, de_reto.get(cuenta.id)),
            "balance": balance,
            "beneficio": beneficio,
            "rentabilidad": round(beneficio / cuenta.balance_inicial, 4),
            **estadisticas,
            "acierto": round(estadisticas["ganadoras"] / estadisticas["operaciones"], 4) if estadisticas["operaciones"] else None,
            "dias_operados": len(bd.dias(e.con, cuenta.id)),
            "reto": None,
            "intentos": [],
        }
        if cuenta.id in de_reto:
            if es_activa:
                estado, perfil = reto_activo()
            else:
                estado = bd.reto(e.con, cuenta.id)
                perfil = perfiles.buscar(estado.perfil)
                # El día de una cuenta que no está activa se cierra la primera vez que se mira después.
                if estado.sesion_dia not in (None, id_sesion):
                    _cambiar_dia(cuenta.id, estado, perfil, balance, None, None)
                    bd.guardar(e.con, "retos", estado, clave=("cuenta",))
            tarjeta["reto"] = _reto_api(cuenta.id, estado, perfil, balance, vivo, sesion if es_activa else None, m)
            tarjeta["intentos"] = bd.intentos(e.con, cuenta.id)
        tarjetas.append(tarjeta)
    return tarjetas


def operaciones(limite: int) -> list[dict]:
    cuenta = cuenta_activa()
    resultado = []
    for o, sesion in bd.operaciones_cerradas(_e().con, cuenta.id, limite):
        resultado.append(
            {
                "id": o.id,
                "contrato": o.contrato,
                "lado": LADOS[o.lado],
                "cantidad": o.cantidad,
                "entrada": round(o.entrada, 4),
                "salida": round(o.salida, 4),
                "apertura": o.apertura.isoformat(),
                "cierre": o.cierre.isoformat(),
                "pnl_bruto": o.pnl_bruto,
                "comisiones": o.comisiones,
                "pnl_neto": o.pnl_neto,
                "sl_inicial": o.sl_inicial,
                "sesion": sesion,
            }
        )
    return resultado


def ejecuciones(sesion: SesionReplay, simbolo: str | None) -> list[dict]:
    todas = bd.ejecuciones_de_sesion(_e().con, cuenta_activa().id, sesion.id)
    return [ejecucion_api(x) for x in todas if simbolo is None or CONTRATOS[x.contrato].simbolo == simbolo]


def restaurar_replay() -> SesionReplay | None:
    """Al arrancar: si la cuenta activa quedó con algo abierto, retoma el replay donde estaba (RF-6)."""
    with cerrojo:
        cuenta = cuenta_activa()
        if replay.actual() is None and cuenta.instante_replay is not None:
            return replay.iniciar(cuenta.instante_replay, cuenta.sesion_replay)
        return None


def nueva_orden(contrato: str, lado: str, tipo: str, cantidad: int, precio=None, sl_puntos=None, tp_puntos=None) -> Orden:
    if lado not in ("compra", "venta"):
        raise OrdenNoValida("El lado tiene que ser compra o venta")
    return Orden(contrato.upper(), COMPRA if lado == "compra" else -COMPRA, tipo, cantidad, precio, sl_puntos, tp_puntos)
