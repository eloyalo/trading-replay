// Herramientas de dibujo (spec 004): línea horizontal, línea de tendencia, rectángulo y Fibonacci (spec 012). Se pintan
// con una primitiva de Lightweight Charts sobre el panel de precio. Cada punto se guarda en tiempo y
// precio (`{t, precio}`, con `t` como el `time` de las velas), así que el dibujo sigue en su sitio al
// cambiar de timeframe y se puede poner a la derecha de la última vela (calculos.js, tiempoALogico).

const TOLERANCIA = 6; // px para acertar a un dibujo o a uno de sus puntos de control
const PUNTOS_POR_TIPO = { horizontal: 1, tendencia: 2, rectangulo: 2, fibonacci: 2 };
const ATAJOS_DIBUJO = { h: "horizontal", t: "tendencia", b: "rectangulo", f: "fibonacci" };

// --- Fibonacci: niveles y pintado, sin depender de la selección para poder usarlo en el backtest ---

const FIB_RETROCESOS = [0, 0.236, 0.382, 0.5, 0.618, 0.65, 0.786, 1];
const FIB_EXTENSIONES = [1.272, 1.618, 2, 2.618];
const FIB_CONFIG_BASE = {
  retrocesos: FIB_RETROCESOS, // niveles visibles (los propios también)
  extensiones: FIB_EXTENSIONES, // extensiones visibles, si `conExtensiones`
  propios: [], // niveles añadidos por el usuario, para poder volver a marcarlos
  conExtensiones: false,
  extender: false, // las líneas llegan hasta el último punto del dibujo; con true, hasta el final visible
  precio: true,
  porcentaje: true,
};
const FIB_ZONA = [0.618, 0.65]; // zona resaltada

function configFibonacci() {
  return { ...FIB_CONFIG_BASE, ...preferencias.leer("fibonacci.config", {}) };
}

// Lista de niveles {valor, precio, extension} de un impulso {origen: {t, precio}, final: {t, precio},
// retrocesos, extensiones}; es el formato de la marca `fibonacci` de las estrategias (spec 012, RF-24).
function nivelesFibonacci({ origen, final, retrocesos = [], extensiones = [] }) {
  return [
    ...fibonacciNiveles(origen.precio, final.precio, retrocesos).map((n) => ({ ...n, extension: false })),
    ...fibonacciExtensiones(origen.precio, final.precio, extensiones).map((n) => ({ ...n, extension: true })),
  ];
}

// Pinta la figura con coordenadas ya en píxeles: `p1` (origen) y `p2` (final) son {x, y, precio}.
// Las líneas llegan hasta `opciones.xFin` (por defecto, `ancho`). Opciones: tinta, texto, grosor.
function pintarFibonacci(ctx, ancho, p1, p2, config, opciones = {}) {
  const tinta = opciones.tinta ?? color("--dibujo");
  const xIni = Math.min(p1.x, p2.x);
  const xFin = Math.max(opciones.xFin ?? ancho, xIni + 1);
  const niveles = nivelesFibonacci({
    origen: { precio: p1.precio },
    final: { precio: p2.precio },
    retrocesos: config.retrocesos,
    extensiones: config.conExtensiones ? config.extensiones : [],
  });
  // El nivel 0 es el final y el 1 el origen; las extensiones se miden desde el origen.
  const alturaDe = (valor, extension) => p1.y + (p2.y - p1.y) * (extension ? valor : 1 - valor);
  const lineas = niveles.map((n) => ({ ...n, y: alturaDe(n.valor, n.extension) })).sort((a, b) => a.y - b.y);

  ctx.save();
  ctx.fillStyle = tinta;
  const rectas = lineas.filter((n) => !n.extension);
  rectas.slice(1).forEach((n, i) => {
    ctx.globalAlpha = i % 2 ? 0.05 : 0.11;
    ctx.fillRect(xIni, rectas[i].y, xFin - xIni, n.y - rectas[i].y);
  });
  if (FIB_ZONA.every((z) => config.retrocesos.includes(z))) {
    const [y1, y2] = FIB_ZONA.map((z) => alturaDe(z, false));
    ctx.globalAlpha = 0.3;
    ctx.fillStyle = "#ffc107";
    ctx.fillRect(xIni, Math.min(y1, y2), xFin - xIni, Math.abs(y2 - y1));
  }
  ctx.globalAlpha = 1;
  ctx.strokeStyle = tinta;
  ctx.lineWidth = opciones.grosor ?? 1;
  ctx.font = "11px sans-serif";
  ctx.textBaseline = "bottom";
  for (const n of lineas) {
    ctx.globalAlpha = n.extension ? 0.7 : 1;
    ctx.beginPath();
    ctx.moveTo(xIni, n.y);
    ctx.lineTo(xFin, n.y);
    ctx.stroke();
    const texto = [config.porcentaje ? `${Math.round(n.valor * 1000) / 10}%` : "", config.precio ? n.precio.toFixed(2) : ""]
      .filter(Boolean)
      .join("  ");
    if (texto) {
      ctx.fillStyle = opciones.texto ?? tinta;
      ctx.fillText(texto, xIni + 4, n.y - 2);
    }
  }
  // La diagonal une el origen con el final del impulso.
  ctx.globalAlpha = 0.8;
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(p1.x, p1.y);
  ctx.lineTo(p2.x, p2.y);
  ctx.stroke();
  ctx.restore();
}

const dibujo = {
  herramienta: null, // null: cursor
  simbolo: null, // instrumento de `lista`
  lista: [], // dibujos del instrumento: {id, tipo, puntos: [{t, precio}]}
  seleccionado: null, // id
  enCurso: null, // dibujo a medio hacer; su último punto sigue al ratón
  arrastre: null, // {id, control, inicio, originales}
  creacion: null, // {x, y} del primer clic, para dibujar también arrastrando
};

const zonaGrafico = document.getElementById("grafico");

// --- Guardado (RF-5, RF-6) ---

const PREFIJO_DIBUJOS = "dibujos.";

function cargarDibujos() {
  dibujo.simbolo = estado.simbolo;
  dibujo.lista = preferencias.leer(PREFIJO_DIBUJOS + estado.simbolo, []);
  dibujo.seleccionado = null;
  dibujo.enCurso = null;
  dibujo.arrastre = null;
  repintarDibujos();
}

function guardarDibujos() {
  preferencias.guardar(PREFIJO_DIBUJOS + dibujo.simbolo, dibujo.lista);
}

// Al empezar un replay nuevo: un nivel dibujado en otra fecha puede delatar lo que pasó después.
function borrarTodosLosDibujos() {
  try {
    for (const clave of Object.keys(localStorage)) {
      if (clave.startsWith(`trading-replay.${PREFIJO_DIBUJOS}`)) localStorage.removeItem(clave);
    }
  } catch {
    // sin almacenamiento: solo queda la lista en memoria
  }
  cargarDibujos();
}

// --- Coordenadas ---

function aPixeles({ t, precio }) {
  const logico = tiempoALogico(estado.velas, t, estado.tf);
  if (logico === null) return null;
  const x = grafico.timeScale().logicalToCoordinate(logico);
  const y = serie.priceToCoordinate(precio);
  return x === null || y === null ? null : { x, y };
}

function desdePixeles(x, y) {
  const logico = grafico.timeScale().coordinateToLogical(x);
  const precio = serie.coordinateToPrice(y);
  if (logico === null || precio === null) return null;
  return { t: logicoATiempo(estado.velas, logico, estado.tf), precio: Math.round(precio * 100) / 100 };
}

// Posición del ratón dentro del panel de precio, o null si está fuera (ejes, otros paneles).
function posicionRaton(evento, dentro = true) {
  const caja = zonaGrafico.getBoundingClientRect();
  const x = evento.clientX - caja.left;
  const y = evento.clientY - caja.top;
  const panel = grafico.paneSize(0);
  if (dentro && (x < 0 || y < 0 || x > panel.width || y > panel.height)) return null;
  return { x, y };
}

// Puntos de control: [índice del punto que da el tiempo, índice del que da el precio].
// El rectángulo tiene las cuatro esquinas a partir de sus dos puntos opuestos.
function controles(figura) {
  if (figura.tipo === "rectangulo") return [[0, 0], [1, 0], [0, 1], [1, 1]];
  return figura.puntos.map((_, i) => [i, i]);
}

// Geometría en píxeles de un dibujo, o null si no se puede situar (gráfico vacío).
function geometria(figura) {
  const pixeles = figura.puntos.map(aPixeles);
  if (pixeles.some((p) => p === null)) return null;
  const asas = controles(figura).map(([it, ip]) => ({ x: pixeles[it].x, y: pixeles[ip].y }));
  return { pixeles, asas };
}

// --- Primitiva: pinta los dibujos y pone el precio de las horizontales en el eje ---

class PrimitivaDibujos {
  constructor() {
    this.figuras = []; // [{figura, geo}] calculadas en updateAllViews, antes de pintar
    this.vista = { renderer: () => ({ draw: (destino) => this.pintar(destino) }), zOrder: () => "top" };
  }

  attached({ requestUpdate }) {
    this.pedirRepintado = requestUpdate;
  }

  detached() {
    this.pedirRepintado = null;
  }

  updateAllViews() {
    const todas = dibujo.enCurso ? [...dibujo.lista, dibujo.enCurso] : dibujo.lista;
    this.figuras = todas.map((figura) => ({ figura, geo: geometria(figura) })).filter((f) => f.geo);
  }

  paneViews() {
    return [this.vista];
  }

  priceAxisViews() {
    return this.figuras
      .filter(({ figura }) => figura.tipo === "horizontal")
      .map(({ figura, geo }) => ({
        coordinate: () => geo.pixeles[0].y,
        text: () => figura.puntos[0].precio.toFixed(2),
        textColor: () => "#ffffff",
        backColor: () => color("--dibujo"),
        visible: () => true,
        tickVisible: () => true,
      }));
  }

  pintar(destino) {
    destino.useMediaCoordinateSpace(({ context: ctx, mediaSize }) => {
      const tinta = color("--dibujo");
      for (const { figura, geo } of this.figuras) {
        const [a, b] = geo.pixeles;
        const elegido = figura.id === dibujo.seleccionado || figura === dibujo.enCurso;
        ctx.strokeStyle = tinta;
        ctx.lineWidth = elegido ? 2 : 1.5;
        ctx.beginPath();
        if (figura.tipo === "fibonacci") {
          pintarFibonacci(
            ctx,
            mediaSize.width,
            { ...a, precio: figura.puntos[0].precio },
            { ...b, precio: figura.puntos[1].precio },
            configFibonacci(),
            { tinta, texto: color("--texto"), grosor: elegido ? 1.5 : 1, xFin: configFibonacci().extender ? undefined : Math.max(a.x, b.x) },
          );
        } else if (figura.tipo === "horizontal") {
          ctx.moveTo(0, a.y);
          ctx.lineTo(mediaSize.width, a.y);
        } else if (figura.tipo === "tendencia") {
          ctx.moveTo(a.x, a.y);
          ctx.lineTo(b.x, b.y);
        } else {
          ctx.rect(Math.min(a.x, b.x), Math.min(a.y, b.y), Math.abs(b.x - a.x), Math.abs(b.y - a.y));
          ctx.fillStyle = color("--dibujo-relleno");
          ctx.fill();
        }
        if (figura.tipo !== "fibonacci") ctx.stroke();
        ctx.lineWidth = 1.5;
        if (elegido) {
          for (const asa of geo.asas) {
            ctx.beginPath();
            ctx.arc(asa.x, asa.y, 4, 0, 2 * Math.PI);
            ctx.fillStyle = color("--fondo");
            ctx.fill();
            ctx.lineWidth = 1.5;
            ctx.stroke();
          }
        }
      }
    });
  }
}

const primitivaDibujos = new PrimitivaDibujos();
serie.attachPrimitive(primitivaDibujos);

function repintarDibujos() {
  primitivaDibujos.pedirRepintado?.();
  actualizarBarraDibujo();
}

// --- Acertar con el ratón ---

function distanciaASegmento(p, a, b) {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const largo = dx * dx + dy * dy;
  const f = largo ? Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / largo)) : 0;
  return Math.hypot(p.x - (a.x + f * dx), p.y - (a.y + f * dy));
}

function tocaFigura(figura, geo, p) {
  const [a, b] = geo.pixeles;
  if (figura.tipo === "horizontal") return Math.abs(p.y - a.y) <= TOLERANCIA;
  if (figura.tipo === "tendencia") return distanciaASegmento(p, a, b) <= TOLERANCIA;
  if (figura.tipo === "fibonacci") {
    // Se acierta en la diagonal o en cualquiera de sus líneas, de la figura hacia la derecha.
    if (distanciaASegmento(p, a, b) <= TOLERANCIA) return true;
    if (p.x < Math.min(a.x, b.x) - TOLERANCIA) return false;
    const config = configFibonacci();
    const alturas = [
      ...config.retrocesos.map((r) => a.y + (b.y - a.y) * (1 - r)),
      ...(config.conExtensiones ? config.extensiones.map((e) => a.y + (b.y - a.y) * e) : []),
    ];
    return alturas.some((y) => Math.abs(p.y - y) <= TOLERANCIA);
  }
  return (
    p.x >= Math.min(a.x, b.x) - TOLERANCIA &&
    p.x <= Math.max(a.x, b.x) + TOLERANCIA &&
    p.y >= Math.min(a.y, b.y) - TOLERANCIA &&
    p.y <= Math.max(a.y, b.y) + TOLERANCIA
  );
}

// {figura, control} bajo el punto `p`: primero las asas del seleccionado, luego el de más arriba.
function buscarDibujo(p) {
  const seleccionado = dibujo.lista.find((f) => f.id === dibujo.seleccionado);
  const geoSeleccionado = seleccionado && geometria(seleccionado);
  if (geoSeleccionado) {
    const control = geoSeleccionado.asas.findIndex((asa) => Math.hypot(asa.x - p.x, asa.y - p.y) <= TOLERANCIA);
    if (control >= 0) return { figura: seleccionado, control };
  }
  for (let i = dibujo.lista.length - 1; i >= 0; i--) {
    const figura = dibujo.lista[i];
    const geo = geometria(figura);
    if (geo && tocaFigura(figura, geo, p)) return { figura, control: null };
  }
  return null;
}

// --- Ratón ---
// Se escucha en captura: cuando el clic es para dibujar o mover un dibujo, se corta aquí y el
// gráfico no lo recibe (no se desplaza).

function cortar(evento) {
  evento.stopPropagation();
  evento.preventDefault();
}

function alPulsar(evento) {
  if (evento.button !== 0 || evento.target.closest?.("#panel-fibonacci")) return;
  const p = posicionRaton(evento);
  if (!p) return;
  if (dibujo.herramienta) {
    cortar(evento);
    ponerPunto(p);
    return;
  }
  const acierto = buscarDibujo(p);
  if (!acierto) {
    if (dibujo.seleccionado) seleccionar(null);
    return;
  }
  cortar(evento);
  seleccionar(acierto.figura.id);
  dibujo.arrastre = {
    id: acierto.figura.id,
    control: acierto.control,
    inicio: { logico: grafico.timeScale().coordinateToLogical(p.x), precio: serie.coordinateToPrice(p.y) },
    originales: structuredClone(acierto.figura.puntos),
  };
}

function ponerPunto(p) {
  const punto = desdePixeles(p.x, p.y);
  if (!punto) return;
  if (dibujo.enCurso) {
    dibujo.enCurso.puntos[dibujo.enCurso.puntos.length - 1] = punto;
    terminarDibujo();
    return;
  }
  dibujo.enCurso = { id: crypto.randomUUID(), tipo: dibujo.herramienta, puntos: [punto] };
  if (PUNTOS_POR_TIPO[dibujo.herramienta] === 1) {
    terminarDibujo();
    return;
  }
  dibujo.enCurso.puntos.push({ ...punto }); // el segundo punto sigue al ratón
  dibujo.creacion = p;
  repintarDibujos();
}

function terminarDibujo() {
  const figura = dibujo.enCurso;
  dibujo.enCurso = null;
  dibujo.creacion = null;
  dibujo.lista.push(figura);
  guardarDibujos();
  elegirHerramienta(null);
  seleccionar(figura.id);
}

function alMover(evento) {
  if (dibujo.enCurso) {
    const p = posicionRaton(evento, false);
    const punto = desdePixeles(p.x, Math.min(p.y, grafico.paneSize(0).height));
    if (punto) dibujo.enCurso.puntos[dibujo.enCurso.puntos.length - 1] = punto;
    repintarDibujos();
    return;
  }
  if (dibujo.arrastre) {
    arrastrar(posicionRaton(evento, false));
    return;
  }
  const p = posicionRaton(evento);
  zonaGrafico.classList.toggle("sobre-dibujo", Boolean(p && !dibujo.herramienta && buscarDibujo(p)));
}

function arrastrar(p) {
  const { id, control, inicio, originales } = dibujo.arrastre;
  const figura = dibujo.lista.find((f) => f.id === id);
  if (!figura) return;
  if (control !== null) {
    const punto = desdePixeles(p.x, p.y);
    if (!punto) return;
    const [it, ip] = controles(figura)[control];
    figura.puntos[it].t = punto.t;
    figura.puntos[ip].precio = punto.precio;
  } else {
    // Se mueve el dibujo entero: el mismo número de velas y el mismo precio para todos los puntos.
    const logico = grafico.timeScale().coordinateToLogical(p.x);
    const precio = serie.coordinateToPrice(p.y);
    if (logico === null || precio === null || inicio.logico === null) return;
    const velas = Math.round(logico - inicio.logico);
    figura.puntos = originales.map((o) => ({
      t: logicoATiempo(estado.velas, tiempoALogico(estado.velas, o.t, estado.tf) + velas, estado.tf),
      precio: Math.round((o.precio + precio - inicio.precio) * 100) / 100,
    }));
  }
  repintarDibujos();
}

function alSoltar(evento) {
  if (dibujo.arrastre) {
    dibujo.arrastre = null;
    guardarDibujos();
    return;
  }
  // Dibujar arrastrando: si se suelta lejos del primer clic, ese es el segundo punto.
  const { creacion, enCurso } = dibujo;
  if (enCurso && creacion && enCurso.puntos.length > 1) {
    const p = posicionRaton(evento, false);
    if (Math.hypot(p.x - creacion.x, p.y - creacion.y) > TOLERANCIA) terminarDibujo();
    else dibujo.creacion = null; // fue un clic: el segundo punto llegará con otro clic
  }
}

zonaGrafico.addEventListener("mousedown", alPulsar, true);
window.addEventListener("mousemove", alMover, true);
window.addEventListener("mouseup", alSoltar, true);

// --- Herramientas, selección y teclado ---

function elegirHerramienta(herramienta) {
  dibujo.herramienta = herramienta;
  dibujo.enCurso = null;
  dibujo.creacion = null;
  if (herramienta) dibujo.seleccionado = null;
  zonaGrafico.classList.toggle("dibujando", Boolean(herramienta));
  repintarDibujos();
}

function seleccionar(id) {
  dibujo.seleccionado = id;
  repintarDibujos();
}

function borrarSeleccionado() {
  if (!dibujo.seleccionado) return;
  dibujo.lista = dibujo.lista.filter((f) => f.id !== dibujo.seleccionado);
  dibujo.seleccionado = null;
  guardarDibujos();
  repintarDibujos();
}

function borrarDibujosDelInstrumento() {
  dibujo.lista = [];
  dibujo.seleccionado = null;
  guardarDibujos();
  repintarDibujos();
}

function actualizarBarraDibujo() {
  for (const boton of document.querySelectorAll("#herramientas [data-herramienta]")) {
    boton.setAttribute("aria-pressed", String((boton.dataset.herramienta || null) === dibujo.herramienta));
  }
  document.getElementById("borrar-dibujo").disabled = !dibujo.seleccionado;
  document.getElementById("borrar-dibujos").disabled = !dibujo.lista.length;
  mostrarPanelFibonacci();
}

// --- Panel de configuración de Fibonacci (RF-22): la config es global, no de cada figura ---

let panelFibonacci = null;

function guardarConfigFibonacci(config) {
  preferencias.guardar("fibonacci.config", config);
  repintarDibujos();
}

function mostrarPanelFibonacci() {
  const figura = dibujo.lista.find((f) => f.id === dibujo.seleccionado);
  const visible = figura?.tipo === "fibonacci";
  if (!visible) {
    if (panelFibonacci) panelFibonacci.hidden = true;
    return;
  }
  if (!panelFibonacci) {
    panelFibonacci = document.createElement("div");
    panelFibonacci.id = "panel-fibonacci";
    panelFibonacci.className = "panel-fibonacci";
    zonaGrafico.appendChild(panelFibonacci);
  }
  // Solo se reconstruye al seleccionar otra figura o al cambiar la configuración (reconstruirPanelFibonacci).
  if (panelFibonacci.hidden || panelFibonacci.dataset.figura !== figura.id) {
    panelFibonacci.dataset.figura = figura.id;
    panelFibonacci.hidden = false;
    reconstruirPanelFibonacci();
  }
}

function reconstruirPanelFibonacci() {
  const config = configFibonacci();
  const panel = panelFibonacci;
  panel.replaceChildren();
  const casilla = (texto, marcada, alCambiar) => {
    const etiqueta = document.createElement("label");
    const caja = document.createElement("input");
    caja.type = "checkbox";
    caja.checked = marcada;
    caja.addEventListener("change", () => alCambiar(caja.checked));
    etiqueta.append(caja, ` ${texto}`);
    panel.appendChild(etiqueta);
  };
  const alternar = (lista, valor, activo) => (activo ? [...new Set([...lista, valor])] : lista.filter((v) => v !== valor));
  const cambiar = (cambios) => {
    guardarConfigFibonacci({ ...configFibonacci(), ...cambios });
    reconstruirPanelFibonacci();
  };
  const retrocesos = [...new Set([...FIB_RETROCESOS, ...config.propios])].sort((a, b) => a - b);
  for (const valor of retrocesos) {
    casilla(`${Math.round(valor * 1000) / 10}%`, config.retrocesos.includes(valor), (on) =>
      cambiar({ retrocesos: alternar(config.retrocesos, valor, on) }));
  }
  casilla("Extensiones", config.conExtensiones, (on) => cambiar({ conExtensiones: on }));
  if (config.conExtensiones) {
    for (const valor of FIB_EXTENSIONES) {
      casilla(`${Math.round(valor * 1000) / 10}%`, config.extensiones.includes(valor), (on) =>
        cambiar({ extensiones: alternar(config.extensiones, valor, on) }));
    }
  }
  casilla("Extender a la derecha", config.extender, (on) => cambiar({ extender: on }));
  casilla("Precio", config.precio, (on) => cambiar({ precio: on }));
  casilla("Porcentaje", config.porcentaje, (on) => cambiar({ porcentaje: on }));
  const propio = document.createElement("input");
  propio.type = "number";
  propio.step = "any";
  propio.placeholder = "Nivel propio (%)";
  propio.addEventListener("keydown", (evento) => {
    if (evento.key !== "Enter") return;
    const valor = Math.round(parseFloat(propio.value) * 10) / 1000; // % -> fracción, sin ruido de coma flotante
    if (Number.isNaN(valor)) return;
    cambiar({ propios: alternar(config.propios, valor, true), retrocesos: alternar(config.retrocesos, valor, true) });
  });
  panel.appendChild(propio);
}

function atajoDibujo(evento) {
  if (hayVentana()) return;
  if (evento.ctrlKey || evento.metaKey || evento.altKey || esCampo(evento.target)) return;
  const herramienta = ATAJOS_DIBUJO[evento.key.toLowerCase()];
  if (herramienta) {
    evento.preventDefault();
    elegirHerramienta(dibujo.herramienta === herramienta ? null : herramienta);
  } else if ((evento.key === "Delete" || evento.key === "Backspace") && dibujo.seleccionado) {
    evento.preventDefault();
    borrarSeleccionado();
  }
}

function prepararDibujo() {
  for (const boton of document.querySelectorAll("#herramientas [data-herramienta]")) {
    boton.addEventListener("click", () => elegirHerramienta(boton.dataset.herramienta || null));
  }
  document.getElementById("borrar-dibujo").addEventListener("click", borrarSeleccionado);
  // Borrar todo pide un segundo clic, para no perder los dibujos por un despiste.
  const borrarTodo = document.getElementById("borrar-dibujos");
  let confirmar = null;
  borrarTodo.addEventListener("click", () => {
    if (confirmar) {
      clearTimeout(confirmar);
      confirmar = null;
      borrarTodo.classList.remove("confirmar");
      borrarDibujosDelInstrumento();
      return;
    }
    borrarTodo.classList.add("confirmar");
    confirmar = setTimeout(() => {
      confirmar = null;
      borrarTodo.classList.remove("confirmar");
    }, 3000);
  });
  document.addEventListener("keydown", atajoDibujo);
  cancelaciones.push(() => {
    if (dibujo.herramienta || dibujo.enCurso) {
      elegirHerramienta(null);
      return true;
    }
    if (dibujo.seleccionado) {
      seleccionar(null);
      return true;
    }
    return false;
  });
  // Al cambiar de instrumento se ven los dibujos del nuevo; al cambiar de timeframe, los mismos.
  alRecargar.push(() => {
    if (dibujo.simbolo !== estado.simbolo) cargarDibujos();
    else elegirHerramienta(dibujo.herramienta);
  });
  cargarDibujos();
}
