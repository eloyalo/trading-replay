// Estudio (spec 010): reproduce una escena descrita en JSON con un reloj determinista. Todo lo que
// se ve en el instante t sale de la escena y de t (RF-7): `estudio.ir(t)` deja el lienzo igual
// llegue desde donde llegue. Las velas y los indicadores los pinta Lightweight Charts; los pasos
// (líneas, zonas, flechas, pincel...) se pintan en un <canvas> encima, a partir de las coordenadas
// del gráfico. La interfaz (barra, pincel) es del modo manual y no sale en las capturas.

const { createChart, CandlestickSeries, LineSeries, HistogramSeries } = LightweightCharts;

const TAMANOS = { "16:9": [1920, 1080], "9:16": [1080, 1920] };
// Tema por defecto (decidido por Claude): oscuro y neutro. La escena puede cambiar cualquier clave.
const TEMA_BASE = {
  fondo: "#0f1420",
  texto: "#c9d1e0",
  rejilla: "rgba(255, 255, 255, 0.05)",
  alcista: "#26a69a",
  bajista: "#ef5350",
  dibujo: "#f5b942",
  secundario: "#6ea8fe",
  pincel: "#f5b942",
  compra: "#26a69a",
  venta: "#ef5350",
  etiqueta_fondo: "rgba(10, 14, 24, 0.88)",
  etiqueta_texto: "#ffffff",
  fuente: "system-ui, 'Segoe UI', Roboto, sans-serif",
  grosor: 4,
  tamano_texto: 34,
  tamano_eje: 22,
};
const ESCALA_VERTICAL = 1.35; // textos más grandes en 9:16 (RF-9)
const COLORES_INDICADOR = ["#f5b942", "#6ea8fe", "#e879f9", "#ffffff"];
const MESES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DIBUJABLES = new Set(["horizontal", "tendencia", "rectangulo", "zona", "flecha", "marca", "etiqueta", "pincel", "ohlc", "operacion"]);

const parametros = new URLSearchParams(location.search);
const modoCaptura = parametros.has("captura");
if (modoCaptura) document.body.classList.add("captura");

const $ = (id) => document.getElementById(id);
const lienzo = $("lienzo");
const capa = $("capa");

const est = {
  original: null, // la escena tal cual se cargó (y con los trazos grabados): es lo que se exporta
  escena: null, // la escena preparada por el backend
  tema: TEMA_BASE,
  escala: 1,
  ancho: 1920,
  alto: 1080,
  grafico: null,
  serie: null,
  volumen: null,
  lineas: [], // [{def, serie, desde}] indicadores
  t: 0,
  claveVelas: "",
  reproduciendo: false,
  trazo: null, // trazo de pincel en curso
};

// --- Utilidades ---

const siguienteCuadro = () => new Promise((r) => requestAnimationFrame(() => r()));

function conAlfa(colorTexto, alfa) {
  if (colorTexto.startsWith("#")) {
    const h = colorTexto.length === 4 ? colorTexto.replace(/#(.)(.)(.)/, "#$1$1$2$2$3$3") : colorTexto;
    const n = parseInt(h.slice(1, 7), 16);
    return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alfa})`;
  }
  const m = colorTexto.match(/rgba?\(([^)]+)\)/);
  if (!m) return colorTexto;
  const [r, g, b, a = 1] = m[1].split(",").map((x) => parseFloat(x));
  return `rgba(${r}, ${g}, ${b}, ${a * alfa})`;
}

const colorDe = (nombre, defecto = "dibujo") => est.tema[nombre ?? defecto] ?? nombre ?? est.tema[defecto];

function formatoPrecio(valor, decimales = 2) {
  return valor.toLocaleString("en-US", { minimumFractionDigits: decimales, maximumFractionDigits: decimales });
}

function fechaIngles(time, conHora) {
  const d = new Date(time * 1000);
  const fecha = `${MESES[d.getUTCMonth()]} ${d.getUTCDate()}, ${d.getUTCFullYear()}`;
  if (!conHora) return fecha;
  const h = d.getUTCHours();
  const m = String(d.getUTCMinutes()).padStart(2, "0");
  return `${fecha} ${((h + 11) % 12) + 1}:${m} ${h < 12 ? "AM" : "PM"}`;
}

function marcaEje(time, tipo) {
  const d = new Date(time * 1000);
  if (tipo === 0) return String(d.getUTCFullYear());
  if (tipo === 1) return MESES[d.getUTCMonth()];
  if (tipo === 2) return `${MESES[d.getUTCMonth()]} ${d.getUTCDate()}`;
  return `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`;
}

// --- Carga ---

async function preparar(escena) {
  const respuesta = await fetch("/api/estudio/preparar", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(escena),
  });
  const datos = await respuesta.json();
  if (!respuesta.ok) {
    const detalle = Array.isArray(datos.detail) ? datos.detail.map((e) => e.msg).join("\n") : datos.detail;
    throw new Error(detalle || respuesta.statusText);
  }
  return datos;
}

function crearGrafico() {
  est.grafico?.remove();
  const { tema, escena } = est;
  const tf = escena.tf;
  const intradia = tf !== "1D";
  est.grafico = createChart($("grafico"), {
    width: est.ancho,
    height: est.alto,
    layout: {
      background: { color: tema.fondo },
      textColor: tema.texto,
      fontFamily: tema.fuente,
      fontSize: Math.round(tema.tamano_eje * est.escala),
      attributionLogo: escena.lienzo.logo_tradingview !== false,
      panes: { separatorColor: tema.rejilla },
    },
    grid: { vertLines: { color: tema.rejilla }, horzLines: { color: tema.rejilla } },
    crosshair: { mode: 2 }, // oculta: nada depende del ratón
    handleScroll: false,
    handleScale: false,
    kineticScroll: { mouse: false, touch: false },
    rightPriceScale: { borderVisible: false },
    timeScale: {
      visible: escena.lienzo.eje_tiempo !== false,
      borderVisible: false,
      timeVisible: intradia,
      secondsVisible: false,
      shiftVisibleRangeOnNewBar: false,
      tickMarkFormatter: marcaEje,
    },
    localization: {
      locale: "en-US",
      timeFormatter: (time) => fechaIngles(time, intradia),
      priceFormatter: (p) => formatoPrecio(p),
    },
  });
  est.serie = est.grafico.addSeries(CandlestickSeries, {
    upColor: tema.alcista,
    downColor: tema.bajista,
    wickUpColor: tema.alcista,
    wickDownColor: tema.bajista,
    borderVisible: false,
    priceLineVisible: false,
    lastValueVisible: false,
  });

  // Indicadores: los de la escena se ven desde el principio; los de pasos `indicador`, desde su t.
  est.volumen = null;
  est.lineas = [];
  const defs = [
    ...escena.indicadores.map((d) => ({ def: d, paso: null })),
    ...escena.pasos.filter((p) => p.accion === "indicador").map((p) => ({ def: p, paso: p })),
  ];
  defs.forEach(({ def, paso }, i) => {
    const colorLinea = colorDe(def.color, null) ?? COLORES_INDICADOR[i % COLORES_INDICADOR.length];
    if (def.tipo === "volumen") {
      est.volumen = {
        paso,
        serie: est.grafico.addSeries(HistogramSeries, {
          priceScaleId: "volumen",
          priceFormat: { type: "volume" },
          lastValueVisible: false,
          priceLineVisible: false,
        }),
      };
      est.grafico.priceScale("volumen").applyOptions({ scaleMargins: { top: 0.86, bottom: 0 } });
      return;
    }
    const panel = def.tipo === "rsi" || def.tipo === "atr" ? 1 : 0;
    const serie = est.grafico.addSeries(
      LineSeries,
      { color: colorLinea, lineWidth: Math.round(3 * est.escala), priceLineVisible: false, lastValueVisible: false },
      panel,
    );
    if (def.tipo === "rsi") {
      for (const nivel of [30, 70]) serie.createPriceLine({ price: nivel, color: tema.rejilla, lineWidth: 1, axisLabelVisible: true });
    }
    const periodo = def.periodo ?? (def.tipo === "rsi" || def.tipo === "atr" ? 14 : 20);
    est.lineas.push({ def, paso, serie, indicador: INDICADORES[def.tipo](periodo) });
  });
  est.claveVelas = "";
}

// Vista inicial y la de cada paso `camara`, en posiciones lógicas y precios.
function calcularVistas() {
  const { escena } = est;
  const { velas, tf_segundos: paso } = escena;
  const extra = [];
  let maxLogico = velas.length - 1;
  for (const p of escena.pasos) {
    for (const campo of ["precio", "stop", "objetivo"]) if (typeof p[campo] === "number") extra.push(p[campo]);
    for (const precio of p.precios ?? []) extra.push(precio);
    const puntos = [...(p.puntos ?? []), ...(p.punto ? [p.punto] : []), ...(p.entrada ? [p.entrada] : [])];
    for (const [t, precio] of puntos) {
      extra.push(precio);
      maxLogico = Math.max(maxLogico, logico(velas, t, paso));
    }
  }
  const v = escena.vista;
  const desde = v.desde != null ? logico(velas, v.desde, paso) - 0.5 : -0.5;
  const hasta = v.hasta != null ? logico(velas, v.hasta, paso) + 0.5 : maxLogico + 1.5;
  est.base = {
    logico: { from: desde, to: hasta },
    precio: v.precio ? { from: v.precio[0], to: v.precio[1] } : rangoPrecio(velas, desde, hasta, extra),
  };
  // Precios de los dibujos anclados dentro de una ventana de tiempo (etiquetas, marcas, operaciones),
  // para que la cámara no los deje fuera al acercarse.
  const preciosEn = (de, a) => {
    const lista = [];
    const dentro = (t) => {
      const l = logico(velas, t, paso);
      return l >= de && l <= a;
    };
    for (const p of escena.pasos) {
      for (const [t, precio] of [...(p.puntos ?? []), ...(p.punto ? [p.punto] : [])]) if (dentro(t)) lista.push(precio);
      if (p.entrada && dentro(p.entrada[0])) lista.push(p.entrada[1], p.stop, p.objetivo);
    }
    return lista;
  };
  est.camaras = escena.pasos
    .filter((p) => p.accion === "camara")
    .map((p) => {
      const de = logico(velas, p.desde, paso) - 0.5;
      const a = logico(velas, p.hasta, paso) + 0.5;
      const precio = p.precio ? { from: p.precio[0], to: p.precio[1] } : rangoPrecio(velas, de, a, preciosEn(de, a), 0.12);
      return { ...p, vista: { logico: { from: de, to: a }, precio } };
    });
  est.ocultaciones = escena.pasos.filter((p) => p.accion === "ocultar");
}

function ajustarAVentana() {
  if (modoCaptura) {
    est.escalaVista = 1;
  } else {
    const caja = $("escenario").getBoundingClientRect();
    est.escalaVista = Math.min(caja.width / est.ancho, caja.height / est.alto);
  }
  lienzo.style.transform = `scale(${est.escalaVista})`;
  const sobra = $("escenario").getBoundingClientRect().width - est.ancho * est.escalaVista;
  lienzo.style.left = modoCaptura ? "0" : `${Math.max(0, sobra / 2)}px`;
}

async function cargar(escena, { conservarT = false } = {}) {
  const preparada = escena.velas && escena.tf_segundos ? escena : await preparar(escena);
  est.original = escena.velas && escena.tf_segundos ? est.original : structuredClone(escena);
  est.escena = preparada;
  const aspecto = preparada.lienzo.aspecto;
  [est.ancho, est.alto] = TAMANOS[aspecto];
  est.escala = aspecto === "9:16" ? (preparada.lienzo.escala_texto ?? ESCALA_VERTICAL) : (preparada.lienzo.escala_texto ?? 1);
  est.tema = { ...TEMA_BASE, ...(preparada.lienzo.tema ?? {}) };
  lienzo.style.width = `${est.ancho}px`;
  lienzo.style.height = `${est.alto}px`;
  capa.width = est.ancho;
  capa.height = est.alto;
  ajustarAVentana();
  // Widgets (spec 011): sin gráfico de velas, todo se pinta en la capa.
  $("grafico").style.display = preparada.widget ? "none" : "";
  if (preparada.widget) {
    est.grafico?.remove();
    est.grafico = null;
    est.ocultaciones = preparada.pasos.filter((p) => p.accion === "ocultar");
  } else {
    crearGrafico();
    calcularVistas();
  }
  if (!modoCaptura) actualizarBarra();
  await document.fonts.ready;
  await ir(conservarT ? Math.min(est.t, preparada.duracion) : 0);
  return { duracion: preparada.duracion };
}

// --- Pintar el instante t ---

function velasEn(t) {
  const { velas, pasos } = est.escena;
  const { completas, parcial } = velasVisibles(velas, pasos, t);
  const lista = velas.slice(0, completas);
  if (parcial) lista.push(parcial);
  return lista;
}

// Atenuación de cada vela por los pasos `resaltar`: 1 = normal.
function brillos(lista, t) {
  const brillo = new Array(lista.length).fill(1);
  for (const paso of est.escena.pasos) {
    if (paso.accion !== "resaltar" || t < paso.t) continue;
    const fuerza = progresoPaso(paso, t) * opacidad(paso.id, est.ocultaciones, t);
    if (paso.atenuar_resto === false) continue;
    const elegidas = new Set(paso.velas);
    lista.forEach((v, i) => {
      if (!elegidas.has(v.time)) brillo[i] = Math.min(brillo[i], lerp(1, 0.22, fuerza));
    });
  }
  return brillo;
}

function aplicarGrafico(t) {
  if (est.escena.widget) return;
  const { tema } = est;
  const lista = velasEn(t);
  const brillo = brillos(lista, t);
  const ultima = lista[lista.length - 1];
  const clave = `${lista.length}|${ultima?.close}|${ultima?.high}|${ultima?.low}|${brillo.join(",")}`;
  if (clave !== est.claveVelas) {
    est.claveVelas = clave;
    est.serie.setData(
      lista.map((v, i) => {
        if (brillo[i] === 1) return v;
        const c = conAlfa(v.close >= v.open ? tema.alcista : tema.bajista, brillo[i]);
        return { ...v, color: c, wickColor: c };
      }),
    );
    if (est.volumen) {
      est.volumen.serie.setData(
        lista.map((v) => ({ time: v.time, value: v.volume, color: conAlfa(v.close >= v.open ? tema.alcista : tema.bajista, 0.45) })),
      );
    }
  }
  for (const linea of est.lineas) {
    const p = linea.paso ? progresoPaso(linea.paso, t) : 1;
    const alfa = linea.paso ? opacidad(linea.paso.id, est.ocultaciones, t) : 1;
    if (p <= 0 || alfa <= 0 || !lista.length) {
      linea.serie.setData([]);
      continue;
    }
    const { valores } = calcular(linea.indicador, lista);
    const datos = [];
    lista.forEach((v, i) => valores[i] !== null && datos.push({ time: v.time, value: valores[i] }));
    linea.serie.setData(datos.slice(0, Math.ceil(datos.length * p)));
    linea.serie.applyOptions({ visible: alfa > 0.05 });
  }
  if (est.volumen?.paso) est.volumen.serie.applyOptions({ visible: t >= est.volumen.paso.t });

  const vista = vistaEn(est.base, est.camaras, t);
  est.grafico.timeScale().setVisibleLogicalRange(vista.logico);
  if (vista.precio) est.serie.priceScale().setVisibleRange(vista.precio);
}

// --- Capa de dibujo ---

const px = (t) => est.grafico.timeScale().logicalToCoordinate(logico(est.escena.velas, t, est.escena.tf_segundos));
const py = (precio) => est.serie.priceToCoordinate(precio);

function texto(ctx, contenido, x, y, { alinear = "left", base = "middle", color, fondo = true, tamano = 1, negrita = true } = {}) {
  const t = est.tema;
  const fuente = Math.round(t.tamano_texto * est.escala * tamano);
  ctx.font = `${negrita ? 600 : 400} ${fuente}px ${t.fuente}`;
  const ancho = ctx.measureText(contenido).width;
  const relleno = fuente * 0.35;
  let x0 = alinear === "left" ? x : alinear === "right" ? x - ancho : x - ancho / 2;
  let y0 = base === "middle" ? y - fuente / 2 : base === "bottom" ? y - fuente : y;
  if (fondo) {
    ctx.fillStyle = t.etiqueta_fondo;
    ctx.beginPath();
    ctx.roundRect(x0 - relleno, y0 - relleno * 0.6, ancho + 2 * relleno, fuente + 1.2 * relleno, relleno * 0.8);
    ctx.fill();
  }
  ctx.fillStyle = color ?? t.etiqueta_texto;
  ctx.textBaseline = "top";
  ctx.fillText(contenido, x0, y0 + fuente * 0.05);
  return { x0, y0, ancho, alto: fuente };
}

function etiquetaEje(ctx, precio, color) {
  const y = py(precio);
  if (y === null) return;
  const panel = est.grafico.paneSize(0);
  const fuente = Math.round(est.tema.tamano_eje * est.escala);
  ctx.font = `600 ${fuente}px ${est.tema.fuente}`;
  const contenido = formatoPrecio(precio);
  const ancho = ctx.measureText(contenido).width + fuente * 0.8;
  ctx.fillStyle = color;
  ctx.fillRect(panel.width, y - fuente * 0.75, ancho, fuente * 1.5);
  ctx.fillStyle = "#ffffff";
  ctx.textBaseline = "middle";
  ctx.fillText(contenido, panel.width + fuente * 0.4, y);
}

function flecha(ctx, x1, y1, x2, y2, grosor) {
  const angulo = Math.atan2(y2 - y1, x2 - x1);
  const punta = grosor * 5;
  ctx.beginPath();
  ctx.moveTo(x1, y1);
  ctx.lineTo(x2 - Math.cos(angulo) * punta * 0.6, y2 - Math.sin(angulo) * punta * 0.6);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(x2, y2);
  ctx.lineTo(x2 - punta * Math.cos(angulo - 0.45), y2 - punta * Math.sin(angulo - 0.45));
  ctx.lineTo(x2 - punta * Math.cos(angulo + 0.45), y2 - punta * Math.sin(angulo + 0.45));
  ctx.closePath();
  ctx.fill();
}

function dibujarPaso(ctx, paso, t, panel) {
  const p = suavizar(progresoPaso(paso, t));
  const alfa = opacidad(paso.id, est.ocultaciones, t);
  if (p <= 0 || alfa <= 0) return;
  const tinta = colorDe(paso.color);
  const grosor = (paso.grosor ?? est.tema.grosor) * est.escala;
  ctx.save();
  ctx.globalAlpha = alfa;
  ctx.strokeStyle = tinta;
  ctx.fillStyle = tinta;
  ctx.lineWidth = grosor;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  const aparecer = Math.max(0, (progresoPaso(paso, t) - 0.6) / 0.4); // las etiquetas entran al final

  switch (paso.accion) {
    case "horizontal": {
      const y = py(paso.precio);
      if (y === null) break;
      const x0 = paso.desde != null ? px(paso.desde) ?? 0 : 0;
      const x1 = x0 + (panel.width - x0) * p;
      if (paso.discontinua) ctx.setLineDash([grosor * 4, grosor * 3]);
      ctx.beginPath();
      ctx.moveTo(x0, y);
      ctx.lineTo(x1, y);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.globalAlpha = alfa * aparecer;
      if (paso.etiqueta) texto(ctx, paso.etiqueta, panel.width - 24 * est.escala, y - grosor * 2, { alinear: "right", base: "bottom", color: tinta });
      ctx.restore();
      ctx.save();
      ctx.globalAlpha = alfa * p;
      if (paso.mostrar_precio !== false) etiquetaEje(ctx, paso.precio, tinta);
      break;
    }
    case "tendencia":
    case "flecha": {
      const [a, b] = paso.puntos.map(([tt, precio]) => ({ x: px(tt), y: py(precio) }));
      if ([a.x, a.y, b.x, b.y].includes(null)) break;
      let fin = { x: lerp(a.x, b.x, p), y: lerp(a.y, b.y, p) };
      if (paso.accion === "flecha") flecha(ctx, a.x, a.y, fin.x, fin.y, grosor);
      else {
        if (paso.extender && p >= 1 && b.x !== a.x) {
          const m = (b.y - a.y) / (b.x - a.x);
          fin = { x: panel.width, y: b.y + m * (panel.width - b.x) };
        }
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(fin.x, fin.y);
        ctx.stroke();
      }
      ctx.globalAlpha = alfa * aparecer;
      // Flecha: la etiqueta va en la punta, hacia donde apunta. Línea: en el primer punto.
      const ancla = paso.accion === "flecha" ? b : a;
      const haciaAbajo = paso.accion === "flecha" ? b.y > a.y : a.y > b.y;
      if (paso.etiqueta) texto(ctx, paso.etiqueta, ancla.x, ancla.y + (haciaAbajo ? 1 : -1) * grosor * 6, { alinear: "center", base: haciaAbajo ? "top" : "bottom", color: tinta });
      break;
    }
    case "rectangulo": {
      const [a, b] = paso.puntos.map(([tt, precio]) => ({ x: px(tt), y: py(precio) }));
      if ([a.x, a.y, b.x, b.y].includes(null)) break;
      const x = lerp(a.x, b.x, p);
      const y = lerp(a.y, b.y, p);
      ctx.fillStyle = conAlfa(tinta, 0.16);
      ctx.fillRect(Math.min(a.x, x), Math.min(a.y, y), Math.abs(x - a.x), Math.abs(y - a.y));
      ctx.strokeRect(Math.min(a.x, x), Math.min(a.y, y), Math.abs(x - a.x), Math.abs(y - a.y));
      ctx.globalAlpha = alfa * aparecer;
      if (paso.etiqueta) texto(ctx, paso.etiqueta, Math.min(a.x, b.x), Math.min(a.y, b.y) - grosor * 2, { base: "bottom", color: tinta });
      break;
    }
    case "zona": {
      const [bajo, alto] = paso.precios;
      const y1 = py(alto);
      const y2 = py(bajo);
      const x0 = px(paso.desde);
      if ([y1, y2, x0].includes(null)) break;
      const xFin = paso.hasta != null ? px(paso.hasta) ?? panel.width : panel.width;
      const x1 = lerp(x0, xFin, p);
      ctx.fillStyle = conAlfa(tinta, 0.18);
      ctx.fillRect(x0, y1, x1 - x0, y2 - y1);
      ctx.lineWidth = grosor * 0.6;
      ctx.beginPath();
      ctx.moveTo(x0, y1);
      ctx.lineTo(x1, y1);
      ctx.moveTo(x0, y2);
      ctx.lineTo(x1, y2);
      ctx.stroke();
      ctx.globalAlpha = alfa * aparecer;
      if (paso.etiqueta) texto(ctx, paso.etiqueta, x0 + 16 * est.escala, y1 - grosor * 2, { base: "bottom", color: tinta });
      break;
    }
    case "marca": {
      const x = px(paso.punto[0]);
      const y = py(paso.punto[1]);
      if (x === null || y === null) break;
      const radio = (paso.radio ?? 30) * est.escala * salida(progresoPaso(paso, t));
      ctx.beginPath();
      ctx.arc(x, y, radio, 0, Math.PI * 2);
      ctx.stroke();
      ctx.globalAlpha = alfa * aparecer;
      const abajo = paso.posicion === "debajo";
      if (paso.etiqueta) texto(ctx, paso.etiqueta, x, y + (abajo ? 1 : -1) * (radio + grosor * 3), { alinear: "center", base: abajo ? "top" : "bottom", color: tinta });
      break;
    }
    case "etiqueta": {
      const x = px(paso.punto[0]);
      const y = py(paso.punto[1]);
      if (x === null || y === null) break;
      ctx.globalAlpha = alfa * p;
      texto(ctx, paso.texto, x, y, { alinear: paso.alinear ?? "center", color: colorDe(paso.color, "etiqueta_texto"), tamano: paso.tamano ?? 1 });
      break;
    }
    case "pincel": {
      const puntos = trazoHasta(paso.puntos, progresoPaso(paso, t)).map(([tt, precio]) => [px(tt), py(precio)]);
      if (puntos.length < 2 || puntos.some(([x, y]) => x === null || y === null)) break;
      ctx.strokeStyle = colorDe(paso.color, "pincel");
      ctx.lineWidth = grosor * 1.4;
      ctx.beginPath();
      ctx.moveTo(...puntos[0]);
      for (const punto of puntos.slice(1)) ctx.lineTo(...punto);
      ctx.stroke();
      break;
    }
    case "ohlc": {
      const vela = est.escena.velas.find((v) => v.time === paso.vela);
      const x = px(paso.vela);
      if (!vela || x === null) break;
      const nombres = { open: "Open", high: "High", low: "Low", close: "Close", ...(paso.nombres ?? {}) };
      const orden = ["open", "high", "low", "close"];
      const avance = progresoPaso(paso, t) * orden.length;
      const ancho = Math.max(14, est.grafico.timeScale().options().barSpacing * 0.6);
      orden.forEach((clave, i) => {
        const parte = Math.min(1, Math.max(0, avance - i));
        if (parte <= 0) return;
        const y = py(vela[clave]);
        const lado = clave === "open" ? -1 : 1;
        ctx.globalAlpha = alfa * parte;
        ctx.beginPath();
        ctx.moveTo(x + lado * ancho * 0.6, y);
        ctx.lineTo(x + lado * ancho * 2.2, y);
        ctx.stroke();
        const valor = `${nombres[clave]}  ${paso.dolares ? "$" : ""}${formatoPrecio(vela[clave])}`;
        texto(ctx, valor, x + lado * ancho * 2.6, y, { alinear: lado < 0 ? "right" : "left", color: tinta, tamano: 0.85 });
      });
      break;
    }
    case "operacion": {
      const [t0, entrada] = paso.entrada;
      const x0 = px(t0);
      const xFin = paso.hasta != null ? px(paso.hasta) : px(t0 + 15 * est.escena.tf_segundos);
      const [ye, ys, yo] = [py(entrada), py(paso.stop), py(paso.objetivo)];
      if ([x0, xFin, ye, ys, yo].includes(null)) break;
      const x1 = lerp(x0, xFin, p);
      ctx.fillStyle = conAlfa(est.tema.compra, 0.2);
      ctx.fillRect(x0, Math.min(ye, yo), x1 - x0, Math.abs(yo - ye));
      ctx.fillStyle = conAlfa(est.tema.venta, 0.2);
      ctx.fillRect(x0, Math.min(ye, ys), x1 - x0, Math.abs(ys - ye));
      ctx.lineWidth = grosor * 0.6;
      for (const [y, c] of [[ye, est.tema.texto], [yo, est.tema.compra], [ys, est.tema.venta]]) {
        ctx.strokeStyle = c;
        ctx.beginPath();
        ctx.moveTo(x0, y);
        ctx.lineTo(x1, y);
        ctx.stroke();
      }
      ctx.globalAlpha = alfa * aparecer;
      const n = paso.nombres ?? {};
      texto(ctx, n.objetivo ?? "Target", x1 + 12 * est.escala, yo, { color: est.tema.compra, tamano: 0.8 });
      texto(ctx, n.entrada ?? "Entry", x1 + 12 * est.escala, ye, { tamano: 0.8 });
      texto(ctx, n.stop ?? "Stop", x1 + 12 * est.escala, ys, { color: est.tema.venta, tamano: 0.8 });
      if (paso.rr) {
        const rr = Math.abs(paso.objetivo - entrada) / Math.abs(entrada - paso.stop);
        texto(ctx, `R:R 1:${rr.toFixed(rr % 1 ? 1 : 0)}`, (x0 + x1) / 2, Math.min(ye, yo, ys) - grosor * 3, { alinear: "center", base: "bottom", tamano: 0.8 });
      }
      break;
    }
  }
  ctx.restore();
}

function dibujarCapa(t) {
  if (est.escena.widget) return dibujarWidget(t);
  const ctx = capa.getContext("2d");
  ctx.clearRect(0, 0, capa.width, capa.height);
  const panel = est.grafico.paneSize(0);
  ctx.save();
  // Los dibujos se recortan al panel de precio; las etiquetas del eje se pintan después, fuera del recorte.
  ctx.beginPath();
  ctx.rect(0, 0, panel.width + 400, panel.height);
  ctx.clip();
  for (const paso of est.escena.pasos) {
    if (DIBUJABLES.has(paso.accion)) dibujarPaso(ctx, paso, t, panel);
  }
  if (est.trazo?.puntos.length > 1) {
    ctx.strokeStyle = est.tema.pincel;
    ctx.lineWidth = est.tema.grosor * est.escala * 1.4;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.beginPath();
    est.trazo.pixeles.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
    ctx.stroke();
  }
  ctx.restore();

  const lz = est.escena.lienzo;
  let y = 24 * est.escala;
  if (lz.titulo) y += texto(ctx, lz.titulo, 24 * est.escala, y, { base: "top", fondo: false, color: est.tema.texto, tamano: 1.1 }).alto + 12;
  if (lz.ilustrativo) {
    texto(ctx, lz.texto_ilustrativo ?? "Illustrative example", 24 * est.escala, y, { base: "top", color: est.tema.dibujo, tamano: 0.7, negrita: false });
  }
}

// Deja el lienzo como debe estar en el instante t (RF-7) y espera a que esté pintado.
async function ir(t) {
  est.t = Math.max(0, Math.min(t, est.escena.duracion));
  aplicarGrafico(est.t);
  await siguienteCuadro();
  dibujarCapa(est.t);
  await siguienteCuadro();
  if (!modoCaptura) pintarPosicion();
}

// --- Modo manual (RF-12 a RF-14) ---

function aviso(mensaje, error = false) {
  $("aviso").textContent = mensaje;
  $("aviso").style.color = error ? "#ef5350" : "#26a69a";
}

function pintarPosicion() {
  const d = est.escena.duracion;
  $("posicion").max = String(d);
  $("posicion").value = String(est.t);
  $("tiempo").textContent = `${est.t.toFixed(1)} / ${d.toFixed(1)} s`;
}

function actualizarBarra() {
  $("aspecto").value = est.escena.lienzo.aspecto;
  const marcas = $("marcas");
  marcas.replaceChildren(
    ...est.escena.pasos.map((p) => {
      const marca = document.createElement("span");
      marca.style.left = `${(p.t / est.escena.duracion) * 100}%`;
      marca.title = `${p.t}s · ${p.accion}${p.id ? ` (${p.id})` : ""}`;
      return marca;
    }),
  );
  pintarPosicion();
}

function reproducir() {
  if (est.reproduciendo) {
    est.reproduciendo = false;
    $("play").textContent = "▶";
    return;
  }
  if (est.t >= est.escena.duracion) est.t = 0;
  est.reproduciendo = true;
  $("play").textContent = "❚❚";
  const inicioReal = performance.now() - est.t * 1000;
  const cuadro = () => {
    if (!est.reproduciendo) return;
    est.t = Math.min((performance.now() - inicioReal) / 1000, est.escena.duracion);
    aplicarGrafico(est.t);
    dibujarCapa(est.t);
    pintarPosicion();
    if (est.t >= est.escena.duracion) reproducir();
    else requestAnimationFrame(cuadro);
  };
  requestAnimationFrame(cuadro);
}

async function recargar(escena, opciones) {
  try {
    await cargar(escena, opciones);
    aviso("");
  } catch (error) {
    aviso(error.message, true);
  }
}

function posicionEnLienzo(evento) {
  const caja = lienzo.getBoundingClientRect();
  return [(evento.clientX - caja.left) / est.escalaVista, (evento.clientY - caja.top) / est.escalaVista];
}

function iniciarPincel() {
  capa.addEventListener("pointerdown", (evento) => {
    if (!lienzo.classList.contains("pincel-activo")) return;
    if (est.reproduciendo) reproducir();
    capa.setPointerCapture(evento.pointerId);
    est.trazo = { inicio: performance.now(), puntos: [], pixeles: [] };
    anadirPunto(evento);
  });
  capa.addEventListener("pointermove", (evento) => {
    if (!est.trazo) return;
    anadirPunto(evento);
    dibujarCapa(est.t);
  });
  capa.addEventListener("pointerup", async () => {
    const trazo = est.trazo;
    est.trazo = null;
    if (!trazo || trazo.puntos.length < 2) return dibujarCapa(est.t);
    const n = est.original.pasos?.filter((p) => String(p.id).startsWith("pincel-")).length ?? 0;
    const duracion = Math.max(0.2, trazo.puntos[trazo.puntos.length - 1][2] / 1000);
    est.original.pasos = [
      ...(est.original.pasos ?? []),
      { id: `pincel-${n + 1}`, t: Math.round(est.t * 100) / 100, accion: "pincel", duracion: Math.round(duracion * 100) / 100, puntos: trazo.puntos },
    ];
    if (est.original.duracion && est.t + duracion > est.original.duracion) est.original.duracion = Math.ceil(est.t + duracion + 1);
    await recargar(est.original, { conservarT: true });
    aviso(`Trazo grabado (pincel-${n + 1}). Exporta la escena para guardarlo.`);
  });
}

function anadirPunto(evento) {
  if (!est.grafico) return; // el pincel solo dibuja sobre gráficos
  const [x, y] = posicionEnLienzo(evento);
  const logicoX = est.grafico.timeScale().coordinateToLogical(x);
  const precio = est.serie.coordinateToPrice(y);
  if (logicoX === null || precio === null) return;
  est.trazo.puntos.push([
    Math.max(0, Math.round(logicoX * 1000) / 1000),
    Math.round(precio * 100) / 100,
    Math.round(performance.now() - est.trazo.inicio),
  ]);
  est.trazo.pixeles.push([x, y]);
}

function descargar(nombre, contenido) {
  const enlace = document.createElement("a");
  enlace.href = URL.createObjectURL(new Blob([contenido], { type: "application/json" }));
  enlace.download = nombre;
  enlace.click();
  setTimeout(() => URL.revokeObjectURL(enlace.href), 1000);
}

function iniciarInterfaz() {
  $("play").addEventListener("click", reproducir);
  $("posicion").addEventListener("input", () => {
    if (est.reproduciendo) reproducir();
    ir(Number($("posicion").value));
  });
  $("aspecto").addEventListener("change", () => {
    est.original.lienzo = { ...(est.original.lienzo ?? {}), aspecto: $("aspecto").value };
    recargar(est.original, { conservarT: true });
  });
  $("abrir").addEventListener("change", async () => {
    const archivo = $("abrir").files[0];
    if (!archivo) return;
    try {
      await recargar(JSON.parse(await archivo.text()));
      est.nombre = archivo.name;
    } catch (error) {
      aviso(`No es un JSON válido: ${error.message}`, true);
    }
  });
  $("boton-pegar").addEventListener("click", () => {
    $("json").value = JSON.stringify(est.original, null, 2);
    $("panel-json").hidden = !$("panel-json").hidden;
  });
  $("cerrar-json").addEventListener("click", () => ($("panel-json").hidden = true));
  $("aplicar").addEventListener("click", async () => {
    try {
      await recargar(JSON.parse($("json").value));
    } catch (error) {
      aviso(`No es un JSON válido: ${error.message}`, true);
    }
  });
  const alternarPincel = () => {
    const activo = lienzo.classList.toggle("pincel-activo");
    $("pincel").setAttribute("aria-pressed", String(activo));
  };
  $("pincel").addEventListener("click", alternarPincel);
  $("deshacer").addEventListener("click", () => {
    const pasos = est.original.pasos ?? [];
    const i = pasos.map((p) => String(p.id).startsWith("pincel-")).lastIndexOf(true);
    if (i < 0) return aviso("No hay trazos grabados.", true);
    pasos.splice(i, 1);
    recargar(est.original, { conservarT: true });
  });
  $("exportar").addEventListener("click", () => descargar(est.nombre ?? "escena.json", JSON.stringify(est.original, null, 2)));
  const alternarLimpio = () => {
    document.body.classList.toggle("limpio");
    if (document.body.classList.contains("limpio")) document.documentElement.requestFullscreen?.().catch(() => {});
    else if (document.fullscreenElement) document.exitFullscreen();
    setTimeout(ajustarAVentana, 100);
  };
  $("limpio").addEventListener("click", alternarLimpio);
  window.addEventListener("resize", ajustarAVentana);
  document.addEventListener("keydown", (evento) => {
    if (evento.target.tagName === "TEXTAREA" || evento.target.tagName === "INPUT" && evento.target.type !== "range") return;
    if (evento.key === " ") {
      evento.preventDefault();
      reproducir();
    } else if (evento.key === "f" || evento.key === "F") alternarLimpio();
    else if (evento.key === "p" || evento.key === "P") alternarPincel();
    else if (evento.key === "Escape" && document.body.classList.contains("limpio")) alternarLimpio();
  });
  iniciarPincel();
}

// Escena de ejemplo para no empezar con la página vacía: una vela explicada.
const ESCENA_EJEMPLO = {
  formato: 1,
  lienzo: { aspecto: "16:9", titulo: "XYZ · Daily" },
  datos: {
    tipo: "manual",
    velas: [[100, 103, 99, 102], [102, 104, 101, 103.5], [103.5, 104, 100.5, 101], [101, 102, 98, 99.5], [99.5, 101, 97.5, 100.5],
      [100.5, 105.5, 100, 101.2], [101.2, 102.5, 100.8, 102], [102, 103.8, 101.5, 103.4]],
  },
  pasos: [
    { t: 0, accion: "revelar", desde: 0, hasta: 7, duracion: 4 },
    { id: "foco", t: 4.5, accion: "resaltar", velas: [5], duracion: 0.8 },
    { t: 5, accion: "ohlc", vela: 5, duracion: 3 },
    { t: 8.5, accion: "marca", punto: [5, 105.5], etiqueta: "Long upper wick", duracion: 0.8 },
    { t: 10, accion: "ocultar", objetivos: ["foco"], duracion: 0.6 },
  ],
};

window.estudio = {
  cargar: (escena) => cargar(escena),
  ir,
  duracion: () => est.escena?.duracion ?? 0,
  escena: () => est.escena,
  original: () => est.original,
};

(async () => {
  if (!modoCaptura) iniciarInterfaz();
  const ruta = parametros.get("escena");
  if (modoCaptura && !ruta) return; // la captura carga la escena con estudio.cargar()
  try {
    const escena = ruta ? await (await fetch(ruta)).json() : ESCENA_EJEMPLO;
    await cargar(escena);
  } catch (error) {
    aviso(error.message, true);
  }
})();
