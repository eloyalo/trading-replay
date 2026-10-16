"""Base de datos de las cuentas (SQLite, ADR 0001): cuentas, órdenes, ejecuciones, posiciones y operaciones.

Las horas de mercado se guardan en ET sin zona, como el reloj del replay; las reales, en UTC.
"""

import sqlite3
from dataclasses import dataclass, field, fields
from datetime import UTC, datetime
from pathlib import Path

from trading_replay.config import carpeta_datos
from trading_replay.operativa.motor import Ejecucion, Operacion, Orden, Posicion
from trading_replay.operativa.reto import Dia, EstadoReto

ESQUEMA = """
CREATE TABLE IF NOT EXISTS cuentas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    balance_inicial REAL NOT NULL,
    balance REAL NOT NULL,
    spread_ticks INTEGER NOT NULL,
    deslizamiento_ticks INTEGER NOT NULL,
    comision_mini REAL NOT NULL,
    comision_micro REAL NOT NULL,
    activa INTEGER NOT NULL DEFAULT 0,
    creada TEXT NOT NULL,
    instante_replay TEXT,
    sesion_replay TEXT
);
CREATE TABLE IF NOT EXISTS ordenes (
    id TEXT PRIMARY KEY,
    cuenta INTEGER NOT NULL REFERENCES cuentas(id),
    contrato TEXT NOT NULL,
    lado INTEGER NOT NULL,
    tipo TEXT NOT NULL,
    cantidad INTEGER NOT NULL,
    precio REAL,
    sl_puntos REAL,
    tp_puntos REAL,
    papel TEXT NOT NULL,
    grupo TEXT,
    activa_desde TEXT,
    nacida_en TEXT,
    estado TEXT NOT NULL,
    precio_ejecucion REAL,
    ejecutada TEXT,
    sesion TEXT,
    creada_real TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ordenes_pendientes ON ordenes (cuenta, estado);
CREATE TABLE IF NOT EXISTS ejecuciones (
    id TEXT PRIMARY KEY,
    cuenta INTEGER NOT NULL REFERENCES cuentas(id),
    orden TEXT NOT NULL,
    contrato TEXT NOT NULL,
    lado INTEGER NOT NULL,
    cantidad INTEGER NOT NULL,
    precio REAL NOT NULL,
    comision REAL NOT NULL,
    instante TEXT NOT NULL,
    papel TEXT NOT NULL,
    sesion TEXT,
    creada_real TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ejecuciones_sesion ON ejecuciones (cuenta, sesion);
CREATE TABLE IF NOT EXISTS posiciones (
    cuenta INTEGER NOT NULL REFERENCES cuentas(id),
    contrato TEXT NOT NULL,
    cantidad INTEGER NOT NULL,
    precio_medio REAL NOT NULL,
    operacion TEXT,
    PRIMARY KEY (cuenta, contrato)
);
CREATE TABLE IF NOT EXISTS operaciones (
    id TEXT PRIMARY KEY,
    cuenta INTEGER NOT NULL REFERENCES cuentas(id),
    contrato TEXT NOT NULL,
    lado INTEGER NOT NULL,
    apertura TEXT NOT NULL,
    cantidad INTEGER NOT NULL,
    suma_entrada REAL NOT NULL,
    contratos_entrada INTEGER NOT NULL,
    suma_salida REAL NOT NULL,
    contratos_salida INTEGER NOT NULL,
    pnl_bruto REAL NOT NULL,
    comisiones REAL NOT NULL,
    cierre TEXT,
    sl_inicial REAL,
    sesion TEXT
);
CREATE INDEX IF NOT EXISTS operaciones_cuenta ON operaciones (cuenta, cierre);
CREATE TABLE IF NOT EXISTS retos (
    cuenta INTEGER PRIMARY KEY REFERENCES cuentas(id),
    perfil TEXT NOT NULL,
    intento INTEGER NOT NULL,
    estado TEXT NOT NULL,
    motivo TEXT,
    fin TEXT,
    umbral REAL NOT NULL,
    pico REAL NOT NULL,
    sesion_dia TEXT,
    balance_inicio_dia REAL NOT NULL,
    operado INTEGER NOT NULL,
    bloqueo TEXT,
    bloqueo_hasta TEXT
);
CREATE TABLE IF NOT EXISTS intentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cuenta INTEGER NOT NULL REFERENCES cuentas(id),
    perfil TEXT NOT NULL,
    numero INTEGER NOT NULL,
    resultado TEXT NOT NULL,
    motivo TEXT,
    dias INTEGER NOT NULL,
    beneficio REAL NOT NULL,
    mejor_dia REAL NOT NULL,
    fin_real TEXT NOT NULL
);
"""

# Campos de los modelos que son horas de mercado.
FECHAS = {"activa_desde", "nacida_en", "ejecutada", "instante", "apertura", "cierre", "instante_replay", "fin", "bloqueo_hasta"}


@dataclass
class Cuenta:
    nombre: str
    balance_inicial: float
    balance: float
    spread_ticks: int = 1
    deslizamiento_ticks: int = 0
    comision_mini: float = 2.5
    comision_micro: float = 0.75
    activa: bool = False
    creada: str = field(default_factory=lambda: ahora_real())
    instante_replay: datetime | None = None
    sesion_replay: str | None = None
    id: int | None = None


def ahora_real() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def ruta() -> Path:
    return carpeta_datos() / "cuentas.sqlite"


def conectar(destino: Path) -> sqlite3.Connection:
    destino.parent.mkdir(parents=True, exist_ok=True)
    # Una sola conexión compartida, protegida por el cerrojo del servicio.
    con = sqlite3.connect(destino, check_same_thread=False, isolation_level=None)
    con.row_factory = sqlite3.Row
    # En el disco NTFS del proyecto, cada transacción tarda unos 100 ms con el diario por defecto y
    # 0,1 ms con WAL. Con NORMAL, un corte de luz puede perder la última transacción, nunca corromper.
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA synchronous = NORMAL")
    con.executescript(ESQUEMA)
    return con


def _a_bd(nombre: str, valor):
    if isinstance(valor, datetime):
        return valor.isoformat()
    if isinstance(valor, bool):
        return int(valor)
    if isinstance(valor, Operacion):  # la posición guarda solo el id de su operación
        return valor.id
    return valor


def _de_bd(nombre: str, valor):
    if valor is not None and nombre in FECHAS:
        return datetime.fromisoformat(valor)
    return valor


def guardar(con: sqlite3.Connection, tabla: str, objeto, clave=("id",), conservar=("creada_real",), **extra) -> None:
    """Inserta o actualiza `objeto`. Al actualizar, las columnas de `conservar` no se tocan."""
    datos = {f.name: _a_bd(f.name, getattr(objeto, f.name)) for f in fields(objeto) if f.name != "id" or objeto.id is not None}
    datos.update(extra)
    columnas = ", ".join(datos)
    marcas = ", ".join("?" * len(datos))
    cambios = ", ".join(f"{c} = excluded.{c}" for c in datos if c not in clave and c not in conservar)
    con.execute(
        f"INSERT INTO {tabla} ({columnas}) VALUES ({marcas}) ON CONFLICT ({', '.join(clave)}) DO UPDATE SET {cambios}",
        list(datos.values()),
    )


def cargar(con: sqlite3.Connection, clase, tabla: str, condicion: str = "1", parametros=(), orden: str = "rowid"):
    nombres = [f.name for f in fields(clase)]
    filas = con.execute(f"SELECT {', '.join(nombres)} FROM {tabla} WHERE {condicion} ORDER BY {orden}", parametros)
    return [clase(**{n: _de_bd(n, fila[n]) for n in nombres}) for fila in filas]


def crear_cuenta(con: sqlite3.Connection, cuenta: Cuenta) -> Cuenta:
    guardar(con, "cuentas", cuenta)
    cuenta.id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
    return cuenta


def cuentas(con: sqlite3.Connection) -> list[Cuenta]:
    return [_cuenta(c) for c in cargar(con, Cuenta, "cuentas", orden="id")]


def _cuenta(cuenta: Cuenta) -> Cuenta:
    cuenta.activa = bool(cuenta.activa)
    return cuenta


def activar(con: sqlite3.Connection, id_cuenta: int) -> None:
    con.execute("UPDATE cuentas SET activa = (id = ?)", (id_cuenta,))


def borrar_historial(con: sqlite3.Connection, id_cuenta: int) -> None:
    """Borra las órdenes, ejecuciones, posiciones y operaciones de una cuenta."""
    for tabla in ("ordenes", "ejecuciones", "posiciones", "operaciones"):
        con.execute(f"DELETE FROM {tabla} WHERE cuenta = ?", (id_cuenta,))


def borrar_cuenta(con: sqlite3.Connection, id_cuenta: int) -> None:
    borrar_historial(con, id_cuenta)
    for tabla in ("retos", "intentos"):
        con.execute(f"DELETE FROM {tabla} WHERE cuenta = ?", (id_cuenta,))
    con.execute("DELETE FROM cuentas WHERE id = ?", (id_cuenta,))


def ordenes_pendientes(con: sqlite3.Connection, id_cuenta: int) -> list[Orden]:
    return cargar(con, Orden, "ordenes", "cuenta = ? AND estado = 'pendiente'", (id_cuenta,))


def posiciones_abiertas(con: sqlite3.Connection, id_cuenta: int) -> list[Posicion]:
    """Posiciones con su operación abierta."""
    abiertas = {o.id: o for o in cargar(con, Operacion, "operaciones", "cuenta = ? AND cierre IS NULL", (id_cuenta,))}
    filas = con.execute(
        "SELECT contrato, cantidad, precio_medio, operacion FROM posiciones WHERE cuenta = ? AND cantidad != 0", (id_cuenta,)
    )
    return [Posicion(f["contrato"], f["cantidad"], f["precio_medio"], abiertas.get(f["operacion"])) for f in filas]


def operaciones_cerradas(con: sqlite3.Connection, id_cuenta: int, limite: int) -> list[tuple[Operacion, str | None]]:
    """Las `limite` operaciones cerradas más recientes, con su sesión de replay."""
    filas = con.execute(
        "SELECT id, sesion FROM operaciones WHERE cuenta = ? AND cierre IS NOT NULL ORDER BY rowid DESC LIMIT ?",
        (id_cuenta, limite),
    ).fetchall()
    sesiones = {f["id"]: f["sesion"] for f in filas}
    if not sesiones:
        return []
    marcas = ", ".join("?" * len(sesiones))
    operaciones = cargar(con, Operacion, "operaciones", f"id IN ({marcas})", list(sesiones), orden="rowid DESC")
    return [(o, sesiones[o.id]) for o in operaciones]


def pnl_sesion(con: sqlite3.Connection, id_cuenta: int, sesion: str) -> float:
    """PnL neto de las operaciones cerradas en una sesión de replay."""
    valor = con.execute(
        "SELECT sum(pnl_bruto - comisiones) FROM operaciones WHERE cuenta = ? AND sesion = ? AND cierre IS NOT NULL",
        (id_cuenta, sesion),
    ).fetchone()[0]
    return round(valor or 0.0, 2)


def ejecuciones_de_sesion(con: sqlite3.Connection, id_cuenta: int, sesion: str) -> list[Ejecucion]:
    return cargar(con, Ejecucion, "ejecuciones", "cuenta = ? AND sesion = ?", (id_cuenta, sesion))



# --- Retos (spec 006) ---


def reto(con: sqlite3.Connection, id_cuenta: int) -> EstadoReto | None:
    encontrados = cargar(con, EstadoReto, "retos", "cuenta = ?", (id_cuenta,))
    if not encontrados:
        return None
    estado = encontrados[0]
    estado.operado = bool(estado.operado)
    return estado


def perfiles_de_cuentas(con: sqlite3.Connection) -> dict[int, str]:
    return {f["cuenta"]: f["perfil"] for f in con.execute("SELECT cuenta, perfil FROM retos")}


def guardar_intento(con: sqlite3.Connection, id_cuenta: int, **datos) -> None:
    datos = {"cuenta": id_cuenta, "fin_real": ahora_real(), **datos}
    columnas = ", ".join(datos)
    con.execute(f"INSERT INTO intentos ({columnas}) VALUES ({', '.join('?' * len(datos))})", list(datos.values()))


def intentos(con: sqlite3.Connection, id_cuenta: int) -> list[dict]:
    filas = con.execute(
        "SELECT numero, resultado, motivo, dias, beneficio, mejor_dia, fin_real FROM intentos WHERE cuenta = ? ORDER BY id DESC",
        (id_cuenta,),
    )
    return [dict(f) for f in filas]


def dias(con: sqlite3.Connection, id_cuenta: int) -> list[Dia]:
    """Días operados (sesiones de replay con alguna ejecución) en orden, con el PnL neto de sus
    operaciones cerradas."""
    filas = con.execute(
        """
        SELECT e.sesion, coalesce(o.pnl, 0) AS pnl
        FROM (SELECT sesion, min(rowid) AS orden FROM ejecuciones WHERE cuenta = ? AND sesion IS NOT NULL GROUP BY sesion) e
        LEFT JOIN (
            SELECT sesion, sum(pnl_bruto - comisiones) AS pnl FROM operaciones
            WHERE cuenta = ? AND cierre IS NOT NULL GROUP BY sesion
        ) o ON o.sesion = e.sesion
        ORDER BY e.orden
        """,
        (id_cuenta, id_cuenta),
    )
    return [Dia(f["sesion"], round(f["pnl"], 2)) for f in filas]


def estadisticas(con: sqlite3.Connection, id_cuenta: int) -> dict:
    """Operaciones cerradas de la cuenta: cuántas, ganadoras, mayor ganancia y pérdida, comisiones."""
    f = con.execute(
        """
        SELECT count(*) AS operaciones,
               coalesce(sum(pnl_bruto - comisiones > 0), 0) AS ganadoras,
               coalesce(max(pnl_bruto - comisiones), 0) AS mayor_ganancia,
               coalesce(min(pnl_bruto - comisiones), 0) AS mayor_perdida,
               coalesce(sum(comisiones), 0) AS comisiones
        FROM operaciones WHERE cuenta = ? AND cierre IS NOT NULL
        """,
        (id_cuenta,),
    ).fetchone()
    return {k: round(f[k], 2) for k in f.keys()}

