// Cálculos puros del Estudio (spec 010), sin DOM: progreso de los pasos, suavizado, velas que se
// ven en cada instante, vela en formación y cámara. Todo depende solo de `t` (RF-7): el mismo `t`
// da siempre el mismo resultado, en cualquier orden. Se carga en el navegador y en Node (tests).

// Progreso de un paso en el instante t, de 0 a 1. Sin duración, salta de 0 a 1 en paso.t.
function progresoPaso(paso, t) {
  if (t < paso.t) return 0;
  if (!paso.duracion) return 1;
  return Math.min(1, (t - paso.t) / paso.duracion);
}

const suavizar = (p) => (p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2);
const salida = (p) => 1 - Math.pow(1 - p, 3);
const lerp = (a, b, p) => a + (b - a) * p;

// Posición lógica (índice de vela, con decimales) de un tiempo. Entre dos velas se interpola; a la
// derecha de la última y a la izquierda de la primera se extrapola con la duración de la vela.
function logico(velas, t, paso) {
  const n = velas.length;
  if (!n) return 0;
  if (t >= velas[n - 1].time) return n - 1 + (t - velas[n - 1].time) / paso;
  if (t <= velas[0].time) return (t - velas[0].time) / paso;
  let bajo = 0;
  let alto = n - 1;
  while (alto - bajo > 1) {
    const medio = (bajo + alto) >> 1;
    if (velas[medio].time <= t) bajo = medio;
    else alto = medio;
  }
  return bajo + (t - velas[bajo].time) / (velas[alto].time - velas[bajo].time);
}

// Índice de la última vela que empieza en `t` o antes (-1 si ninguna).
function indiceHasta(velas, t) {
  let r = -1;
  for (let i = 0; i < velas.length && velas[i].time <= t; i++) r = i;
  return r;
}

// La vela a medio formar con progreso p: apertura → extremo más cercano → el otro → cierre.
function velaEnFormacion(vela, p) {
  const { open: o, high: h, low: l, close: c } = vela;
  if (p <= 0) return { ...vela, high: o, low: o, close: o };
  if (p >= 1) return { ...vela };
  const primeroBajo = o - l <= h - o;
  const ruta = primeroBajo ? [o, l, h, c] : [o, h, l, c];
  const tramos = [Math.abs(ruta[1] - ruta[0]), Math.abs(ruta[2] - ruta[1]), Math.abs(ruta[3] - ruta[2])];
  const total = tramos[0] + tramos[1] + tramos[2] || 1;
  let resto = p * total;
  let precio = o;
  let alto = o;
  let bajo = o;
  for (let i = 0; i < 3; i++) {
    const avance = Math.min(resto, tramos[i]);
    precio = ruta[i] + Math.sign(ruta[i + 1] - ruta[i]) * avance;
    alto = Math.max(alto, precio, i > 0 ? ruta[i] : o);
    bajo = Math.min(bajo, precio, i > 0 ? ruta[i] : o);
    resto -= avance;
    if (resto <= 0) break;
  }
  return { ...vela, high: alto, low: bajo, close: precio };
}

// Velas que se ven en t según los pasos `revelar`: {completas, parcial}. Sin pasos `revelar`, todas.
// Antes del primero se ve hasta su `desde` (o la primera vela). Cada `revelar` avanza de lo que
// había hasta `hasta` (incluida) a ritmo constante; con `formar` (por defecto), cada vela crece.
function velasVisibles(velas, pasos, t) {
  const revelar = pasos.filter((p) => p.accion === "revelar");
  if (!revelar.length) return { completas: velas.length, parcial: null };
  let cuenta = revelar[0].desde != null ? indiceHasta(velas, revelar[0].desde) + 1 : 1;
  for (const paso of revelar) {
    if (t < paso.t) break;
    const destino = indiceHasta(velas, paso.hasta) + 1;
    const p = progresoPaso(paso, t);
    if (p >= 1 || destino <= cuenta) {
      cuenta = Math.max(cuenta, destino);
      continue;
    }
    const exacto = cuenta + (destino - cuenta) * p;
    const completas = Math.floor(exacto);
    const fraccion = exacto - completas;
    if (paso.formar === false || fraccion === 0) return { completas, parcial: null };
    return { completas, parcial: velaEnFormacion(velas[completas], fraccion) };
  }
  return { completas: Math.min(cuenta, velas.length), parcial: null };
}

// Rango de precio de las velas entre dos posiciones lógicas, más los precios extra, con margen.
function rangoPrecio(velas, desde, hasta, extra = [], margen = 0.08) {
  let bajo = Infinity;
  let alto = -Infinity;
  const i0 = Math.max(0, Math.ceil(desde));
  const i1 = Math.min(velas.length - 1, Math.floor(hasta));
  for (let i = i0; i <= i1; i++) {
    bajo = Math.min(bajo, velas[i].low);
    alto = Math.max(alto, velas[i].high);
  }
  for (const p of extra) {
    bajo = Math.min(bajo, p);
    alto = Math.max(alto, p);
  }
  if (!Number.isFinite(bajo)) return null;
  const hueco = (alto - bajo || alto * 0.01 || 1) * margen;
  return { from: bajo - hueco, to: alto + hueco };
}

// Vista en el instante t: {logico: {from, to}, precio: {from, to} | null}. `base` es la vista
// inicial; cada paso `camara` lleva de la vista anterior a la suya con suavizado.
function vistaEn(base, camaras, t) {
  let vista = base;
  for (const camara of camaras) {
    if (t < camara.t) break;
    const p = suavizar(progresoPaso(camara, t));
    const mezcla = (a, b) => (a && b ? { from: lerp(a.from, b.from, p), to: lerp(a.to, b.to, p) } : b ?? a);
    vista = { logico: mezcla(vista.logico, camara.vista.logico), precio: mezcla(vista.precio, camara.vista.precio) };
  }
  return vista;
}

// Opacidad de un elemento con id en el instante t, según los pasos `ocultar` que lo nombran.
function opacidad(id, ocultaciones, t) {
  let alfa = 1;
  if (id == null) return alfa;
  for (const paso of ocultaciones) {
    if (paso.objetivos.includes(id) && t >= paso.t) alfa = Math.min(alfa, 1 - progresoPaso(paso, t));
  }
  return alfa;
}

// Trazo de pincel hasta el progreso p. Cada punto es [t, precio, fracción del trazo 0..1].
function trazoHasta(puntos, p) {
  const salidaPuntos = [];
  for (let i = 0; i < puntos.length; i++) {
    if (puntos[i][2] <= p) {
      salidaPuntos.push(puntos[i]);
      continue;
    }
    if (i > 0) {
      const a = puntos[i - 1];
      const b = puntos[i];
      const f = (p - a[2]) / (b[2] - a[2] || 1);
      salidaPuntos.push([lerp(a[0], b[0], f), lerp(a[1], b[1], f), p]);
    }
    break;
  }
  return salidaPuntos;
}

// --- Widgets (spec 011) ---
// Un libro es {asks: [[precio, cantidad], ...], bids: [...]} con el mejor precio primero.

// Ejecuta `cantidad` a mercado: una compra consume asks y una venta bids, del mejor precio hacia fuera.
// Devuelve las ejecuciones [[precio, cantidad]], el libro que queda, el último precio y el medio.
function ejecutar(libro, lado, cantidad) {
  const clave = lado === "compra" ? "asks" : "bids";
  const niveles = libro[clave].map(([precio, q]) => [precio, q]);
  const ejecuciones = [];
  let resto = cantidad;
  for (const nivel of niveles) {
    if (resto <= 0) break;
    const toma = Math.min(resto, nivel[1]);
    if (toma > 0) {
      ejecuciones.push([nivel[0], toma]);
      nivel[1] -= toma;
      resto -= toma;
    }
  }
  const total = ejecuciones.reduce((s, [, q]) => s + q, 0);
  const importe = ejecuciones.reduce((s, [p, q]) => s + p * q, 0);
  return {
    ejecuciones,
    libro: { ...libro, [clave]: niveles },
    ultimo: ejecuciones.length ? ejecuciones[ejecuciones.length - 1][0] : null,
    medio: total ? importe / total : null,
  };
}

// Estado del libro en el instante t según los pasos `orden` (cada una parte del libro que dejó la
// anterior; la que está en curso, en proporción a su progreso). Cada nivel lleva su cantidad
// original para que la escalera no cambie de forma al vaciarse.
function libroEn(widget, pasos, t) {
  let libro = { asks: widget.asks, bids: widget.bids };
  let ultimaOrden = null;
  for (const paso of pasos) {
    if (paso.accion !== "orden" || t < paso.t) continue;
    const p = progresoPaso(paso, t);
    const cantidad = Math.round(paso.cantidad * p);
    const r = ejecutar(libro, paso.lado, cantidad);
    // Los tramos de una misma orden (mismo `grupo`, p. ej. uno por nivel para seguir a la voz)
    // se muestran como una sola: ejecuciones acumuladas y precio medio de todo.
    const previas = ultimaOrden && paso.grupo != null && ultimaOrden.paso.grupo === paso.grupo ? ultimaOrden.ejecuciones : [];
    const ejecuciones = [...previas];
    for (const [precio, q] of r.ejecuciones) {
      const igual = ejecuciones.find((x) => x[0] === precio);
      if (igual) igual[1] += q;
      else ejecuciones.push([precio, q]);
    }
    const total = ejecuciones.reduce((s, [, q]) => s + q, 0);
    const medio = total ? ejecuciones.reduce((s, [pr, q]) => s + pr * q, 0) / total : null;
    ultimaOrden = { paso, progreso: p, libro: r.libro, ultimo: r.ultimo ?? ultimaOrden?.ultimo ?? null, ejecuciones, medio };
    libro = r.libro;
  }
  const conOriginal = (clave) =>
    libro[clave].map(([precio, q], i) => ({ precio, cantidad: q, original: widget[clave][i][1] }));
  return { asks: conOriginal("asks"), bids: conOriginal("bids"), orden: ultimaOrden };
}

if (typeof module !== "undefined") {
  module.exports = {
    progresoPaso,
    suavizar,
    salida,
    lerp,
    logico,
    indiceHasta,
    velaEnFormacion,
    velasVisibles,
    rangoPrecio,
    vistaEn,
    opacidad,
    trazoHasta,
    ejecutar,
    libroEn,
  };
}
