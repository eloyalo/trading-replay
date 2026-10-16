"""Servidor principal: API bajo /api y frontend estático en /."""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from trading_replay import __version__, replay
from trading_replay.config import INSTRUMENTOS
from trading_replay.historico import almacen
from trading_replay.operativa import servicio
from trading_replay.operativa.perfiles import PerfilNoValido
from trading_replay.operativa.motor import MAX_CONTRATOS, OrdenNoValida

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


# Se monta al final para que no tape las rutas de /api.
app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
