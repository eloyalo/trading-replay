// Widgets del Estudio (spec 011): cotización, libro de órdenes y comparación de libros. Se pintan
// en la capa de dibujo cuando la escena trae `widget` (el gráfico de velas se oculta). Como el resto
// del Estudio, todo sale de la escena y de t. Usa `est`, `texto`, `conAlfa`, `colorDe` y
// `formatoPrecio` de estudio.js, y `libroEn`, `progresoPaso` y `opacidad` de estudio_calculos.js.

const TEXTOS_WIDGET = {
  precio: "Price",
  cantidad: "Size",
  spread: "Spread",
  asks: "Asks · sellers waiting",
  bids: "Bids · buyers waiting",
  ultimo: "Last trade",
  medio: "Avg fill",
  ejecuciones: "Fills",
  compra: "Market buy",
  venta: "Market sell",
  creador: "Market maker",
  bid: "Bid",
  ask: "Ask",
  last: "Last",
  profundo: "Deep book",
  fino: "Thin book",
};

const dolar = (p) => `$${formatoPrecio(p)}`;
const entero = (n) => n.toLocaleString("en-US");

// Fuerza de los pasos `foco` de una zona en t (0 si no hay ninguno activo).
function focoEn(zona, t) {
  let fuerza = 0;
  for (const paso of est.escena.pasos) {
    if (paso.accion === "foco" && paso.zona === zona && t >= paso.t) {
      fuerza = Math.max(fuerza, suavizar(progresoPaso(paso, t)) * opacidad(paso.id, est.ocultaciones, t));
    }
  }
  return fuerza;
}

function caja(ctx, x, y, w, h, { relleno, borde, grosor = 2, radio = 10 }) {
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, radio);
  if (relleno) {
    ctx.fillStyle = relleno;
    ctx.fill();
  }
  if (borde) {
    ctx.strokeStyle = borde;
    ctx.lineWidth = grosor;
    ctx.stroke();
  }
}

// Escalera de un libro en el rectángulo dado. `estado` sale de libroEn; devuelve la posición de las
// filas para que la orden y los focos se dibujen encima.
function dibujarEscalera(ctx, estado, { x, y, w, h }, t, textos, conFocos = true) {
  const tema = est.tema;
  const e = est.escala;
  const asks = [...estado.asks].reverse(); // la mejor ask abajo, junto al spread
  const filas = asks.length + estado.bids.length;
  const alto = Math.min(84 * e, h / (filas + 2));
  const hueco = alto * 0.9;
  const total = filas * alto + hueco;
  let fila = y + (h - total) / 2 + alto * 0.6;
  const colPrecio = x + w * 0.3;
  const colBarra = x + w * 0.36;
  const anchoBarra = w * 0.62;
  const maximo = Math.max(...estado.asks.map((n) => n.original), ...estado.bids.map((n) => n.original));
  const posiciones = { asks: [], bids: [] };

  texto(ctx, textos.precio, colPrecio, fila - alto * 0.55, { alinear: "right", base: "bottom", fondo: false, color: tema.texto, tamano: 0.6, negrita: false });
  texto(ctx, textos.cantidad, colBarra, fila - alto * 0.55, { base: "bottom", fondo: false, color: tema.texto, tamano: 0.6, negrita: false });

  const dibujarFila = (nivel, color, lado) => {
    const yc = fila + alto / 2;
    const largoOriginal = (nivel.original / maximo) * anchoBarra;
    const largo = (nivel.cantidad / maximo) * anchoBarra;
    const consumido = nivel.cantidad < nivel.original;
    caja(ctx, colBarra, fila + alto * 0.14, largoOriginal, alto * 0.72, { relleno: conAlfa(color, 0.12), radio: 6 });
    if (largo > 0) caja(ctx, colBarra, fila + alto * 0.14, largo, alto * 0.72, { relleno: conAlfa(color, consumido ? 0.75 : 0.55), radio: 6 });
    texto(ctx, dolar(nivel.precio), colPrecio, yc, { alinear: "right", fondo: false, color, tamano: 0.95 });
    texto(ctx, entero(nivel.cantidad), colBarra + 14 * e, yc, { fondo: false, color: nivel.cantidad ? tema.etiqueta_texto : conAlfa(tema.texto, 0.5), tamano: 0.8 });
    posiciones[lado].push({ precio: nivel.precio, y: fila, alto });
    fila += alto;
  };

  asks.forEach((n) => dibujarFila(n, tema.venta, "asks"));
  const ySpread = fila + hueco / 2;
  const mejorAsk = estado.asks[0].precio;
  const mejorBid = estado.bids[0].precio;
  const fSpread = conFocos ? focoEn("spread", t) : 0;
  if (fSpread > 0) {
    ctx.save();
    ctx.globalAlpha = fSpread;
    caja(ctx, x, ySpread - hueco * 0.42, w, hueco * 0.84, { relleno: conAlfa(tema.dibujo, 0.18), borde: tema.dibujo, radio: 8 });
    ctx.restore();
  }
  texto(ctx, `${textos.spread}  ${dolar(mejorAsk - mejorBid)}`, x + w / 2, ySpread, {
    alinear: "center", fondo: false, color: fSpread > 0 ? tema.dibujo : conAlfa(tema.texto, 0.7), tamano: 0.7,
  });
  fila += hueco;
  estado.bids.forEach((n) => dibujarFila(n, tema.compra, "bids"));
  posiciones.colBarra = colBarra;
  posiciones.anchoBarra = anchoBarra;
  return posiciones;
}

function dibujarLibro(ctx, t) {
  const { widget } = est.escena;
  const tema = est.tema;
  const e = est.escala;
  const vertical = est.alto > est.ancho;
  const textos = { ...TEXTOS_WIDGET, ...(widget.textos ?? {}) };
  const estado = libroEn(widget, est.escena.pasos, t);
  const area = vertical
    ? { x: est.ancho * 0.06, y: est.alto * 0.06, w: est.ancho * 0.88, h: est.alto * 0.48 }
    : { x: est.ancho * 0.18, y: est.alto * 0.1, w: est.ancho * 0.4, h: est.alto * 0.86 };
  const pos = dibujarEscalera(ctx, estado, area, t, textos);
  const filaDe = (lado, precio) => pos[lado].find((f) => f.precio === precio);

  // Focos: lados del libro y creador de mercado.
  const fLados = focoEn("lados", t);
  if (fLados > 0) {
    ctx.save();
    ctx.globalAlpha = fLados;
    for (const [lado, color] of [["asks", tema.venta], ["bids", tema.compra]]) {
      const filas = pos[lado];
      const y0 = Math.min(...filas.map((f) => f.y));
      const y1 = Math.max(...filas.map((f) => f.y + f.alto));
      caja(ctx, area.x - 12 * e, y0 - 4, area.w + 24 * e, y1 - y0 + 8, { borde: color, grosor: 3 * e, radio: 12 });
      const etiqueta = textos[lado];
      if (vertical) texto(ctx, etiqueta, area.x, lado === "asks" ? y0 - 16 * e : y1 + 16 * e, { base: lado === "asks" ? "bottom" : "top", color, tamano: 0.75 });
      else texto(ctx, etiqueta, area.x + area.w + 40 * e, (y0 + y1) / 2, { color, tamano: 0.8 });
    }
    ctx.restore();
  }
  const fCreador = focoEn("creador", t);
  if (fCreador > 0) {
    ctx.save();
    ctx.globalAlpha = fCreador;
    const a = filaDe("asks", widget.asks[0][0]);
    const b = filaDe("bids", widget.bids[0][0]);
    for (const f of [a, b]) caja(ctx, area.x - 12 * e, f.y, area.w + 24 * e, f.alto, { borde: tema.dibujo, grosor: 4 * e, radio: 10 });
    const lineas = [textos.creador, `Buys at ${dolar(widget.bids[0][0])}`, `Sells at ${dolar(widget.asks[0][0])}`];
    const xT = vertical ? area.x : area.x + area.w + 60 * e;
    let yT = vertical ? area.y + area.h + 60 * e : (a.y + b.y + b.alto) / 2 - 70 * e;
    lineas.forEach((l, i) => {
      yT += texto(ctx, l, xT, yT, { base: "top", color: i ? tema.etiqueta_texto : tema.dibujo, tamano: i ? 0.85 : 1 }).alto + 20 * e;
    });
    ctx.restore();
  }

  // Orden a mercado: flecha hacia el nivel en curso, ejecuciones, último y medio.
  const orden = estado.orden;
  if (!orden) return;
  const alfa = opacidad(orden.paso.id, est.ocultaciones, t);
  if (alfa <= 0) return;
  ctx.save();
  ctx.globalAlpha = alfa;
  const compra = orden.paso.lado === "compra";
  const ladoLibro = compra ? "asks" : "bids";
  const color = compra ? tema.compra : tema.venta;
  const actual = orden.ejecuciones[orden.ejecuciones.length - 1];
  const filaActual = actual ? filaDe(ladoLibro, actual[0]) : pos[ladoLibro][compra ? pos.asks.length - 1 : 0];
  if (orden.progreso < 1 && filaActual) {
    caja(ctx, area.x - 12 * e, filaActual.y, area.w + 24 * e, filaActual.alto, { borde: tema.dibujo, grosor: 4 * e, radio: 10 });
  }
  if (filaActual && !vertical) {
    const yF = filaActual.y + filaActual.alto / 2;
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.lineWidth = 5 * e;
    const xFlecha = Math.max(30 * e, area.x - 300 * e);
    flecha(ctx, xFlecha, yF, area.x - 30 * e, yF, 5 * e);
    texto(ctx, `${compra ? textos.compra : textos.venta}`, xFlecha, yF - 30 * e, { alinear: "left", base: "bottom", color, tamano: 0.7 });
    texto(ctx, `${entero(orden.paso.total ?? orden.paso.cantidad)} shares`, xFlecha, yF + 30 * e, { alinear: "left", base: "top", color: tema.texto, tamano: 0.65, fondo: false });
  }
  let xP = vertical ? area.x : area.x + area.w + 80 * e;
  let yP = vertical ? area.y + area.h + 50 * e : area.y + 40 * e;
  if (vertical) {
    texto(ctx, `${compra ? textos.compra : textos.venta} · ${entero(orden.paso.total ?? orden.paso.cantidad)} shares`, xP, yP, { base: "top", color, tamano: 0.85 });
    yP += 80 * e;
  }
  texto(ctx, textos.ejecuciones, xP, yP, { base: "top", fondo: false, color: tema.texto, tamano: 0.7, negrita: false });
  yP += 56 * e;
  for (const [precio, q] of orden.ejecuciones) {
    texto(ctx, `${entero(q)} @ ${dolar(precio)}`, xP, yP, { base: "top", color: tema.etiqueta_texto, tamano: 0.9 });
    yP += 66 * e;
  }
  if (orden.ultimo !== null) {
    yP += 24 * e;
    texto(ctx, `${textos.ultimo}  ${dolar(orden.ultimo)}`, xP, yP, { base: "top", color: tema.dibujo, tamano: 1.1 });
    if (orden.progreso >= 1 && orden.medio !== null && (orden.paso.ultimo_del_grupo ?? true)) {
      yP += 84 * e;
      texto(ctx, `${textos.medio}  ${dolar(orden.medio)}`, xP, yP, { base: "top", color: tema.etiqueta_texto, tamano: 0.9 });
    }
  }
  ctx.restore();
}

function dibujarCotizacion(ctx, t) {
  const { widget } = est.escena;
  const tema = est.tema;
  const e = est.escala;
  const textos = { ...TEXTOS_WIDGET, ...(widget.textos ?? {}) };
  const vertical = est.alto > est.ancho;
  const campos = [["bid", tema.compra], ["ask", tema.venta], ["last", tema.etiqueta_texto]];
  const focos = campos.map(([c]) => focoEn(c, t));
  const algunFoco = Math.max(...focos);
  const ancho = vertical ? est.ancho * 0.7 : est.ancho * 0.24;
  const alto = vertical ? est.alto * 0.18 : est.alto * 0.34;
  const sep = vertical ? est.alto * 0.04 : est.ancho * 0.04;
  const totalX = vertical ? ancho : 3 * ancho + 2 * sep;
  const totalY = vertical ? 3 * alto + 2 * sep : alto;
  const x0 = (est.ancho - totalX) / 2;
  const y0 = (est.alto - totalY) / 2;
  campos.forEach(([campo, color], i) => {
    const x = vertical ? x0 : x0 + i * (ancho + sep);
    const y = vertical ? y0 + i * (alto + sep) : y0;
    const f = focos[i];
    ctx.save();
    ctx.globalAlpha = lerp(1, 0.45, algunFoco - f);
    caja(ctx, x, y, ancho, alto, { relleno: conAlfa(color, 0.1), borde: f > 0 ? tema.dibujo : conAlfa(color, 0.5), grosor: lerp(2, 6, f) * e, radio: 18 * e });
    texto(ctx, textos[campo], x + ancho / 2, y + alto * 0.3, { alinear: "center", fondo: false, color, tamano: 0.9 });
    texto(ctx, dolar(widget[campo]), x + ancho / 2, y + alto * 0.62, { alinear: "center", fondo: false, color: tema.etiqueta_texto, tamano: 1.9 });
    ctx.restore();
  });
}

function dibujarComparacion(ctx, t) {
  const { widget } = est.escena;
  const e = est.escala;
  const textos = { ...TEXTOS_WIDGET, ...(widget.textos ?? {}) };
  const vertical = est.alto > est.ancho;
  [["izquierda", textos.profundo], ["derecha", textos.fino]].forEach(([lado, defecto], i) => {
    const libro = widget[lado];
    const area = vertical
      ? { x: est.ancho * 0.08, y: est.alto * (0.08 + i * 0.46), w: est.ancho * 0.84, h: est.alto * 0.4 }
      : { x: est.ancho * (0.06 + i * 0.48), y: est.alto * 0.14, w: est.ancho * 0.4, h: est.alto * 0.82 };
    texto(ctx, libro.titulo ?? defecto, area.x + area.w / 2, area.y - 10 * e, { alinear: "center", base: "bottom", color: est.tema.dibujo, tamano: 1 });
    const estado = libroEn(libro, [], t);
    dibujarEscalera(ctx, estado, area, t, textos);
  });
}

function dibujarWidget(t) {
  const ctx = capa.getContext("2d");
  ctx.fillStyle = est.tema.fondo;
  ctx.fillRect(0, 0, capa.width, capa.height);
  const { widget, lienzo: lz } = est.escena;
  if (widget.tipo === "libro") dibujarLibro(ctx, t);
  else if (widget.tipo === "cotizacion") dibujarCotizacion(ctx, t);
  else dibujarComparacion(ctx, t);
  let y = 24 * est.escala;
  const titulo = lz.titulo ?? (widget.tipo === "libro" ? `${widget.simbolo ?? "XYZ"} · Order book` : null);
  if (titulo) y += texto(ctx, titulo, 24 * est.escala, y, { base: "top", fondo: false, color: est.tema.texto, tamano: 1.1 }).alto + 12;
  if (lz.ilustrativo) texto(ctx, lz.texto_ilustrativo ?? "Illustrative example", 24 * est.escala, y, { base: "top", color: est.tema.dibujo, tamano: 0.7, negrita: false });
}
