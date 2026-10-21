"""Escenas del Estudio (spec 010): validación (RF-6) y resolución de datos (RF-2 a RF-4b).

`preparar(escena)` devuelve la escena lista para pintar: velas resueltas, todos los tiempos en
segundos "ET como UTC" (como `time` de las velas), pasos ordenados y duración calculada. Si algo
falla, lanza `EscenaNoValida` con un mensaje por problema que nombra el paso.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

from trading_replay.config import INSTRUMENTOS
from trading_replay.estudio import acciones
from trading_replay.historico import almacen

FORMATO = 1
ASPECTOS = {"16:9", "9:16"}
TF_SEGUNDOS = {tf: m * 60 for tf, m in almacen.TIMEFRAMES.items()}
INICIO_MANUAL = date(2001, 1, 1)  # lunes: las velas escritas a mano empiezan aquí, un día por vela
MAX_VELAS = 5000
MAX_FUTURO = 200  # velas que se pueden dibujar a la derecha de la última

INDICADORES = {"ema", "sma", "vwap", "volumen", "rsi", "atr"}
# Campos obligatorios de cada acción (además de `t`).
ACCIONES = {
    "revelar": ("hasta",),
    "horizontal": ("precio",),
    "tendencia": ("puntos",),
    "rectangulo": ("puntos",),
    "zona": ("precios", "desde"),
    "flecha": ("puntos",),
    "marca": ("punto",),
    "etiqueta": ("punto", "texto"),
    "pincel": ("puntos",),
    "resaltar": ("velas",),
    "ohlc": ("vela",),
    "indicador": ("tipo",),
    "camara": ("desde", "hasta"),
    "operacion": ("lado", "entrada", "stop", "objetivo"),
    "ocultar": ("objetivos",),
}
CAMPOS_TIEMPO = ("desde", "hasta", "vela")  # un tiempo
CAMPOS_PUNTO = ("punto", "entrada")  # [tiempo, precio]


class EscenaNoValida(ValueError):
    def __init__(self, errores: list[str]):
        super().__init__("; ".join(errores))
        self.errores = errores


def _segundos(texto: str) -> int:
    """'2024-03-08 09:30' o '2024-03-08' (hora ET) → segundos "ET como UTC"."""
    momento = datetime.fromisoformat(texto.strip().replace("T", " "))
    return int(momento.replace(tzinfo=timezone.utc).timestamp())


def _a_datetime(segundos: int) -> datetime:
    return datetime.fromtimestamp(segundos, timezone.utc).replace(tzinfo=None)


def _numero(valor) -> bool:
    return isinstance(valor, (int, float)) and not isinstance(valor, bool) and math.isfinite(valor)


# --- Datos ---

def _velas_manuales(filas: list, errores: list[str], con_tiempo: bool) -> list[dict]:
    velas = []
    dia = INICIO_MANUAL
    for i, fila in enumerate(filas):
        donde = f"datos.velas[{i}]"
        if con_tiempo:
            if not isinstance(fila, list) or len(fila) not in (5, 6) or not isinstance(fila[0], str):
                errores.append(f"{donde}: debe ser [tiempo, apertura, máximo, mínimo, cierre, volumen?]")
                continue
            try:
                t = _segundos(fila[0])
            except ValueError:
                errores.append(f"{donde}: tiempo no válido {fila[0]!r}")
                continue
            valores = fila[1:]
        else:
            if not isinstance(fila, list) or len(fila) not in (4, 5):
                errores.append(f"{donde}: debe ser [apertura, máximo, mínimo, cierre, volumen?]")
                continue
            while dia.weekday() >= 5:
                dia += timedelta(days=1)
            t = _segundos(dia.isoformat())
            dia += timedelta(days=1)
            valores = fila
        if not all(_numero(v) for v in valores):
            errores.append(f"{donde}: los valores tienen que ser números")
            continue
        o, h, l, c = valores[:4]
        if h < max(o, c) or l > min(o, c) or l <= 0:
            errores.append(f"{donde}: vela imposible (máximo {h}, mínimo {l}, apertura {o}, cierre {c})")
            continue
        velas.append({"time": t, "open": o, "high": h, "low": l, "close": c,
                      "volume": valores[4] if len(valores) == 5 else 0})
    velas.sort(key=lambda v: v["time"])
    return velas


def _resolver_datos(datos: dict, errores: list[str]) -> tuple[str, str, list[dict], bool]:
    """(símbolo, timeframe, velas, ilustrativo)."""
    tipo = datos.get("tipo")
    if tipo == "manual":
        filas = datos.get("velas")
        if not isinstance(filas, list) or not filas:
            errores.append("datos.velas: hace falta una lista de velas")
            return "XYZ", "1D", [], True
        return str(datos.get("simbolo", "XYZ")), "1D", _velas_manuales(filas, errores, False), True

    tf = datos.get("tf", "1D")
    if tf not in TF_SEGUNDOS:
        errores.append(f"datos.tf: timeframe no válido {tf!r} (válidos: {', '.join(TF_SEGUNDOS)})")
        return "", "1D", [], False

    if tipo == "aportadas":
        filas = datos.get("velas")
        if not isinstance(filas, list) or not filas:
            errores.append("datos.velas: hace falta una lista de velas")
            return "", tf, [], False
        return str(datos.get("simbolo", "")), tf, _velas_manuales(filas, errores, True), False

    if tipo != "real":
        errores.append(f"datos.tipo: {tipo!r} no válido (real, manual o aportadas)")
        return "", tf, [], False
    simbolo = str(datos.get("instrumento", "")).upper()
    try:
        desde = datetime.fromisoformat(str(datos["desde"]).replace("T", " "))
        hasta = datetime.fromisoformat(str(datos["hasta"]).replace("T", " "))
    except (KeyError, ValueError):
        errores.append("datos.desde y datos.hasta: hacen falta, con formato 'AAAA-MM-DD HH:MM' (hora ET)")
        return simbolo, tf, [], False
    if hasta <= desde:
        errores.append("datos.hasta tiene que ser posterior a datos.desde")
        return simbolo, tf, [], False

    if simbolo in INSTRUMENTOS:
        disponible = almacen.rango(simbolo)
        if not disponible:
            errores.append(f"datos.instrumento: no hay histórico de {simbolo}; descárgalo con `trading-replay datos descargar`")
            return simbolo, tf, [], False
        velas = almacen.consultar(simbolo, tf, desde, hasta)  # sin el recorte del replay (RF-2)
    else:
        try:
            velas = acciones.consultar(simbolo, tf, desde, hasta)
        except acciones.SimboloNoValido as error:
            errores.append(f"datos.instrumento: {error}")
            return simbolo, tf, [], False
        except (ValueError, RuntimeError) as error:
            errores.append(f"datos: {error}")
            return simbolo, tf, [], False
    if not velas:
        errores.append(f"datos: no hay velas de {simbolo} {tf} entre {desde} y {hasta}")
    return simbolo, tf, velas, False


# --- Tiempos y precios de los pasos ---

class _Convertidor:
    def __init__(self, velas: list[dict], tf: str):
        self.velas = velas
        self.paso = TF_SEGUNDOS[tf]

    def tiempo(self, valor, donde: str, errores: list[str]) -> int | None:
        """Texto ET o índice de vela → segundos. Admite hasta MAX_FUTURO velas a la derecha."""
        if not self.velas:
            return None
        ultima = len(self.velas) - 1
        if _numero(valor):
            # Índice de vela; con decimales (trazos de pincel) se interpola entre dos velas.
            if valor < 0 or valor > ultima + MAX_FUTURO:
                errores.append(f"{donde}: índice de vela {valor} fuera de 0..{ultima + MAX_FUTURO}")
                return None
            if valor >= ultima:
                return round(self.velas[ultima]["time"] + (valor - ultima) * self.paso)
            i = int(valor)
            a, b = self.velas[i]["time"], self.velas[i + 1]["time"]
            return round(a + (valor - i) * (b - a))
        if not isinstance(valor, str):
            errores.append(f"{donde}: el tiempo tiene que ser 'AAAA-MM-DD HH:MM' o un índice de vela")
            return None
        try:
            t = _segundos(valor)
        except ValueError:
            errores.append(f"{donde}: tiempo no válido {valor!r}")
            return None
        primero, fin = self.velas[0]["time"], self.velas[ultima]["time"] + MAX_FUTURO * self.paso
        if not primero - self.paso < t <= fin:
            errores.append(f"{donde}: {valor} está fuera de los datos de la escena")
            return None
        return t

    def precio(self, valor, donde: str, errores: list[str]) -> float | None:
        if not _numero(valor) or valor <= 0:
            errores.append(f"{donde}: precio no válido {valor!r}")
            return None
        if self.velas:
            bajo = min(v["low"] for v in self.velas)
            alto = max(v["high"] for v in self.velas)
            margen = (alto - bajo) or alto
            if not bajo - 2 * margen <= valor <= alto + 2 * margen:
                errores.append(f"{donde}: el precio {valor} queda muy lejos de las velas ({bajo:g}-{alto:g})")
                return None
        return float(valor)

    def punto(self, valor, donde: str, errores: list[str]) -> list | None:
        if not isinstance(valor, list) or len(valor) < 2:
            errores.append(f"{donde}: un punto es [tiempo, precio]")
            return None
        t = self.tiempo(valor[0], donde, errores)
        p = self.precio(valor[1], donde, errores)
        if t is None or p is None:
            return None
        return [t, p, *valor[2:]]


def _normalizar_paso(paso: dict, n: int, conv: _Convertidor, errores: list[str], ids: set) -> dict | None:
    accion = paso.get("accion") if isinstance(paso, dict) else None
    nombre = f"pasos[{n}]" + (f" ({paso.get('id')})" if isinstance(paso, dict) and paso.get("id") else "")
    if accion not in ACCIONES:
        errores.append(f"{nombre}: acción {accion!r} no válida (válidas: {', '.join(ACCIONES)})")
        return None
    nombre = f"{nombre} {accion}"
    antes = len(errores)
    if not _numero(paso.get("t")) or paso["t"] < 0:
        errores.append(f"{nombre}: falta `t` (segundos desde el inicio, 0 o más)")
    if "duracion" in paso and (not _numero(paso["duracion"]) or paso["duracion"] < 0):
        errores.append(f"{nombre}: `duracion` tiene que ser un número de segundos")
    for campo in ACCIONES[accion]:
        if campo not in paso:
            errores.append(f"{nombre}: falta `{campo}`")
    if paso.get("id") is not None:
        if paso["id"] in ids:
            errores.append(f"{nombre}: id repetido {paso['id']!r}")
        ids.add(paso["id"])
    if len(errores) > antes:
        return None

    salida = dict(paso)
    salida.setdefault("duracion", 0)
    for campo in CAMPOS_TIEMPO:
        if campo in paso:
            salida[campo] = conv.tiempo(paso[campo], f"{nombre}.{campo}", errores)
    for campo in CAMPOS_PUNTO:
        if campo in paso:
            salida[campo] = conv.punto(paso[campo], f"{nombre}.{campo}", errores)
    if "puntos" in paso:
        if not isinstance(paso["puntos"], list) or len(paso["puntos"]) < (1 if accion == "pincel" else 2):
            errores.append(f"{nombre}.puntos: hacen falta al menos {1 if accion == 'pincel' else 2} puntos")
        else:
            salida["puntos"] = [conv.punto(p, f"{nombre}.puntos[{i}]", errores) for i, p in enumerate(paso["puntos"])]
    for campo in ("precio", "stop", "objetivo"):
        if campo in paso:
            salida[campo] = conv.precio(paso[campo], f"{nombre}.{campo}", errores)
    if "precios" in paso:
        if not isinstance(paso["precios"], list) or len(paso["precios"]) != 2:
            errores.append(f"{nombre}.precios: son [precio bajo, precio alto]")
        else:
            salida["precios"] = sorted(conv.precio(p, f"{nombre}.precios", errores) or 0 for p in paso["precios"])
    if "velas" in paso:
        if not isinstance(paso["velas"], list) or not paso["velas"]:
            errores.append(f"{nombre}.velas: hace falta una lista de velas")
        else:
            salida["velas"] = [conv.tiempo(v, f"{nombre}.velas[{i}]", errores) for i, v in enumerate(paso["velas"])]
    if accion == "indicador" and paso["tipo"] not in INDICADORES:
        errores.append(f"{nombre}: indicador {paso['tipo']!r} no válido ({', '.join(sorted(INDICADORES))})")
    if accion == "operacion" and paso["lado"] not in ("compra", "venta"):
        errores.append(f"{nombre}: `lado` es compra o venta")
    if accion == "ocultar" and not isinstance(paso["objetivos"], list):
        salida["objetivos"] = [paso["objetivos"]]
    if accion == "pincel" and isinstance(paso.get("puntos"), list):
        # Cada punto puede llevar su instante relativo en ms (grabado con el pincel); si no, reparto uniforme.
        if any(len(p) < 3 for p in paso["puntos"] if isinstance(p, list)):
            total = len(paso["puntos"]) - 1 or 1
            salida["puntos"] = [p[:2] + [i / total] for i, p in enumerate(salida["puntos"]) if p]
        elif salida["puntos"] and all(salida["puntos"]):
            fin = max(p[2] for p in salida["puntos"]) or 1
            salida["puntos"] = [p[:2] + [p[2] / fin] for p in salida["puntos"]]
    return salida


def preparar(escena: dict) -> dict:
    """Valida la escena y la devuelve normalizada (ver el plan de la spec 010)."""
    errores: list[str] = []
    if not isinstance(escena, dict):
        raise EscenaNoValida(["la escena tiene que ser un objeto JSON"])
    if escena.get("formato") != FORMATO:
        errores.append(f"formato: tiene que ser {FORMATO}")
    lienzo = dict(escena.get("lienzo") or {})
    if lienzo.setdefault("aspecto", "16:9") not in ASPECTOS:
        errores.append(f"lienzo.aspecto: {lienzo['aspecto']!r} no válido (16:9 o 9:16)")
    if "widget" in escena:
        return _preparar_widget(escena, lienzo, errores)
    if not isinstance(escena.get("datos"), dict):
        errores.append("datos: falta")
        raise EscenaNoValida(errores)

    simbolo, tf, velas, ilustrativo = _resolver_datos(escena["datos"], errores)
    if len(velas) > MAX_VELAS:
        errores.append(f"datos: {len(velas)} velas; como mucho {MAX_VELAS} por escena")
    lienzo.setdefault("ilustrativo", ilustrativo)
    lienzo.setdefault("eje_tiempo", not ilustrativo)
    lienzo.setdefault("logo_tradingview", True)
    if errores:
        raise EscenaNoValida(errores)

    conv = _Convertidor(velas, tf)
    vista = dict(escena.get("vista") or {})
    for campo in ("desde", "hasta"):
        if campo in vista:
            vista[campo] = conv.tiempo(vista[campo], f"vista.{campo}", errores)
    if "precio" in vista:
        if not isinstance(vista["precio"], list) or len(vista["precio"]) != 2:
            errores.append("vista.precio: es [precio bajo, precio alto]")
        else:
            vista["precio"] = sorted(conv.precio(p, "vista.precio", errores) or 0 for p in vista["precio"])

    indicadores = []
    for i, ind in enumerate(escena.get("indicadores") or []):
        if not isinstance(ind, dict) or ind.get("tipo") not in INDICADORES:
            errores.append(f"indicadores[{i}]: tipo no válido ({', '.join(sorted(INDICADORES))})")
        else:
            indicadores.append(ind)

    ids: set = set()
    pasos = [_normalizar_paso(p, n, conv, errores, ids) for n, p in enumerate(escena.get("pasos") or [])]
    pasos = [p for p in pasos if p]
    for p in pasos:
        if p["accion"] == "ocultar":
            for objetivo in p["objetivos"]:
                if objetivo not in ids:
                    errores.append(f"paso ocultar en t={p['t']}: no hay ningún paso con id {objetivo!r}")
    fin = max((p["t"] + p["duracion"] for p in pasos), default=0)
    duracion = escena.get("duracion")
    if duracion is not None:
        if not _numero(duracion) or duracion <= 0:
            errores.append("duracion: tiene que ser un número de segundos")
        else:
            for p in pasos:
                if p["t"] + p["duracion"] > duracion:
                    errores.append(f"paso {p.get('id') or p['accion']} en t={p['t']}: termina después del final de la escena ({duracion} s)")
    if errores:
        raise EscenaNoValida(errores)

    pasos.sort(key=lambda p: p["t"])
    return {
        "formato": FORMATO,
        "simbolo": simbolo,
        "tf": tf,
        "tf_segundos": TF_SEGUNDOS[tf],
        "lienzo": lienzo,
        "vista": vista,
        "indicadores": indicadores,
        "pasos": pasos,
        "velas": velas,
        "duracion": float(duracion if duracion is not None else fin + 1),
    }


# --- Widgets (spec 011): cotización, libro de órdenes y comparación de libros ---

TIPOS_WIDGET = {"cotizacion", "libro", "comparar_libros"}
ACCIONES_WIDGET = {"orden": ("lado", "cantidad"), "foco": ("zona",), "ocultar": ("objetivos",)}
ZONAS = {"cotizacion": {"bid", "ask", "last"}, "libro": {"lados", "spread", "creador"}, "comparar_libros": {"lados", "spread"}}


def _niveles(libro: dict, donde: str, errores: list[str]) -> dict | None:
    salida = {}
    for lado in ("asks", "bids"):
        filas = libro.get(lado)
        if not isinstance(filas, list) or not filas:
            errores.append(f"{donde}.{lado}: hace falta una lista de [precio, cantidad]")
            return None
        limpias = []
        for i, fila in enumerate(filas):
            if (not isinstance(fila, list) or len(fila) != 2 or not _numero(fila[0]) or fila[0] <= 0
                    or not isinstance(fila[1], int) or isinstance(fila[1], bool) or fila[1] <= 0):
                errores.append(f"{donde}.{lado}[{i}]: debe ser [precio > 0, cantidad entera > 0]")
                return None
            limpias.append([float(fila[0]), fila[1]])
        salida[lado] = sorted(limpias, key=lambda f: f[0], reverse=(lado == "bids"))  # el mejor precio primero
    if salida["asks"][0][0] <= salida["bids"][0][0]:
        errores.append(f"{donde}: la mejor ask ({salida['asks'][0][0]}) tiene que estar por encima de la mejor bid ({salida['bids'][0][0]})")
        return None
    return {**libro, **salida}


def _preparar_widget(escena: dict, lienzo: dict, errores: list[str]) -> dict:
    w = dict(escena["widget"]) if isinstance(escena["widget"], dict) else {}
    tipo = w.get("tipo")
    if tipo not in TIPOS_WIDGET:
        raise EscenaNoValida(errores + [f"widget.tipo: {tipo!r} no válido ({', '.join(sorted(TIPOS_WIDGET))})"])
    if tipo == "cotizacion":
        for campo in ("bid", "ask", "last"):
            if not _numero(w.get(campo)) or w[campo] <= 0:
                errores.append(f"widget.{campo}: precio no válido {w.get(campo)!r}")
    elif tipo == "libro":
        w = _niveles(w, "widget", errores) or w
    else:
        for lado in ("izquierda", "derecha"):
            if not isinstance(w.get(lado), dict):
                errores.append(f"widget.{lado}: falta el libro")
            else:
                w[lado] = _niveles(w[lado], f"widget.{lado}", errores) or w[lado]

    ids: set = set()
    pasos = []
    # Lo que queda en cada lado del libro, para comprobar que cada orden cabe (las órdenes se encadenan).
    queda = {"asks": sum(q for _, q in w.get("asks", [])), "bids": sum(q for _, q in w.get("bids", []))} if tipo == "libro" else None
    for n, paso in enumerate(escena.get("pasos") or []):
        accion = paso.get("accion") if isinstance(paso, dict) else None
        nombre = f"pasos[{n}]" + (f" ({paso.get('id')})" if isinstance(paso, dict) and paso.get("id") else "") + f" {accion}"
        if accion not in ACCIONES_WIDGET:
            errores.append(f"{nombre}: acción no válida en un widget ({', '.join(ACCIONES_WIDGET)})")
            continue
        if not _numero(paso.get("t")) or paso["t"] < 0:
            errores.append(f"{nombre}: falta `t` (segundos desde el inicio, 0 o más)")
        faltan = [c for c in ACCIONES_WIDGET[accion] if c not in paso]
        if faltan:
            errores.append(f"{nombre}: falta `{faltan[0]}`")
            continue
        if paso.get("id") is not None:
            if paso["id"] in ids:
                errores.append(f"{nombre}: id repetido {paso['id']!r}")
            ids.add(paso["id"])
        salida = {**paso, "duracion": paso.get("duracion", 0)}
        if accion == "orden":
            if tipo != "libro":
                errores.append(f"{nombre}: las órdenes solo van en un widget `libro`")
            elif paso["lado"] not in ("compra", "venta"):
                errores.append(f"{nombre}: `lado` es compra o venta")
            elif not isinstance(paso["cantidad"], int) or paso["cantidad"] <= 0:
                errores.append(f"{nombre}: `cantidad` tiene que ser un entero positivo")
            else:
                lado = "asks" if paso["lado"] == "compra" else "bids"
                if paso["cantidad"] > queda[lado]:
                    errores.append(f"{nombre}: pide {paso['cantidad']} y en el libro solo hay {queda[lado]} en las {lado}")
                else:
                    queda[lado] -= paso["cantidad"]
        if accion == "foco" and paso["zona"] not in ZONAS[tipo]:
            errores.append(f"{nombre}: zona {paso['zona']!r} no válida en `{tipo}` ({', '.join(sorted(ZONAS[tipo]))})")
        if accion == "ocultar" and not isinstance(paso["objetivos"], list):
            salida["objetivos"] = [paso["objetivos"]]
        pasos.append(salida)
    for p in pasos:
        if p["accion"] == "ocultar":
            for objetivo in p["objetivos"]:
                if objetivo not in ids:
                    errores.append(f"paso ocultar en t={p['t']}: no hay ningún paso con id {objetivo!r}")
    if errores:
        raise EscenaNoValida(errores)
    lienzo.setdefault("ilustrativo", bool(w.get("ilustrativo", True)))
    lienzo.setdefault("logo_tradingview", False)
    pasos.sort(key=lambda p: p["t"])
    fin = max((p["t"] + p["duracion"] for p in pasos), default=0)
    duracion = escena.get("duracion")
    return {
        "formato": FORMATO, "simbolo": w.get("simbolo", "XYZ"), "tf": "1D", "tf_segundos": 86400,
        "lienzo": lienzo, "vista": {}, "indicadores": [], "pasos": pasos, "velas": [], "widget": w,
        "duracion": float(duracion if _numero(duracion) and duracion > 0 else fin + 1),
    }
