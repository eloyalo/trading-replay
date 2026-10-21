"""Servidor principal: API bajo /api y frontend estático en /."""

from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from trading_replay import __version__, replay
from trading_replay.backtest import almacen_bt, cargador, metricas, trabajos
from trading_replay.backtest.estrategia import ParametroNoValido, valores_parametros
from trading_replay.config import INSTRUMENTOS
from trading_replay.estudio import escena as estudio_escena
from trading_replay.historico import almacen
from trading_replay.operativa import perfiles, servicio
from trading_replay.operativa.perfiles import PerfilNoValido
from trading_replay.operativa.motor import MAX_CONTRATOS, Costes, OrdenNoValida

RAIZ = Path(__file__).resolve().parents[2]
FRONTEND = RAIZ / "frontend"

# Cuánta historia se devuelve por defecto en cada timeframe, para que la carga sea ágil.
VENTANA_POR_DEFECTO = {
    "1m": timedelta(days=3),
    "5m": timedelta(days=14),
    "15m": timedelta(days=31),
    "30m": timedelta(days=62),
    "1h": timedelta(days=92),
    "4h": timedelta(days=366),
    "1D": timedelta(days=366 * 10),
}


@asynccontextmanager
async def vida(_app):
    # Si la cuenta quedó con posiciones u órdenes abiertas, se retoma el replay donde estaba (spec 005, RF-6).
    servicio.restaurar_replay()
    yield


app = FastAPI(title="trading-replay", version=__version__, lifespan=vida)


@app.middleware("http")
async def revalidar_frontend(request, call_next):
    """Sin esto, Chrome reutiliza app.js y compañía de su caché y no ve los cambios al recargar."""
    respuesta = await call_next(request)
    if not request.url.path.startswith("/api/"):
        respuesta.headers["Cache-Control"] = "no-cache"
    return respuesta


@app.get("/api/estado")
def estado() -> dict:
    return {"ok": True, "version": __version__}


@app.get("/api/instrumentos")
def instrumentos() -> list[dict]:
    """Instrumentos disponibles y el rango de datos descargado de cada uno (hora ET)."""
    resultado = []
    for instrumento in INSTRUMENTOS.values():
        disponible = almacen.rango(instrumento.simbolo)
        resultado.append(
            {
                "simbolo": instrumento.simbolo,
                "nombre": instrumento.nombre,
                "desde": disponible[0].isoformat() if disponible else None,
                "hasta": disponible[1].isoformat() if disponible else None,
            }
        )
    return resultado


def comprobar_simbolo(simbolo: str) -> tuple[str, tuple[datetime, datetime]]:
    """Símbolo normalizado y rango de datos disponible, o error HTTP si no se puede usar."""
    simbolo = simbolo.upper()
    if simbolo not in INSTRUMENTOS:
        raise HTTPException(404, f"Instrumento desconocido: {simbolo}")
    disponible = almacen.rango(simbolo)
    if not disponible:
        raise HTTPException(404, f"No hay datos de {simbolo}: ejecuta `trading-replay datos descargar`")
    return simbolo, disponible


def comprobar_tf(tf: str) -> None:
    if tf not in almacen.TIMEFRAMES:
        raise HTTPException(422, f"Timeframe no válido: {tf}. Opciones: {', '.join(almacen.TIMEFRAMES)}")


@app.get("/api/velas")
def velas(
    simbolo: str,
    tf: str = "15m",
    desde: datetime | None = Query(None, description="hora ET; por defecto, una ventana según el timeframe"),
    hasta: datetime | None = Query(None, description="hora ET, excluida; por defecto, el final de los datos"),
) -> dict:
    comprobar_tf(tf)
    simbolo, disponible = comprobar_simbolo(simbolo)

    hasta = hasta or disponible[1] + timedelta(minutes=1)
    sesion = replay.actual()
    if sesion:
        # Con un replay en marcha, nunca se devuelve nada posterior a su instante.
        hasta = min(hasta, sesion.instante)
    desde = desde or hasta - VENTANA_POR_DEFECTO[tf]
    return {
        "simbolo": simbolo,
        "tf": tf,
        "inicio_datos": disponible[0].isoformat(),
        "velas": almacen.consultar(simbolo, tf, desde, hasta),
    }


class InicioReplay(BaseModel):
    simbolo: str
    inicio: datetime | None = Field(None, description="hora ET")
    aleatorio: bool = False
    sesion: Literal["cualquiera", "asia", "londres", "nueva_york"] = "cualquiera"

    @model_validator(mode="after")
    def inicio_o_aleatorio(self):
        if (self.inicio is None) != self.aleatorio:
            raise ValueError("Indica `inicio` o `aleatorio`, uno de los dos")
        return self


class AvanceReplay(BaseModel):
    simbolo: str
    minutos: int | None = Field(None, ge=1, le=replay.MAX_MINUTOS)
    tf: str | None = Field(None, description="avanza hasta cerrar la siguiente vela de este timeframe")

    @model_validator(mode="after")
    def minutos_o_tf(self):
        if (self.minutos is None) == (self.tf is None):
            raise ValueError("Indica `minutos` o `tf`, uno de los dos")
        return self


def estado_replay(**extra) -> dict:
    sesion = replay.actual()
    return {"activo": sesion is not None, "instante": sesion.instante.isoformat() if sesion else None, **extra}


def liquidar_si_hace_falta() -> list:
    """Antes de saltar o salir del replay se cierra todo al precio del instante (spec 005, RF-17)."""
    sesion = replay.actual()
    return [servicio.ejecucion_api(e) for e in servicio.liquidar(sesion)] if sesion else []


@app.get("/api/replay")
def ver_replay() -> dict:
    return estado_replay()


@app.post("/api/replay")
def iniciar_replay(peticion: InicioReplay) -> dict:
    if trabajos.en_marcha():
        raise HTTPException(409, "Hay un backtest en marcha: espera a que termine o cancélalo")
    simbolo, disponible = comprobar_simbolo(peticion.simbolo)
    if peticion.aleatorio:
        instante = replay.instante_aleatorio(simbolo, peticion.sesion)
        if instante is None:
            raise HTTPException(422, "No hay histórico suficiente para elegir un momento aleatorio")
    else:
        instante = peticion.inicio.replace(tzinfo=None)
        if not disponible[0] <= instante <= disponible[1]:
            raise HTTPException(
                422, f"Fuera de los datos de {simbolo}: de {disponible[0]:%Y-%m-%d %H:%M} a {disponible[1]:%Y-%m-%d %H:%M}"
            )
    with servicio.cerrojo:
        liquidadas = liquidar_si_hace_falta()
        servicio.terminar_dia(replay.actual())  # cada salto es un día del reto (spec 006, RF-4)
        replay.iniciar(instante)
    return estado_replay(liquidadas=liquidadas)


@app.post("/api/replay/avanzar")
def avanzar_replay(peticion: AvanceReplay) -> dict:
    sesion = replay.actual()
    if not sesion:
        raise HTTPException(409, "No hay ningún replay en marcha")
    if peticion.tf:
        comprobar_tf(peticion.tf)
    simbolo, _ = comprobar_simbolo(peticion.simbolo)
    with servicio.cerrojo:
        desde = sesion.instante
        nuevas, fin = sesion.avanzar(simbolo, minutos=peticion.minutos, tf=peticion.tf)
        # El motor de órdenes ve el mismo tramo de todos los instrumentos con exposición (spec 005, RF-15).
        minutos = {
            s: nuevas if s == simbolo else sesion.minutos_entre(s, desde, sesion.instante)
            for s in servicio.simbolos_con_exposicion()
        }
        ejecuciones = servicio.procesar_avance(sesion, minutos)
        cuenta = servicio.resumen(sesion)
    return {
        "instante": sesion.instante.isoformat(),
        "velas": [replay.vela_grafico(f) for f in nuevas],
        "fin": fin,
        "cuenta": cuenta,
        "ejecuciones": [servicio.ejecucion_api(e) for e in ejecuciones],
    }


@app.delete("/api/replay")
def salir_replay() -> dict:
    with servicio.cerrojo:
        liquidadas = liquidar_si_hace_falta()
        servicio.terminar_dia(replay.actual())
        replay.terminar()
    return estado_replay(liquidadas=liquidadas)


# --- Órdenes y cuentas (spec 005) ---


def sesion_para_operar():
    sesion = replay.actual()
    if not sesion:
        raise HTTPException(409, "Solo se puede operar durante un replay")
    return sesion


class NuevaOrden(BaseModel):
    contrato: str
    lado: Literal["compra", "venta"]
    tipo: Literal["mercado", "limite", "stop"] = "mercado"
    cantidad: int = Field(1, ge=1, le=MAX_CONTRATOS)
    precio: float | None = Field(None, gt=0)
    sl_puntos: float | None = Field(None, gt=0)
    tp_puntos: float | None = Field(None, gt=0)


class CambioOrden(BaseModel):
    precio: float = Field(gt=0)


class NuevaCuenta(BaseModel):
    nombre: str | None = Field(None, min_length=1, max_length=60)
    balance_inicial: float | None = Field(None, gt=0, le=10_000_000)
    perfil: str | None = Field(None, description="perfil de reto (spec 006); sin él, cuenta libre")


class CambioCuenta(BaseModel):
    nombre: str | None = Field(None, min_length=1, max_length=60)
    activa: bool | None = None
    spread_ticks: int | None = Field(None, ge=0, le=20)
    deslizamiento_ticks: int | None = Field(None, ge=0, le=20)
    comision_mini: float | None = Field(None, ge=0, le=100)
    comision_micro: float | None = Field(None, ge=0, le=100)


def operar(accion):
    """Ejecuta una acción sobre la cuenta y traduce sus errores a HTTP."""
    with servicio.cerrojo:
        try:
            return accion()
        except OrdenNoValida as error:
            raise HTTPException(422, str(error)) from error
        except KeyError as error:
            raise HTTPException(404, "No existe esa orden o ya no está pendiente") from error
        except servicio.ConExposicion as error:
            raise HTTPException(409, str(error)) from error
        except servicio.CuentaNoValida as error:
            raise HTTPException(409, str(error)) from error
        except PerfilNoValido as error:
            raise HTTPException(422, str(error)) from error


def respuesta_cuenta(sesion, ejecuciones=(), **extra) -> dict:
    return {"cuenta": servicio.resumen(sesion), "ejecuciones": [servicio.ejecucion_api(e) for e in ejecuciones], **extra}


@app.get("/api/cuenta")
def ver_cuenta() -> dict:
    with servicio.cerrojo:
        return servicio.resumen(replay.actual())


@app.post("/api/ordenes")
def enviar_orden(peticion: NuevaOrden) -> dict:
    sesion = sesion_para_operar()

    def accion():
        orden, ejecuciones = servicio.enviar(sesion, servicio.nueva_orden(**peticion.model_dump()))
        return respuesta_cuenta(sesion, ejecuciones, orden=orden.id)

    return operar(accion)


@app.patch("/api/ordenes/{id_orden}")
def modificar_orden(id_orden: str, peticion: CambioOrden) -> dict:
    sesion = sesion_para_operar()
    return operar(lambda: servicio.modificar(sesion, id_orden, peticion.precio) or respuesta_cuenta(sesion))


@app.delete("/api/ordenes/{id_orden}")
def cancelar_orden(id_orden: str) -> dict:
    sesion = sesion_para_operar()
    return operar(lambda: servicio.cancelar(sesion, id_orden) or respuesta_cuenta(sesion))


@app.post("/api/posiciones/{contrato}/cerrar")
def cerrar_posicion(contrato: str) -> dict:
    sesion = sesion_para_operar()
    return operar(lambda: respuesta_cuenta(sesion, servicio.cerrar(sesion, contrato.upper())))


@app.post("/api/cuenta/cerrar-todo")
def cerrar_todo() -> dict:
    sesion = sesion_para_operar()
    return operar(lambda: respuesta_cuenta(sesion, servicio.cerrar_todo(sesion)))


@app.get("/api/operaciones")
def ver_operaciones(limite: int = Query(50, ge=1, le=1000)) -> list[dict]:
    with servicio.cerrojo:
        return servicio.operaciones(limite)


@app.get("/api/ejecuciones")
def ver_ejecuciones(simbolo: str | None = None) -> list[dict]:
    sesion = replay.actual()
    if not sesion:
        return []
    with servicio.cerrojo:
        return servicio.ejecuciones(sesion, simbolo.upper() if simbolo else None)


@app.get("/api/cuentas")
def ver_cuentas() -> list[dict]:
    with servicio.cerrojo:
        return servicio.cuentas()


@app.post("/api/cuentas")
def crear_cuenta(peticion: NuevaCuenta) -> dict:
    return operar(lambda: servicio.crear_cuenta(peticion.nombre, peticion.balance_inicial, peticion.perfil))


@app.get("/api/cuentas/resumen")
def resumen_cuentas() -> list[dict]:
    """Cómo va cada cuenta, con el detalle de los retos (spec 006, RF-21)."""
    return operar(lambda: servicio.resumen_cuentas(replay.actual()))


@app.get("/api/perfiles")
def ver_perfiles() -> list[dict]:
    return operar(servicio.perfiles_api)


def sobre_cuenta(accion):
    """Como `operar`, con el 404 de una cuenta que no existe."""

    def envuelta():
        try:
            return accion()
        except KeyError as error:
            raise HTTPException(404, "No existe esa cuenta") from error

    return operar(envuelta)


@app.patch("/api/cuentas/{id_cuenta}")
def cambiar_cuenta(id_cuenta: int, peticion: CambioCuenta) -> dict:
    return sobre_cuenta(lambda: servicio.actualizar_cuenta(id_cuenta, peticion.model_dump()))


@app.post("/api/cuentas/{id_cuenta}/reiniciar")
def reiniciar_cuenta(id_cuenta: int) -> dict:
    return sobre_cuenta(lambda: servicio.reiniciar_cuenta(id_cuenta))


@app.delete("/api/cuentas/{id_cuenta}")
def borrar_cuenta(id_cuenta: int) -> list[dict]:
    return sobre_cuenta(lambda: servicio.borrar_cuenta(id_cuenta) or servicio.cuentas())


# --- Backtest de estrategias (spec 008) ---


def _estrategia(id_estrategia: str) -> cargador.InfoEstrategia:
    try:
        return cargador.buscar(id_estrategia)
    except KeyError as error:
        raise HTTPException(404, f"No existe la estrategia {id_estrategia}") from error


@app.get("/api/estrategias")
def ver_estrategias() -> list[dict]:
    return [info.api() for info in cargador.listar()]


@app.get("/api/estrategias/{id_estrategia}/codigo")
def ver_codigo_estrategia(id_estrategia: str) -> dict:
    info = _estrategia(id_estrategia)
    return {"id": info.id, "ruta": str(info.ruta), "huella": info.huella, "codigo": info.codigo}


@app.post("/api/estrategias/{id_estrategia}/duplicar")
def duplicar_estrategia(id_estrategia: str) -> dict:
    _estrategia(id_estrategia)
    return cargador.duplicar(id_estrategia).api()


class CostesBacktest(BaseModel):
    spread_ticks: int = Field(1, ge=0, le=20)
    deslizamiento_ticks: int = Field(0, ge=0, le=20)
    comision_mini: float = Field(2.5, ge=0, le=100)
    comision_micro: float = Field(0.75, ge=0, le=100)


class NuevoBacktest(BaseModel):
    estrategia: str
    simbolo: str
    desde: date | None = Field(None, description="primer día de trading; por defecto, el primero con datos")
    hasta: date | None = Field(None, description="último día de trading, incluido; por defecto, el último")
    parametros: dict = Field(default_factory=dict)
    costes: CostesBacktest = Field(default_factory=CostesBacktest)
    perfil: str | None = Field(None, description="perfil de reto (spec 009); sin él, backtest sin reto")


INICIO_DIA = time(18, 0)


def _dia_trading(dia: date) -> datetime:
    """Inicio (18:00 ET de la víspera) del día de trading `dia`."""
    return datetime.combine(dia - timedelta(days=1), INICIO_DIA)


@app.post("/api/backtests")
def lanzar_backtest(peticion: NuevoBacktest) -> dict:
    if replay.actual():
        raise HTTPException(409, "El backtest enseña todo el histórico: sal del replay antes de lanzarlo")
    simbolo, disponible = comprobar_simbolo(peticion.simbolo)
    info = _estrategia(peticion.estrategia)
    if info.error:
        raise HTTPException(422, f"La estrategia tiene un error: {info.error}")
    try:
        valores = valores_parametros(info.clase.parametros, peticion.parametros)
    except ParametroNoValido as error:
        raise HTTPException(422, str(error)) from error
    desde = _dia_trading(peticion.desde) if peticion.desde else disponible[0]
    hasta = _dia_trading(peticion.hasta + timedelta(days=1)) if peticion.hasta else disponible[1] + timedelta(minutes=1)
    if desde >= hasta:
        raise HTTPException(422, "El periodo está vacío: «desde» tiene que ser anterior a «hasta»")
    try:
        perfil = perfiles.buscar(peticion.perfil) if peticion.perfil else None
    except PerfilNoValido as error:
        raise HTTPException(422, str(error)) from error
    try:
        trabajo = trabajos.lanzar(info, valores, simbolo, desde, hasta, Costes(**peticion.costes.model_dump()), perfil)
    except trabajos.EnMarcha as error:
        raise HTTPException(409, str(error)) from error
    return trabajo.api()


@app.get("/api/backtests/en-marcha")
def ver_backtest_en_marcha() -> dict | None:
    trabajo = trabajos.actual()
    return trabajo.api() if trabajo else None


@app.post("/api/backtests/en-marcha/cancelar")
def cancelar_backtest() -> dict | None:
    trabajo = trabajos.cancelar()
    return trabajo.api() if trabajo else None


def _ejecucion_api(meta: dict, huellas: dict[str, str]) -> dict:
    actual = huellas.get(meta["estrategia"])
    return {
        **meta,
        "desde": meta["desde"].isoformat(),
        "hasta": meta["hasta"].isoformat(),
        # El archivo ya no está, o su código no es el que dio este resultado (RF-17).
        "codigo_cambiado": actual != meta["huella"],
        "estrategia_borrada": actual is None,
    }


def _operacion_api(op) -> dict:
    return {
        "numero": op.numero,
        "contrato": op.contrato,
        "lado": "largo" if op.lado > 0 else "corto",
        "cantidad": op.cantidad,
        "apertura": op.apertura.isoformat(),
        "cierre": op.cierre.isoformat(),
        "t_apertura": metricas.segundos_grafico(op.apertura),
        "t_cierre": metricas.segundos_grafico(op.cierre),
        # Minutos cuyo precio dio la entrada y la salida, para poner las marcas en su vela.
        "t_minuto_entrada": metricas.segundos_grafico(op.minuto_entrada or op.apertura),
        "t_minuto_salida": metricas.segundos_grafico(op.minuto_salida or op.cierre),
        "entrada": op.entrada,
        "salida": op.salida,
        "sl_inicial": op.sl_inicial,
        "sl_final": op.sl_final,
        "tp_final": op.tp_final,
        "motivo_entrada": op.motivo_entrada,
        "motivo_salida": op.motivo_salida,
        "pnl_neto": op.pnl_neto,
        "r": round(op.r, 3) if op.r is not None else None,
        "dudosa": op.dudosa,
        "intento": op.intento,
    }


def _huellas() -> dict[str, str]:
    return {info.id: info.huella for info in cargador.listar()}


@app.get("/api/backtests")
def historial_backtests() -> list[dict]:
    huellas = _huellas()
    return [_ejecucion_api(meta, huellas) for meta in almacen_bt.listar()]


def _meta_backtest(id_ejecucion: int, con_codigo: bool = False) -> dict:
    try:
        return almacen_bt.ejecucion(id_ejecucion, con_codigo)
    except KeyError as error:
        raise HTTPException(404, "No existe esa ejecución") from error


def _lista(texto: str | None, convertir=str) -> set | None:
    """"2023,2024" → {2023, 2024}; vacío → None (sin filtrar)."""
    if not texto:
        return None
    try:
        return {convertir(x.strip()) for x in texto.split(",") if x.strip()} or None
    except ValueError as error:
        raise HTTPException(422, f"Filtro no válido: {texto}") from error


def _filtro(desde, hasta, anios, sesiones, dias, lado) -> metricas.Filtro:
    sesiones_ok = _lista(sesiones)
    if sesiones_ok and not sesiones_ok <= set(metricas.SESIONES):
        raise HTTPException(422, f"Sesiones: {', '.join(metricas.SESIONES)}")
    if lado is not None and lado not in metricas.LADOS:
        raise HTTPException(422, "Lado: largos o cortos")
    return metricas.Filtro(
        desde=_dia_trading(desde) if desde else None,
        hasta=_dia_trading(hasta + timedelta(days=1)) if hasta else None,
        anios=_lista(anios, int),
        sesiones=sesiones_ok,
        dias=_lista(dias),
        lado=lado,
    )


@app.get("/api/backtests/{id_ejecucion}")
def ver_backtest(
    id_ejecucion: int,
    desde: date | None = None,
    hasta: date | None = Query(None, description="último día de trading, incluido"),
    anios: str | None = Query(None, description="separados por comas"),
    sesiones: str | None = Query(None, description="asia, londres, nueva_york, separadas por comas"),
    dias: str | None = Query(None, description="lunes, martes... separados por comas"),
    lado: str | None = Query(None, description="largos o cortos"),
    inicio: int = Query(0, ge=0, description="primera operación de la lista que se devuelve"),
    limite: int = Query(200, ge=0, le=5000),
) -> dict:
    """Métricas, curva, desglose y operaciones de una ejecución, con los filtros de RF-12."""
    meta = _meta_backtest(id_ejecucion)
    filtro = _filtro(desde, hasta, anios, sesiones, dias, lado)
    ops = metricas.filtrar(almacen_bt.operaciones(id_ejecucion), filtro)
    periodo_desde = max(meta["desde"], filtro.desde) if filtro.desde else meta["desde"]
    periodo_hasta = min(meta["hasta"], filtro.hasta) if filtro.hasta else meta["hasta"]
    reto = None
    if meta["reto"]:
        intentos = almacen_bt.intentos(id_ejecucion)
        reto = {"perfil": meta["perfil"], "titulo": meta["reto"].get("titulo"), "resumen": meta["reto"], "intentos": intentos}
    return {
        "ejecucion": _ejecucion_api(meta, _huellas()),
        "reto": reto,
        "resumen": metricas.resumen(ops, metricas.meses_entre(periodo_desde, periodo_hasta)),
        "curva": metricas.curva(ops),
        "desglose": metricas.desglose(ops),
        "total": len(ops),
        "inicio": inicio,
        "operaciones": [_operacion_api(op) for op in ops[inicio : inicio + limite]],
    }


@app.get("/api/backtests/{id_ejecucion}/tramo")
def ver_tramo_backtest(
    id_ejecucion: int,
    desde: datetime = Query(description="hora ET"),
    hasta: datetime = Query(description="hora ET"),
) -> dict:
    """Operaciones y marcas de la estrategia que se ven en un tramo del gráfico (RF-14 y RF-15)."""
    _meta_backtest(id_ejecucion)
    desde, hasta = desde.replace(tzinfo=None), hasta.replace(tzinfo=None)
    ops = [op for op in almacen_bt.operaciones(id_ejecucion) if op.apertura < hasta and op.cierre >= desde]
    return {
        "operaciones": [_operacion_api(op) for op in ops],
        "marcas": [
            {
                "tipo": m.tipo,
                "t": metricas.segundos_grafico(m.instante),
                "t_fin": metricas.segundos_grafico(m.fin) if m.fin else None,
                "precio": m.precio,
                "precio2": m.precio2,
                "texto": m.texto,
                "datos": _datos_marca(m),
            }
            for m in almacen_bt.marcas(id_ejecucion, desde, hasta)
        ],
    }


def _datos_marca(marca) -> dict | None:
    """Los datos de una marca `fibonacci`, con los instantes en el reloj del gráfico."""
    if not marca.datos:
        return None
    return {
        **marca.datos,
        **{
            punto: {"t": metricas.segundos_grafico(datetime.fromisoformat(marca.datos[punto]["instante"])), "precio": marca.datos[punto]["precio"]}
            for punto in ("origen", "final")
        },
    }


@app.get("/api/backtests/{id_ejecucion}/codigo")
def ver_codigo_backtest(id_ejecucion: int) -> dict:
    meta = _meta_backtest(id_ejecucion, con_codigo=True)
    return {"id": id_ejecucion, "estrategia": meta["estrategia"], "huella": meta["huella"], "codigo": meta["codigo"]}


@app.delete("/api/backtests/{id_ejecucion}")
def borrar_backtest(id_ejecucion: int) -> dict:
    try:
        almacen_bt.borrar(id_ejecucion)
    except KeyError as error:
        raise HTTPException(404, "No existe esa ejecución") from error
    return {"borrada": id_ejecucion}


# Se monta al final para que no tape las rutas de /api.
# --- Estudio (spec 010) ---


@app.post("/api/estudio/preparar")
def estudio_preparar(escena: dict) -> dict:
    """Valida una escena del Estudio y la devuelve con las velas y los tiempos en segundos.
    Lee el histórico sin el recorte del replay: el Estudio no ve ni toca la sesión de replay."""
    try:
        return estudio_escena.preparar(escena)
    except estudio_escena.EscenaNoValida as error:
        raise HTTPException(422, detail=[{"msg": e} for e in error.errores]) from error


app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
