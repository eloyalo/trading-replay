"""Línea de comandos: `trading-replay datos descargar | construir | huecos` y `trading-replay estudio validar | capturar`."""

import argparse
import sys
import time
from pathlib import Path

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


def estudio_validar(args) -> int:
    from trading_replay.estudio.captura import cargar_escena
    from trading_replay.estudio.escena import EscenaNoValida, preparar

    try:
        e = preparar(cargar_escena(args.escena))
    except EscenaNoValida as error:
        for mensaje in error.errores:
            print(f"ERROR {mensaje}")
        return 1
    print(f"{args.escena}: válida · {e['simbolo']} {e['tf']} · {len(e['velas'])} velas · "
          f"{len(e['pasos'])} pasos · {e['duracion']:g} s · {e['lienzo']['aspecto']}")
    return 0


def estudio_capturar(args) -> int:
    from trading_replay.estudio import captura
    from trading_replay.estudio.escena import EscenaNoValida

    escena = captura.cargar_escena(args.escena)
    sufijo = "_vertical" if args.aspecto == "9:16" else ""
    salida = args.salida or args.escena.with_name(f"{args.escena.stem}{sufijo}.mp4")
    if salida.is_dir() or (args.salida and not salida.suffix):
        salida = salida / f"{args.escena.stem}{sufijo}.mp4"
    try:
        if args.foto:
            for ruta in captura.fotos(escena, args.foto, salida.with_suffix(".png"), args.aspecto):
                print(ruta)
            return 0

        def progreso(hechos, total):
            if hechos % 30 == 0 or hechos == total:
                print(f"\r  {hechos}/{total} fotogramas", end="", flush=True)

        r = captura.video(escena, salida, args.fps, args.aspecto, progreso)
    except EscenaNoValida as error:
        for mensaje in error.errores:
            print(f"ERROR {mensaje}")
        return 1
    except captura.ErrorCaptura as error:
        print(f"ERROR {error}")
        return 1
    print(f"\n{r['ruta']}: {r['fotogramas']} fotogramas en {r['segundos']:.0f} s")
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

    estudio = grupos.add_parser("estudio", help="escenas del Estudio para vídeo (spec 010)")
    acciones_estudio = estudio.add_subparsers(dest="accion", required=True)
    sub = acciones_estudio.add_parser("validar", help="comprueba una escena sin capturar nada")
    sub.add_argument("escena", type=Path)
    sub.set_defaults(funcion=estudio_validar)
    sub = acciones_estudio.add_parser("capturar", help="captura una escena en MP4 (o en PNG con --foto)")
    sub.add_argument("escena", type=Path)
    sub.add_argument("--foto", type=float, action="append", metavar="SEGUNDOS", help="PNG de ese instante; se puede repetir")
    sub.add_argument("--fps", type=int, default=30, choices=(24, 25, 30, 50, 60))
    sub.add_argument("--aspecto", choices=("16:9", "9:16"), help="cambia el de la escena")
    sub.add_argument("--salida", type=Path, help="archivo .mp4 o carpeta (por defecto, junto a la escena)")
    sub.set_defaults(funcion=estudio_capturar)

    args = parser.parse_args(argv)
    if args.grupo == "estudio":
        return args.funcion(args)
    args.simbolos = [s.upper() for s in args.simbolos]
    desconocidos = set(args.simbolos) - set(INSTRUMENTOS)
    if desconocidos:
        parser.error(f"símbolos desconocidos: {', '.join(sorted(desconocidos))}")
    return args.funcion(args)


if __name__ == "__main__":
    sys.exit(main())
