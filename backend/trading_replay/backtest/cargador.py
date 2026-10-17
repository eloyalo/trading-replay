"""Carga de las estrategias de `estrategias/` (spec 008, RF-1, RF-5 y RF-18).

Cada `estrategias/*.py` (salvo los que empiezan por `_`) es una estrategia; su id es el nombre del
archivo. Se vuelven a cargar si cambia el archivo, como los perfiles de reto. Las estrategias son
código del usuario que corre en su propio servidor local: no hay sandbox.
"""

import hashlib
import importlib.util
import re
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from trading_replay.backtest.estrategia import TIMEFRAMES, Estrategia, Parametro
from trading_replay.config import carpeta_estrategias


@dataclass(eq=False)
class ErrorEstrategia(Exception):
    """Error de una estrategia, con el archivo y la línea donde está."""

    mensaje: str
    archivo: str | None = None
    linea: int | None = None
    vela: str | None = None  # en los errores al ejecutar, la vela en la que falló (hora ET)

    def __str__(self):
        donde = f"{self.archivo}, línea {self.linea}: " if self.archivo and self.linea else ""
        return donde + self.mensaje

    def api(self) -> dict:
        return {"mensaje": self.mensaje, "archivo": self.archivo, "linea": self.linea, "vela": self.vela}


@dataclass
class InfoEstrategia:
    id: str
    ruta: Path
    huella: str  # SHA-256 del código
    codigo: str
    clase: type[Estrategia] | None = None
    error: ErrorEstrategia | None = None
    descripcion: str = ""
    modulo: str = ""
    marca: tuple = field(default=(), repr=False)  # (fecha de modificación, tamaño) con que se cargó

    @property
    def nombre(self) -> str:
        return self.clase.nombre if self.clase else self.id

    def api(self) -> dict:
        return {
            "id": self.id,
            "nombre": self.nombre,
            "descripcion": self.descripcion,
            "timeframe": self.clase.timeframe if self.clase else None,
            "parametros": [p.api(clave) for clave, p in self.clase.parametros.items()] if self.clase else [],
            "ruta": str(self.ruta),
            "huella": self.huella,
            "error": self.error.api() if self.error else None,
        }


def huella(codigo: str) -> str:
    return hashlib.sha256(codigo.encode()).hexdigest()


def error_desde(excepcion: BaseException, carpeta: Path | None = None) -> ErrorEstrategia:
    """Traduce una excepción a un `ErrorEstrategia` con el último punto del traceback que está dentro
    de la carpeta de estrategias (lo que ha escrito el usuario, no el código de la app)."""
    carpeta = (carpeta or carpeta_estrategias()).resolve()
    mensaje = f"{type(excepcion).__name__}: {excepcion}"
    if isinstance(excepcion, SyntaxError):
        mensaje = f"{type(excepcion).__name__}: {excepcion.msg}"
        if excepcion.filename:
            return ErrorEstrategia(mensaje, Path(excepcion.filename).name, excepcion.lineno)
    archivo = linea = None
    for marco in traceback.extract_tb(excepcion.__traceback__):
        ruta = Path(marco.filename).resolve()
        if ruta.is_relative_to(carpeta):
            archivo, linea = ruta.name, marco.lineno
    return ErrorEstrategia(mensaje, archivo, linea)


def _validar_clase(clase: type[Estrategia], archivo: str) -> None:
    def error(mensaje):
        raise ErrorEstrategia(mensaje, archivo)

    if not isinstance(clase.nombre, str) or not clase.nombre.strip():
        error("Falta el nombre: nombre = \"...\"")
    if clase.timeframe not in TIMEFRAMES:
        error(f"Timeframe no válido: {clase.timeframe!r}. Opciones: {', '.join(TIMEFRAMES)}")
    if not isinstance(clase.parametros, dict) or not all(isinstance(p, Parametro) for p in clase.parametros.values()):
        error("`parametros` tiene que ser un diccionario de Parametro(...)")
    if clase.al_cerrar_vela is Estrategia.al_cerrar_vela:
        error("Falta al_cerrar_vela(self, vela)")
    for clave, parametro in clase.parametros.items():
        try:
            parametro.validar(parametro.defecto)
        except ValueError as e:
            error(f"El valor por defecto de «{clave}» no cumple sus límites: {e}")


def _cargar(id_estrategia: str, ruta: Path) -> InfoEstrategia:
    codigo = ruta.read_text(encoding="utf-8")
    info = InfoEstrategia(id_estrategia, ruta, huella(codigo), codigo)
    nombre_modulo = info.modulo = f"estrategia_usuario_{id_estrategia}_{info.huella[:12]}"
    try:
        spec = importlib.util.spec_from_file_location(nombre_modulo, ruta)
        modulo = importlib.util.module_from_spec(spec)
        sys.modules[nombre_modulo] = modulo  # lo necesitan, por ejemplo, las dataclasses
        try:
            spec.loader.exec_module(modulo)
        except BaseException:
            sys.modules.pop(nombre_modulo, None)
            raise
        clases = [
            c
            for c in vars(modulo).values()
            if isinstance(c, type) and issubclass(c, Estrategia) and c is not Estrategia and c.__module__ == nombre_modulo
        ]
        if len(clases) != 1:
            raise ErrorEstrategia(
                "El archivo tiene que definir una clase que herede de Estrategia" if not clases else "El archivo define más de una estrategia",
                ruta.name,
            )
        _validar_clase(clases[0], ruta.name)
        info.clase = clases[0]
        info.descripcion = (modulo.__doc__ or clases[0].__doc__ or "").strip()
    except ErrorEstrategia as error:
        info.error = error
    except Exception as excepcion:  # cualquier fallo del código del usuario se enseña, no tumba la app
        info.error = error_desde(excepcion, ruta.parent)
    return info


_cache: dict[str, InfoEstrategia] = {}


def _marca(ruta: Path) -> tuple:
    estado = ruta.stat()
    return estado.st_mtime_ns, estado.st_size


def listar() -> list[InfoEstrategia]:
    """Todas las estrategias, recargando las que han cambiado."""
    carpeta = carpeta_estrategias()
    rutas = sorted(carpeta.glob("*.py")) if carpeta.is_dir() else []
    vistas = {}
    for ruta in rutas:
        if ruta.name.startswith("_"):
            continue
        id_estrategia = ruta.stem
        marca = _marca(ruta)
        info = _cache.get(id_estrategia)
        if info is None or info.marca != marca or info.ruta != ruta:
            if info is not None:
                sys.modules.pop(info.modulo, None)
            info = _cargar(id_estrategia, ruta)
            info.marca = marca
        vistas[id_estrategia] = info
    _cache.clear()
    _cache.update(vistas)
    return list(vistas.values())


def buscar(id_estrategia: str) -> InfoEstrategia:
    for info in listar():
        if info.id == id_estrategia:
            return info
    raise KeyError(id_estrategia)


_NOMBRE = re.compile(r'^(\s*nombre\s*=\s*)(["\'])(.*?)\2', re.MULTILINE)


def duplicar(id_estrategia: str) -> InfoEstrategia:
    """Copia la estrategia a `<id>_2.py` (o el primer número libre), con "(copia N)" en el nombre."""
    original = buscar(id_estrategia)
    carpeta = original.ruta.parent
    base = re.sub(r"_\d+$", "", id_estrategia)
    numero = 2
    while (carpeta / f"{base}_{numero}.py").exists():
        numero += 1
    destino = carpeta / f"{base}_{numero}.py"
    codigo = _NOMBRE.sub(
        lambda m: f"{m.group(1)}{m.group(2)}{re.sub(r' \(copia \d+\)$', '', m.group(3))} (copia {numero}){m.group(2)}",
        original.codigo,
        count=1,
    )
    destino.write_text(codigo, encoding="utf-8")
    return buscar(destino.stem)
