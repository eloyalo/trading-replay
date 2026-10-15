"""Línea de comandos: `trading-replay datos descargar | construir | huecos`."""

import argparse
import sys
import time

from trading_replay.config import INSTRUMENTOS
from trading_replay.historico import almacen, dukascopy, huecos

UMBRAL_HUECOS = 15  # minutos de mercado abierto sin velas a partir de los que se informa


def _instrumentos(simbolos: list[str] | None):
    return [INSTRUMENTOS[s] for s in (simbolos or INSTRUMENTOS)]


def _progreso(simbolo: str, hechos: int, total: int) -> None:
    if hechos % 25 == 0 or hechos == total:
        print(f"\r  {simbolo}: {hechos}/{total} días", end="", flush=True)
        if hechos == total:
            print()


def descargar(args) -> int:
    instrumentos = _instrumentos(args.simbolos)
    inicio = time.monotonic()
    print("Descargando de Dukascopy (se puede cortar y relanzar sin perder lo descargado)...")
    errores = dukascopy.descargar(instrumentos, _progreso)
    print(f"Descarga terminada en {(time.monotonic() - inicio) / 60:.1f} min")
    fallidos = sum(len(e) for e in errores.values())
    for simbolo, lista in errores.items():
        for dia, error in lista[:5]:
            print(f"  ERROR {simbolo} {dia}: {error}")
    if fallidos:
        print(f"{fallidos} días con error: relanza el comando para reintentarlos.")
    construir(args)
    return 1 if fallidos else 0


def construir(args) -> int:
    for instrumento in _instrumentos(args.simbolos):
        velas = almacen.construir(instrumento)
        print(f"{instrumento.simbolo}: {velas:,} velas de 1m".replace(",", "."))
    informar_huecos(args)
    return 0


def informar_huecos(args) -> int:
    for instrumento in _instrumentos(args.simbolos):
        if not almacen.ruta_parquet(instrumento.simbolo).exists():
            continue
        encontrados = huecos.generar_informe(instrumento, UMBRAL_HUECOS)
        minutos = sum(m for _, _, m in encontrados)
        print(f"{instrumento.simbolo}: {len(encontrados)} huecos ({minutos / 60:.0f} h de mercado sin datos)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trading-replay")
    grupos = parser.add_subparsers(dest="grupo", required=True)

    datos = grupos.add_parser("datos", help="histórico de precios")
    acciones = datos.add_subparsers(dest="accion", required=True)
    for nombre, funcion, ayuda in (
        ("descargar", descargar, "descarga lo que falte y reconstruye"),
        ("construir", construir, "regenera los Parquet a partir de lo descargado"),
        ("huecos", informar_huecos, "regenera el informe de huecos"),
    ):
        sub = acciones.add_parser(nombre, help=ayuda)
        sub.add_argument("simbolos", nargs="*", metavar="SIMBOLO",
                         help=f"por defecto todos ({', '.join(INSTRUMENTOS)})")
        sub.set_defaults(funcion=funcion)

    args = parser.parse_args(argv)
    args.simbolos = [s.upper() for s in args.simbolos]
    desconocidos = set(args.simbolos) - set(INSTRUMENTOS)
    if desconocidos:
        parser.error(f"símbolos desconocidos: {', '.join(sorted(desconocidos))}")
    return args.funcion(args)


if __name__ == "__main__":
    sys.exit(main())
