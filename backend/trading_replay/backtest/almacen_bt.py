"""Historial de backtests (spec 008, RF-17) en `datos/backtests.sqlite`, aparte de las cuentas para
que borrar o rehacer backtests no las toque.

Las horas de mercado se guardan en ET sin zona; la de creación, en UTC.
"""

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

from trading_replay.backtest.ejecutor import Marca, OperacionBT, Resultado
from trading_replay.config import carpeta_datos

ESQUEMA = """
CREATE TABLE IF NOT EXISTS ejecuciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    estrategia TEXT NOT NULL,
    nombre TEXT NOT NULL,
    huella TEXT NOT NULL,
    codigo TEXT NOT NULL,
    parametros TEXT NOT NULL,
    simbolo TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    desde TEXT NOT NULL,
    hasta TEXT NOT NULL,
    costes TEXT NOT NULL,
    creada TEXT NOT NULL,
    segundos REAL NOT NULL,
    resumen TEXT NOT NULL,
    perfil TEXT,                      -- reto de la spec 009, o NULL
    reto TEXT                         -- JSON con el resumen del reto, o NULL
);
CREATE TABLE IF NOT EXISTS operaciones (
    ejecucion INTEGER NOT NULL REFERENCES ejecuciones(id) ON DELETE CASCADE,
    numero INTEGER NOT NULL,
    contrato TEXT NOT NULL,
    lado INTEGER NOT NULL,
    cantidad INTEGER NOT NULL,
    apertura TEXT NOT NULL,
    cierre TEXT NOT NULL,
    entrada REAL NOT NULL,
    salida REAL NOT NULL,
    sl_inicial REAL,
    sl_final REAL,
    tp_final REAL,
    motivo_entrada TEXT,
    motivo_salida TEXT NOT NULL,
    pnl_bruto REAL NOT NULL,
    comisiones REAL NOT NULL,
    riesgo REAL,
    dudosa INTEGER NOT NULL,
    minuto_entrada TEXT,
    minuto_salida TEXT,
    intento INTEGER,
    PRIMARY KEY (ejecucion, numero)
);
CREATE TABLE IF NOT EXISTS marcas (
    ejecucion INTEGER NOT NULL REFERENCES ejecuciones(id) ON DELETE CASCADE,
    tipo TEXT NOT NULL,
    instante TEXT NOT NULL,
    fin TEXT,
    precio REAL,
    precio2 REAL,
    texto TEXT
);
CREATE INDEX IF NOT EXISTS marcas_instante ON marcas (ejecucion, instante);
CREATE TABLE IF NOT EXISTS intentos (
    ejecucion INTEGER NOT NULL REFERENCES ejecuciones(id) ON DELETE CASCADE,
    numero INTEGER NOT NULL,
    inicio TEXT NOT NULL,
    fin TEXT,
    resultado TEXT NOT NULL,
    motivo TEXT,
    dias INTEGER NOT NULL,
    beneficio REAL NOT NULL,
    mejor_dia REAL NOT NULL,
    operaciones INTEGER NOT NULL,
    PRIMARY KEY (ejecucion, numero)
);
"""

# Columnas añadidas después de crear la base de datos: se añaden a las que ya existían (spec 009).
COLUMNAS_NUEVAS = [
    ("ejecuciones", "perfil", "TEXT"),
    ("ejecuciones", "reto", "TEXT"),
    ("operaciones", "intento", "INTEGER"),
    ("marcas", "datos", "TEXT"),  # spec 012: JSON de la marca `fibonacci`
]

CAMPOS_OPERACION = (
    "numero", "contrato", "lado", "cantidad", "apertura", "cierre", "entrada", "salida", "sl_inicial", "sl_final",
    "tp_final", "motivo_entrada", "motivo_salida", "pnl_bruto", "comisiones", "riesgo", "dudosa", "minuto_entrada",
    "minuto_salida", "intento",
)  # fmt: skip
CAMPOS_INTENTO = ("numero", "inicio", "fin", "resultado", "motivo", "dias", "beneficio", "mejor_dia", "operaciones")


def ruta() -> Path:
    return carpeta_datos() / "backtests.sqlite"


_cerrojo = threading.Lock()
_conexion: tuple[Path, sqlite3.Connection] | None = None


def _con() -> sqlite3.Connection:
    """Conexión compartida (se rehace si cambia la carpeta de datos, en los tests). Usar con `_cerrojo`."""
    global _conexion
    destino = ruta()
    if _conexion is None or _conexion[0] != destino:
        destino.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(destino, check_same_thread=False, isolation_level=None)
        con.row_factory = sqlite3.Row
        # Como en cuentas.sqlite: en el disco NTFS, WAL hace las transacciones mil veces más rápidas.
        con.execute("PRAGMA journal_mode = WAL")
        con.execute("PRAGMA synchronous = NORMAL")
        con.execute("PRAGMA foreign_keys = ON")
        con.executescript(ESQUEMA)
        for tabla, columna, tipo in COLUMNAS_NUEVAS:
            if columna not in {f["name"] for f in con.execute(f"PRAGMA table_info({tabla})")}:
                con.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {tipo}")
        _conexion = (destino, con)
        _cache.clear()  # era de otra base de datos
    return _conexion[1]


def _texto(momento: datetime | None) -> str | None:
    return momento.isoformat() if momento else None


def _fecha(texto: str | None) -> datetime | None:
    return datetime.fromisoformat(texto) if texto else None


def guardar(meta: dict, resultado: Resultado, resumen: dict, reto: dict | None = None) -> int:
    """Guarda una ejecución terminada. `meta`: estrategia, nombre, huella, codigo, parametros, simbolo,
    timeframe, desde, hasta, costes y perfil. `reto`: el resumen del reto, si se lanzó con uno."""
    with _cerrojo:
        con = _con()
        con.execute("BEGIN")
        try:
            cursor = con.execute(
                """INSERT INTO ejecuciones (estrategia, nombre, huella, codigo, parametros, simbolo, timeframe, desde, hasta,
                                            costes, creada, segundos, resumen, perfil, reto)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    meta["estrategia"], meta["nombre"], meta["huella"], meta["codigo"], json.dumps(meta["parametros"]),
                    meta["simbolo"], meta["timeframe"], _texto(meta["desde"]), _texto(meta["hasta"]),
                    json.dumps(meta["costes"]), datetime.now(UTC).isoformat(timespec="seconds"),
                    round(resultado.segundos, 2), json.dumps(resumen), meta.get("perfil"),
                    json.dumps(reto) if reto is not None else None,
                ),
            )  # fmt: skip
            id_ejecucion = cursor.lastrowid
            con.executemany(
                f"INSERT INTO operaciones (ejecucion, {', '.join(CAMPOS_OPERACION)}) VALUES (?{', ?' * len(CAMPOS_OPERACION)})",
                [
                    (id_ejecucion, *(_texto(v) if isinstance(v, datetime) else v for v in (getattr(op, c) for c in CAMPOS_OPERACION)))
                    for op in resultado.operaciones
                ],
            )
            con.executemany(
                "INSERT INTO marcas (ejecucion, tipo, instante, fin, precio, precio2, texto, datos) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (id_ejecucion, m.tipo, _texto(m.instante), _texto(m.fin), m.precio, m.precio2, m.texto, json.dumps(m.datos) if m.datos else None)
                    for m in resultado.marcas
                ],
            )
            if resultado.reto is not None:
                con.executemany(
                    f"INSERT INTO intentos (ejecucion, {', '.join(CAMPOS_INTENTO)}) VALUES (?{', ?' * len(CAMPOS_INTENTO)})",
                    [
                        (id_ejecucion, *(_texto(v) if isinstance(v, datetime) else v for v in (getattr(i, c) for c in CAMPOS_INTENTO)))
                        for i in resultado.reto.intentos
                    ],
                )
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise
    _cache.clear()
    return id_ejecucion


def _meta(fila: sqlite3.Row, con_codigo: bool = False) -> dict:
    meta = {
        "id": fila["id"],
        "estrategia": fila["estrategia"],
        "nombre": fila["nombre"],
        "huella": fila["huella"],
        "parametros": json.loads(fila["parametros"]),
        "simbolo": fila["simbolo"],
        "timeframe": fila["timeframe"],
        "desde": _fecha(fila["desde"]),
        "hasta": _fecha(fila["hasta"]),
        "costes": json.loads(fila["costes"]),
        "creada": fila["creada"],
        "segundos": fila["segundos"],
        "resumen": json.loads(fila["resumen"]),
        "perfil": fila["perfil"],
        "reto": json.loads(fila["reto"]) if fila["reto"] else None,
    }
    if con_codigo:
        meta["codigo"] = fila["codigo"]
    return meta


def listar() -> list[dict]:
    """Todas las ejecuciones, la más reciente primero, sin el código ni las operaciones."""
    with _cerrojo:
        filas = _con().execute("SELECT * FROM ejecuciones ORDER BY id DESC").fetchall()
    return [_meta(f) for f in filas]


def ejecucion(id_ejecucion: int, con_codigo: bool = False) -> dict:
    with _cerrojo:
        fila = _con().execute("SELECT * FROM ejecuciones WHERE id = ?", (id_ejecucion,)).fetchone()
    if fila is None:
        raise KeyError(id_ejecucion)
    return _meta(fila, con_codigo)


# Operaciones de la última ejecución que se ha mirado: al recorrerla en el gráfico se piden muchas veces.
_cache: dict[int, list[OperacionBT]] = {}


def operaciones(id_ejecucion: int) -> list[OperacionBT]:
    if id_ejecucion in _cache:
        return _cache[id_ejecucion]
    with _cerrojo:
        filas = _con().execute(
            f"SELECT {', '.join(CAMPOS_OPERACION)} FROM operaciones WHERE ejecucion = ? ORDER BY numero", (id_ejecucion,)
        ).fetchall()
    ops = [
        OperacionBT(
            **{
                **dict(f),
                **{c: _fecha(f[c]) for c in ("apertura", "cierre", "minuto_entrada", "minuto_salida")},
                "dudosa": bool(f["dudosa"]),
            }
        )
        for f in filas
    ]
    _cache.clear()
    _cache[id_ejecucion] = ops
    return ops


def marcas(id_ejecucion: int, desde: datetime, hasta: datetime) -> list[Marca]:
    """Marcas que se ven en [desde, hasta): las que empiezan antes de `hasta` y acaban después de `desde`."""
    with _cerrojo:
        filas = _con().execute(
            """SELECT tipo, instante, fin, precio, precio2, texto, datos FROM marcas
               WHERE ejecucion = ? AND instante < ? AND coalesce(fin, instante) >= ?
               ORDER BY instante""",
            (id_ejecucion, _texto(hasta), _texto(desde)),
        ).fetchall()
    return [
        Marca(f["tipo"], _fecha(f["instante"]), _fecha(f["fin"]), f["precio"], f["precio2"], f["texto"], json.loads(f["datos"]) if f["datos"] else None)
        for f in filas
    ]


def intentos(id_ejecucion: int) -> list[dict]:
    """Intentos del reto de una ejecución (spec 009), en orden."""
    with _cerrojo:
        filas = _con().execute(
            f"SELECT {', '.join(CAMPOS_INTENTO)} FROM intentos WHERE ejecucion = ? ORDER BY numero", (id_ejecucion,)
        ).fetchall()
    return [dict(f) for f in filas]


def borrar(id_ejecucion: int) -> None:
    with _cerrojo:
        cursor = _con().execute("DELETE FROM ejecuciones WHERE id = ?", (id_ejecucion,))
    _cache.clear()
    if not cursor.rowcount:
        raise KeyError(id_ejecucion)
