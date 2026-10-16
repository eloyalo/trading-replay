"""Perfiles de reto de prop firm (spec 006, RF-1 y RF-2): un archivo JSON por empresa en `perfiles/`.

Se cargan al primer uso y se vuelven a leer si cambia algún archivo, para poder corregir una regla sin
reiniciar el servidor.
"""

import json
from dataclasses import dataclass
from datetime import time
from pathlib import Path

from trading_replay.config import RAIZ

CARPETA = RAIZ / "perfiles"
TIPOS_PERDIDA = ("estatica", "trailing_cierre", "trailing_intradia")
TOPES = (None, "balance_inicial", "objetivo")
EFECTOS = ("pausa", "suspende")


class PerfilNoValido(ValueError):
    pass


@dataclass(frozen=True)
class PerdidaMaxima:
    importe: float
    tipo: str  # estatica | trailing_cierre | trailing_intradia
    tope: str | None = None  # hasta dónde sube el umbral: balance_inicial | objetivo


@dataclass(frozen=True)
class LimiteDiario:
    importe: float
    efecto: str  # pausa | suspende


@dataclass(frozen=True)
class Perfil:
    id: str
    empresa: str
    nombre: str
    balance_inicial: float
    objetivo: float
    perdida_maxima: PerdidaMaxima
    limite_diario: LimiteDiario | None = None
    consistencia: float | None = None  # 0.55 = el mejor día no puede pasar del 55 % del beneficio
    dias_minimos: int = 0
    beneficio_minimo_dia: float | None = None
    contratos_maximos: float | None = None  # en minis; un micro cuenta 0,1
    hora_cierre: time | None = None  # ET
    revisado: str | None = None

    @property
    def titulo(self) -> str:
        return f"{self.empresa} {self.nombre}"

    @property
    def tope_umbral(self) -> float | None:
        """Nivel del que no pasa el umbral de la pérdida máxima."""
        if self.perdida_maxima.tope == "balance_inicial":
            return self.balance_inicial
        if self.perdida_maxima.tope == "objetivo":
            return self.balance_inicial + self.objetivo
        return None


def _perfil(empresa: str, revisado: str | None, datos: dict) -> Perfil:
    try:
        perdida = PerdidaMaxima(**datos["perdida_maxima"])
        limite = LimiteDiario(**datos["limite_diario"]) if datos.get("limite_diario") else None
        hora = datos.get("hora_cierre")
        perfil = Perfil(
            id=datos["id"],
            empresa=empresa,
            nombre=datos["nombre"],
            balance_inicial=float(datos["balance_inicial"]),
            objetivo=float(datos["objetivo"]),
            perdida_maxima=perdida,
            limite_diario=limite,
            consistencia=datos.get("consistencia"),
            dias_minimos=int(datos.get("dias_minimos") or 0),
            beneficio_minimo_dia=datos.get("beneficio_minimo_dia"),
            contratos_maximos=datos.get("contratos_maximos"),
            hora_cierre=time.fromisoformat(hora) if hora else None,
            revisado=revisado,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise PerfilNoValido(f"Perfil {datos.get('id', '?')} de {empresa}: {error}") from error
    if perdida.tipo not in TIPOS_PERDIDA or perdida.tope not in TOPES:
        raise PerfilNoValido(f"Perfil {perfil.id}: pérdida máxima no válida")
    if limite and limite.efecto not in EFECTOS:
        raise PerfilNoValido(f"Perfil {perfil.id}: efecto del límite diario no válido")
    if perfil.consistencia is not None and not 0 < perfil.consistencia <= 1:
        raise PerfilNoValido(f"Perfil {perfil.id}: la consistencia va de 0 a 1")
    return perfil


def leer(carpeta: Path = CARPETA) -> dict[str, Perfil]:
    perfiles = {}
    for archivo in sorted(carpeta.glob("*.json")):
        datos = json.loads(archivo.read_text(encoding="utf-8"))
        for cuenta in datos["cuentas"]:
            perfil = _perfil(datos["empresa"], datos.get("revisado"), cuenta)
            if perfil.id in perfiles:
                raise PerfilNoValido(f"Perfil repetido: {perfil.id}")
            perfiles[perfil.id] = perfil
    return perfiles


_cache: tuple[tuple, dict[str, Perfil]] | None = None


def todos() -> dict[str, Perfil]:
    global _cache
    firma = tuple((a.name, a.stat().st_mtime_ns) for a in sorted(CARPETA.glob("*.json")))
    if _cache is None or _cache[0] != firma:
        _cache = (firma, leer())
    return _cache[1]


def buscar(id_perfil: str) -> Perfil:
    perfil = todos().get(id_perfil)
    if perfil is None:
        raise PerfilNoValido(f"No existe el perfil {id_perfil}")
    return perfil
