// Operar (spec 005): boleta, cuenta, posiciones, órdenes e historial, y en el gráfico las líneas de
// la posición y de las órdenes (las de órdenes se arrastran para cambiar el precio) y las marcas de
// las ejecuciones. El motor de órdenes vive en el backend: aquí solo se envía y se enseña su estado.

const CONTRATOS_DE = { NQ: ["NQ", "MNQ"], ES: ["ES", "MES"], GC: ["GC", "MGC"] };
const TICK = { NQ: 0.25, ES: 0.25, GC: 0.1 };
const MULTIPLICADOR = { NQ: 20, MNQ: 2, ES: 50, MES: 5, GC: 100, MGC: 10 }; // $ por punto
const LADOS = [
  ["compra", "Compra"],
  ["venta", "Venta"],
];
const UNIDADES = [
  ["puntos", "Puntos"],
  ["dolares", "$"],
];
const TIPOS_ORDEN = [
  ["mercado", "Mercado"],
  ["limite", "Límite"],
  ["stop", "Stop"],
];
const NOMBRE_PAPEL = { entrada: "", sl: "SL", tp: "TP", cierre: "Cierre" };
const MS_CONFIRMAR = 6000;

const operativa = {
  cuenta: null, // resumen que manda el backend
  ejecuciones: [], // de la sesión de replay actual, para las marcas
  micro: preferencias.leer("micro", false),
  lado: preferencias.leer("boleta", {}).lado ?? "compra",
  unidad: preferencias.leer("boleta", {}).unidad ?? "puntos", // del SL y el TP (RF-23)
  tipo: "mercado",
  // Vista previa (RF-24): mientras se prepara la orden, hasta que se envía.
  sobreBoleta: false,
  focoEnBoleta: false,
  recienEnviada: false,
  lineas: new Map(), // id → línea de precio del gráfico
  arrastre: null, // {id, linea, precio}
  confirmar: null, // {accion, hasta}: segundo clic para saltar o salir con algo abierto
};

const marcasEjecuciones = LightweightCharts.createSeriesMarkers(serie, []);

// --- Formatos ---

const formatoDinero = (x) => {
  const texto = Math.abs(x).toLocaleString("es", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${x < 0 ? "−" : x > 0 ? "+" : ""}${texto} $`;
};
const formatoSaldo = (x) => `${x.toLocaleString("es", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} $`;
const tono = (x) => (x > 0 ? "positivo" : x < 0 ? "negativo" : "");
const redondearTick = (precio, simbolo) => {
  const tick = TICK[simbolo];
  return Math.round(Math.round(precio / tick) * tick * 100) / 100;
};

// --- API ---

function pedir(ruta, metodo = "GET", cuerpo) {
  const opciones = { method: metodo };
  if (cuerpo !== undefined) {
    opciones.headers = { "Content-Type": "application/json" };
    opciones.body = JSON.stringify(cuerpo);
  }
  // En fila con el avance del reloj: una orden nunca se cruza con un avance a medias.
  return enSerie(() => api(ruta, opciones));
}

async function accionCuenta(ruta, metodo, cuerpo) {
  try {
    const datos = await pedir(ruta, metodo, cuerpo);
    actualizarCuenta(datos.cuenta, datos.ejecuciones);
    return datos;
  } catch (error) {
    mostrarAviso(error.message);
    return null;
  }
}

async function refrescarCuenta() {
  try {
    const [cuenta, ejecuciones] = await Promise.all([api("/api/cuenta"), api("/api/ejecuciones")]);
    operativa.ejecuciones = ejecuciones;
    actualizarCuenta(cuenta);
    pintarMarcas();
    mostrarHistorial();
  } catch (error) {
    mostrarAviso(error.message);
  }
}

// Llega con cada avance del reloj y con cada acción sobre la cuenta.
function actualizarCuenta(cuenta, ejecuciones = []) {
  if (cuenta) operativa.cuenta = cuenta;
  if (ejecuciones.length) {
    operativa.ejecuciones.push(...ejecuciones);
    pintarMarcas();
    mostrarHistorial();
  }
  mostrarCuenta();
  pintarLineas();
  mostrarReto(); // retos.js (spec 006)
  atenderEventos(cuenta?.eventos);
}

const hayExposicion = () => Boolean(operativa.cuenta && (operativa.cuenta.posiciones.length || operativa.cuenta.ordenes.length));

// Al saltar o salir con posiciones u órdenes abiertas, se cierran (RF-17): se pide un segundo clic.
function confirmarSalto(accion) {
  if (!hayExposicion()) return true;
  const { confirmar } = operativa;
  if (confirmar && confirmar.accion === accion && performance.now() < confirmar.hasta) {
    operativa.confirmar = null;
    return true;
  }
  operativa.confirmar = { accion, hasta: performance.now() + MS_CONFIRMAR };
  mostrarAviso("Hay posiciones u órdenes abiertas y se cerrarán al precio actual. Repite para confirmar.");
  return false;
}

// Tras saltar o salir: avisa de lo que se cerró y empieza la lista de ejecuciones de la sesión nueva.
function trasSalto(datos) {
  operativa.ejecuciones = [];
  pintarMarcas();
  const cerradas = datos?.liquidadas?.length ?? 0;
  if (cerradas) mostrarAviso(`Se ${cerradas === 1 ? "cerró 1 posición" : `cerraron ${cerradas} posiciones`} al saltar`);
  refrescarCuenta();
}

// --- Boleta ---

function contratoElegido() {
  const [mini, micro] = CONTRATOS_DE[estado.simbolo];
  return operativa.micro ? micro : mini;
}

function numeroDe(id) {
  const valor = $(id).value.trim().replace(",", ".");
  return valor === "" ? null : Number(valor);
}

const cantidadElegida = () => Math.max(1, Math.round(numeroDe("cantidad") ?? 1));

function especificacion(cantidad = cantidadElegida()) {
  const contrato = contratoElegido();
  return { multiplicador: MULTIPLICADOR[contrato], tick: TICK[estado.simbolo], cantidad };
}

// Distancia en puntos del SL o el TP escritos en la boleta, o null si no hay (RF-23).
function distancia(campo) {
  const valor = numeroDe(campo);
  if (!(valor > 0)) return null;
  const spec = especificacion();
  if (operativa.unidad === "dolares") return puntosDesdeDolares(valor, spec, campo === "tp");
  return Math.max(redondearTick(valor, estado.simbolo), spec.tick);
}

function guardarBoleta() {
  const { lado, unidad } = operativa;
  preferencias.guardar("boleta", { lado, unidad, cantidad: cantidadElegida(), sl: $("sl").value, tp: $("tp").value });
}

// En modo simulado el backend ya ha pasado el minuto que se está dibujando, y una orden a mercado se
// ejecuta a su cierre real (RF-16). Se completa la vela para que el gráfico enseñe ese precio.
function completarMinutoSimulado() {
  if (replay.animacion) terminarAnimacion(); // replay.js
}

async function enviarOrden() {
  if (operativa.tipo === "mercado") completarMinutoSimulado();
  const cuerpo = { contrato: contratoElegido(), lado: operativa.lado, tipo: operativa.tipo, cantidad: cantidadElegida() };
  if (operativa.tipo !== "mercado") cuerpo.precio = numeroDe("precio");
  const sl = distancia("sl");
  const tp = distancia("tp");
  if (sl) cuerpo.sl_puntos = sl;
  if (tp) cuerpo.tp_puntos = tp;
  guardarBoleta();
  const datos = await accionCuenta("/api/ordenes", "POST", cuerpo);
  if (!datos) return;
  mostrarAviso();
  operativa.recienEnviada = true; // la vista previa se apaga hasta que se vuelva a tocar la boleta
  actualizarPrevia();
}

function proponerPrecio() {
  const ultima = estado.velas.at(-1);
  if (ultima && operativa.tipo !== "mercado") $("precio").value = redondearTick(ultima.close, estado.simbolo);
}

function segmentado(contenedor, opciones, elegido, alElegir) {
  contenedor.replaceChildren();
  for (const [valor, texto, titulo] of opciones) {
    const boton = document.createElement("button");
    boton.type = "button";
    boton.textContent = texto;
    if (titulo) boton.title = titulo;
    boton.dataset.valor = valor;
    boton.setAttribute("aria-pressed", String(valor === elegido));
    boton.addEventListener("click", () => alElegir(valor));
    contenedor.append(boton);
  }
}

function mostrarBoleta() {
  const elegir = (cambio) => (valor) => {
    cambio(valor);
    guardarBoleta();
    mostrarBoleta();
  };
  segmentado($("lados"), LADOS, operativa.lado, elegir((v) => (operativa.lado = v)));
  segmentado(
    $("contratos"),
    CONTRATOS_DE[estado.simbolo].map((c, i) => [c, c, i ? "Micro" : "Mini"]),
    contratoElegido(),
    elegir((v) => {
      operativa.micro = v !== CONTRATOS_DE[estado.simbolo][0];
      preferencias.guardar("micro", operativa.micro);
    }),
  );
  segmentado(
    $("tipos"),
    TIPOS_ORDEN,
    operativa.tipo,
    elegir((v) => {
      operativa.tipo = v;
      proponerPrecio();
    }),
  );
  segmentado($("unidades"), UNIDADES, operativa.unidad, (v) => cambiarUnidad(v));
  $("lados").dataset.lado = operativa.lado;
  $("precio").disabled = operativa.tipo === "mercado";
  $("precio").step = TICK[estado.simbolo];
  if (operativa.tipo === "mercado") $("precio").value = "";
  for (const campo of ["sl", "tp"]) $(campo).step = operativa.unidad === "dolares" ? "any" : TICK[estado.simbolo];
  actualizarPrevia();
}

// Al cambiar de unidad, se convierten los valores para que el SL y el TP sigan en el mismo sitio.
function cambiarUnidad(unidad) {
  if (unidad === operativa.unidad) return;
  for (const campo of ["sl", "tp"]) {
    const puntos = distancia(campo);
    if (puntos === null) continue;
    const valor = unidad === "dolares" ? dolaresDesdePuntos(puntos, especificacion()) : puntos;
    $(campo).value = String(valor);
  }
  operativa.unidad = unidad;
  guardarBoleta();
  mostrarBoleta();
}

// Equivalencia en la otra unidad bajo el SL y el TP, y resumen en el botón de confirmar.
function mostrarResumenBoleta() {
  const spec = especificacion();
  for (const campo of ["sl", "tp"]) {
    const puntos = distancia(campo);
    let texto = "";
    if (puntos !== null) {
      const dolares = formatoSaldo(dolaresDesdePuntos(puntos, spec));
      texto = operativa.unidad === "dolares" ? `= ${puntos.toLocaleString("es")} pts (${dolares})` : `= ${dolares}`;
    }
    $(`${campo}-equivale`).textContent = texto;
  }
  const verbo = operativa.lado === "compra" ? "Comprar" : "Vender";
  const precio = numeroDe("precio");
  const tipo = operativa.tipo === "mercado" ? "a mercado" : `${operativa.tipo === "limite" ? "límite" : "stop"}${precio ? ` ${precio.toFixed(2)}` : ""}`;
  const boton = $("confirmar");
  boton.textContent = `${verbo} ${cantidadElegida()} ${contratoElegido()} ${tipo}`;
  boton.className = `confirmar ${operativa.lado === "compra" ? "comprar" : "vender"}`;
}

// --- Vista previa del SL y el TP (RF-24) ---

const previaVisible = () => replay.activo && (operativa.sobreBoleta || operativa.focoEnBoleta) && !operativa.recienEnviada;

// Precio de entrada previsto: el escrito en límite y stop; en mercado, el que se ve ahora mismo
// (la vela provisional del movimiento simulado, si la hay), al ASK si compra y al BID si vende.
function entradaPrevista() {
  const simbolo = estado.simbolo;
  if (operativa.tipo !== "mercado") {
    const precio = numeroDe("precio");
    return precio > 0 ? redondearTick(precio, simbolo) : null;
  }
  const actual = indicadores.provisional?.vela.close ?? estado.velas.at(-1)?.close;
  if (actual == null) return null;
  const bid = redondearTick(actual, simbolo);
  const spread = (operativa.cuenta?.costes.spread_ticks ?? 1) * TICK[simbolo];
  return operativa.lado === "compra" ? Math.round((bid + spread) * 100) / 100 : bid;
}

// {entrada, sl, tp, importeSl, importeTp} de la orden que se está preparando, o null.
function previa() {
  if (!previaVisible()) return null;
  const entrada = entradaPrevista();
  if (entrada === null) return null;
  const sentido = operativa.lado === "compra" ? 1 : -1;
  const spec = especificacion();
  const resultado = { entrada };
  for (const [campo, signo] of [
    ["sl", -1],
    ["tp", 1],
  ]) {
    const puntos = distancia(campo);
    if (puntos === null) continue;
    resultado[campo] = Math.round((entrada + signo * sentido * puntos) * 100) / 100;
    resultado[`importe_${campo}`] = signo * dolaresDesdePuntos(puntos, spec);
  }
  return resultado;
}

// Se llama al tocar la boleta y con cada cambio de precio (avance del reloj y movimiento simulado).
function actualizarPrevia() {
  mostrarResumenBoleta();
  pintarLineas();
}

// --- Cuenta, posiciones, órdenes e historial ---

function mostrarCuenta() {
  const cuenta = operativa.cuenta;
  if (!cuenta) return;
  $("balance").textContent = formatoSaldo(cuenta.balance);
  // El selector de cuentas también enseña el balance: se mantiene al día al operar.
  const opcion = [...$("cuenta-activa").options].find((o) => Number(o.value) === cuenta.id);
  if (opcion) opcion.text = `${cuenta.nombre} · ${formatoSaldo(cuenta.balance)}`;
  for (const [id, valor] of [
    ["pnl-abierto", cuenta.pnl_abierto],
    ["pnl-sesion", cuenta.pnl_sesion],
  ]) {
    $(id).textContent = formatoDinero(valor);
    $(id).className = tono(valor);
  }

  const posiciones = $("posiciones");
  posiciones.replaceChildren();
  for (const p of cuenta.posiciones) {
    const fila = filaLista(
      `${p.cantidad > 0 ? "Largo" : "Corto"} ${Math.abs(p.cantidad)} ${p.contrato} @ ${p.precio_medio.toFixed(2)}`,
      [formatoDinero(p.pnl), tono(p.pnl)],
    );
    const cerrar = () => {
      completarMinutoSimulado();
      accionCuenta(`/api/posiciones/${p.contrato}/cerrar`, "POST");
    };
    fila.append(botonLista("Cerrar", `Cerrar la posición de ${p.contrato} a mercado`, cerrar));
    posiciones.append(fila);
  }
  if (!cuenta.posiciones.length) posiciones.append(filaVacia("Sin posiciones"));

  const ordenes = $("ordenes");
  ordenes.replaceChildren();
  for (const o of cuenta.ordenes) {
    const fila = filaLista(textoOrden(o));
    fila.append(botonLista("×", "Cancelar la orden", () => accionCuenta(`/api/ordenes/${o.id}`, "DELETE")));
    ordenes.append(fila);
  }
  if (!cuenta.ordenes.length) ordenes.append(filaVacia("Sin órdenes pendientes"));
  $("cerrar-todo").disabled = !hayExposicion();
}

function textoOrden(o) {
  const papel = NOMBRE_PAPEL[o.papel];
  const tipo = { mercado: "a mercado", limite: "límite", stop: "stop" }[o.tipo];
  const precio = o.precio == null ? "" : ` ${o.precio.toFixed(2)}`;
  return `${papel ? `${papel} · ` : ""}${o.lado === "compra" ? "Compra" : "Venta"} ${o.cantidad} ${o.contrato} ${tipo}${precio}`;
}

function filaLista(texto, [extra, clase] = []) {
  const fila = document.createElement("li");
  const principal = document.createElement("span");
  principal.textContent = texto;
  fila.append(principal);
  if (extra !== undefined) {
    const cifra = document.createElement("span");
    cifra.className = `cifra ${clase ?? ""}`;
    cifra.textContent = extra;
    fila.append(cifra);
  }
  return fila;
}

function filaVacia(texto) {
  const fila = document.createElement("li");
  fila.className = "vacia";
  fila.textContent = texto;
  return fila;
}

function botonLista(texto, titulo, accion) {
  const boton = document.createElement("button");
  boton.type = "button";
  boton.textContent = texto;
  boton.title = titulo;
  boton.addEventListener("click", accion);
  return boton;
}

async function mostrarHistorial() {
  let operaciones;
  try {
    operaciones = await api("/api/operaciones?limite=15");
  } catch {
    return;
  }
  const lista = $("historial");
  lista.replaceChildren();
  for (const o of operaciones) {
    // Modo a ciegas: textoMomento enseña solo el día de la semana y la hora (RF-21).
    const cuando = textoMomento(aSegundos(o.apertura));
    const texto = `${cuando} · ${o.lado === "compra" ? "Largo" : "Corto"} ${o.cantidad} ${o.contrato}`;
    const fila = filaLista(texto, [formatoDinero(o.pnl_neto), tono(o.pnl_neto)]);
    fila.title = `Entrada ${o.entrada.toFixed(2)} · salida ${o.salida.toFixed(2)} · comisiones ${o.comisiones.toFixed(2)} $`;
    lista.append(fila);
  }
  if (!operaciones.length) lista.append(filaVacia("Todavía no hay operaciones cerradas"));
}

// --- Líneas en el gráfico (RF-19) ---

function lineasDeseadas() {
  const cuenta = operativa.cuenta;
  if (!cuenta || !replay.activo) return [];
  const lineas = [];
  for (const p of cuenta.posiciones) {
    if (p.simbolo !== estado.simbolo) continue;
    lineas.push({
      id: `posicion-${p.contrato}`,
      price: p.precio_medio,
      color: color("--texto"),
      lineStyle: LineStyle.Solid,
      title: `${p.cantidad > 0 ? "Largo" : "Corto"} ${Math.abs(p.cantidad)} ${p.contrato} · ${formatoDinero(p.pnl)}`,
    });
  }
  for (const o of cuenta.ordenes) {
    if (o.simbolo !== estado.simbolo || o.precio == null) continue;
    const colorOrden = o.papel === "sl" ? color("--rojo") : o.papel === "tp" ? color("--verde") : color("--ambar");
    lineas.push({ id: o.id, price: o.precio, color: colorOrden, lineStyle: LineStyle.Dashed, title: tituloOrden(o, o.precio), orden: true });
  }
  // Precio al que se cerraría todo en una cuenta de reto (spec 006, RF-16).
  const reto = cuenta.reto;
  const liquidacion = reto?.liquidacion?.[estado.simbolo];
  if (liquidacion !== undefined) {
    const regla = reto.regla === "limite_diario" ? "Límite diario" : "Pérdida máxima";
    lineas.push({ id: "liquidacion", price: liquidacion, color: color("--rojo"), lineStyle: LineStyle.LargeDashed, title: `${regla} · se cierra todo` });
  }
  const prevista = previa();
  if (prevista) {
    if (operativa.tipo !== "mercado") {
      lineas.push({ id: "previa-entrada", price: prevista.entrada, color: color("--ambar"), lineStyle: LineStyle.Dotted, title: "Entrada prevista" });
    }
    for (const [campo, nombre, tinta] of [
      ["sl", "SL", color("--rojo")],
      ["tp", "TP", color("--verde")],
    ]) {
      if (prevista[campo] === undefined) continue;
      const titulo = `${nombre} previsto · ${formatoDinero(prevista[`importe_${campo}`])}`;
      lineas.push({ id: `previa-${campo}`, price: prevista[campo], color: tinta, lineStyle: LineStyle.Dotted, title: titulo });
    }
  }
  return lineas;
}

// Posición del contrato de una orden, si la hay.
const posicionDe = (contrato) => operativa.cuenta?.posiciones.find((p) => p.contrato === contrato);

// Lo que se perdería o ganaría si se ejecutara un SL o un TP a `precio` (RF-22).
function importeOrden(o, precio) {
  const posicion = posicionDe(o.contrato);
  if (!posicion || (o.papel !== "sl" && o.papel !== "tp")) return null;
  const sentido = Math.sign(posicion.cantidad);
  return Math.round((precio - posicion.precio_medio) * MULTIPLICADOR[o.contrato] * o.cantidad * sentido * 100) / 100;
}

function tituloOrden(o, precio) {
  const nombre = NOMBRE_PAPEL[o.papel] || `${o.lado === "compra" ? "Compra" : "Venta"} ${o.tipo === "limite" ? "límite" : "stop"}`;
  const importe = importeOrden(o, precio);
  return `${nombre} ${o.cantidad}${importe === null ? "" : ` · ${formatoDinero(importe)}`}`;
}

function pintarLineas() {
  const deseadas = lineasDeseadas();
  const vistas = new Set();
  for (const d of deseadas) {
    vistas.add(d.id);
    // Mientras se arrastra, la línea sigue al ratón y no al precio guardado.
    const precio = operativa.arrastre?.id === d.id ? operativa.arrastre.precio : d.price;
    const opciones = { price: precio, color: d.color, lineStyle: d.lineStyle, title: d.title, lineWidth: 1, axisLabelVisible: true };
    const existente = operativa.lineas.get(d.id);
    if (existente) existente.linea.applyOptions(opciones);
    else operativa.lineas.set(d.id, { linea: serie.createPriceLine(opciones), orden: d.orden });
  }
  for (const [id, { linea }] of operativa.lineas) {
    if (!vistas.has(id)) {
      serie.removePriceLine(linea);
      operativa.lineas.delete(id);
    }
  }
  primitivaZonas.pedirRepintado?.();
}

// --- Zonas de SL y TP (RF-22) ---
// Rectángulos translúcidos entre la entrada y cada SL o TP, hasta el borde derecho del gráfico,
// como la herramienta de posición de TradingView. También para la vista previa.

function zonas() {
  const lista = [];
  const cuenta = operativa.cuenta;
  if (cuenta && replay.activo) {
    for (const o of cuenta.ordenes) {
      if (o.simbolo !== estado.simbolo || (o.papel !== "sl" && o.papel !== "tp")) continue;
      const posicion = posicionDe(o.contrato);
      if (!posicion) continue;
      const precio = operativa.arrastre?.id === o.id ? operativa.arrastre.precio : o.precio;
      lista.push({ desde: posicion.desde, de: posicion.precio_medio, a: precio, papel: o.papel });
    }
  }
  const prevista = previa();
  const ultima = estado.velas.at(-1);
  if (prevista && ultima) {
    for (const papel of ["sl", "tp"]) {
      if (prevista[papel] !== undefined) lista.push({ desde: ultima.time, de: prevista.entrada, a: prevista[papel], papel, previa: true });
    }
  }
  return lista;
}

class PrimitivaZonas {
  constructor() {
    this.rectangulos = [];
    // Por debajo de las velas, para que sigan viéndose encima de las zonas.
    this.vista = { renderer: () => ({ draw: (destino) => this.pintar(destino) }), zOrder: () => "bottom" };
  }

  attached({ requestUpdate }) {
    this.pedirRepintado = requestUpdate;
  }

  detached() {
    this.pedirRepintado = null;
  }

  updateAllViews() {
    const escala = grafico.timeScale();
    this.rectangulos = zonas()
      .map((z) => {
        const logico = z.desde == null ? null : tiempoALogico(estado.velas, z.desde, estado.tf);
        const x = logico === null ? 0 : escala.logicalToCoordinate(logico);
        const y1 = serie.priceToCoordinate(z.de);
        const y2 = serie.priceToCoordinate(z.a);
        return x === null || y1 === null || y2 === null ? null : { x, y1, y2, papel: z.papel, previa: z.previa };
      })
      .filter(Boolean);
  }

  paneViews() {
    return [this.vista];
  }

  pintar(destino) {
    destino.useMediaCoordinateSpace(({ context: ctx, mediaSize }) => {
      for (const r of this.rectangulos) {
        const variable = `--zona-${r.papel}${r.previa ? "-previa" : ""}`;
        ctx.fillStyle = color(variable);
        ctx.fillRect(r.x, Math.min(r.y1, r.y2), mediaSize.width - r.x, Math.abs(r.y2 - r.y1));
      }
    });
  }
}

const primitivaZonas = new PrimitivaZonas();
serie.attachPrimitive(primitivaZonas);

// --- Arrastrar órdenes ---
// Se escucha en `window` en fase de captura para adelantarse a los dibujos y al gráfico.

function ordenBajo(evento) {
  const caja = zonaGrafico.getBoundingClientRect();
  const x = evento.clientX - caja.left;
  const y = evento.clientY - caja.top;
  const panel = grafico.paneSize(0);
  if (x < 0 || y < 0 || x > panel.width || y > panel.height) return null;
  for (const [id, { linea, orden }] of operativa.lineas) {
    if (!orden) continue;
    const yLinea = serie.priceToCoordinate(linea.options().price);
    if (yLinea !== null && Math.abs(yLinea - y) <= TOLERANCIA) return { id, linea };
  }
  return null;
}

window.addEventListener(
  "mousedown",
  (evento) => {
    if (evento.button !== 0 || dibujo.herramienta) return;
    const objetivo = ordenBajo(evento);
    if (!objetivo) return;
    evento.stopPropagation();
    evento.preventDefault();
    operativa.arrastre = { ...objetivo, precio: objetivo.linea.options().price };
  },
  true,
);

window.addEventListener(
  "mousemove",
  (evento) => {
    if (!operativa.arrastre) {
      zonaGrafico.classList.toggle("sobre-orden", Boolean(!dibujo.herramienta && ordenBajo(evento)));
      return;
    }
    const caja = zonaGrafico.getBoundingClientRect();
    const precio = serie.coordinateToPrice(evento.clientY - caja.top);
    if (precio === null) return;
    const arrastre = operativa.arrastre;
    arrastre.precio = redondearTick(precio, estado.simbolo);
    // La etiqueta en dólares y la zona siguen al ratón (RF-22).
    const orden = operativa.cuenta?.ordenes.find((o) => o.id === arrastre.id);
    arrastre.linea.applyOptions({ price: arrastre.precio, ...(orden && { title: tituloOrden(orden, arrastre.precio) }) });
    primitivaZonas.pedirRepintado?.();
  },
  true,
);

window.addEventListener(
  "mouseup",
  async () => {
    const arrastre = operativa.arrastre;
    if (!arrastre) return;
    operativa.arrastre = null;
    const datos = await accionCuenta(`/api/ordenes/${arrastre.id}`, "PATCH", { precio: arrastre.precio });
    if (!datos) pintarLineas(); // rechazado: la línea vuelve a su precio
  },
  true,
);

// --- Marcas de las ejecuciones ---

function pintarMarcas() {
  const primera = estado.velas[0]?.time ?? Infinity;
  const marcas = operativa.ejecuciones
    .filter((e) => e.simbolo === estado.simbolo)
    .map((e) => {
      const compra = e.lado === "compra";
      const papel = NOMBRE_PAPEL[e.papel];
      return {
        time: cubeta(e.time, estado.tf),
        position: compra ? "belowBar" : "aboveBar",
        shape: compra ? "arrowUp" : "arrowDown",
        color: compra ? color("--verde") : color("--rojo"),
        text: `${papel ? `${papel} ` : ""}${compra ? "+" : "−"}${e.cantidad} @ ${e.precio.toFixed(2)}`,
      };
    })
    .filter((m) => m.time >= primera)
    .sort((a, b) => a.time - b.time);
  marcasEjecuciones.setMarkers(marcas);
}

// --- Cuentas y costes (RF-20) ---

async function mostrarCuentas() {
  let cuentas;
  try {
    cuentas = await api("/api/cuentas");
  } catch (error) {
    mostrarAviso(error.message);
    return;
  }
  const selector = $("cuenta-activa");
  selector.replaceChildren(...cuentas.map((c) => new Option(`${c.nombre} · ${formatoSaldo(c.balance)}`, c.id)));
  const activa = cuentas.find((c) => c.activa);
  if (!activa) return;
  selector.value = activa.id;
  $("nombre-cuenta").value = activa.nombre;
  for (const [campo, valor] of Object.entries(activa.costes)) $(`coste-${campo}`).value = valor;
}

// Reiniciar y borrar no se deshacen (RF-27, RF-28): el primer clic pone el botón en rojo y el segundo,
// antes de MS_CONFIRMAR, ejecuta la acción.
function conSegundoClic(boton, aviso, accion) {
  const texto = boton.textContent;
  let espera = null;
  const restaurar = () => {
    clearTimeout(espera);
    espera = null;
    boton.classList.remove("peligro");
    boton.textContent = texto;
  };
  boton.addEventListener("click", () => {
    if (espera) {
      restaurar();
      accion();
      return;
    }
    boton.classList.add("peligro");
    boton.textContent = "¿Seguro?";
    mostrarAviso(aviso);
    espera = setTimeout(restaurar, MS_CONFIRMAR);
  });
}

async function cambiarCuenta(cuerpo, ruta = `/api/cuentas/${$("cuenta-activa").value}`, metodo = "PATCH") {
  try {
    await pedir(ruta, metodo, cuerpo);
    mostrarAviso();
  } catch (error) {
    mostrarAviso(error.message);
  }
  await mostrarCuentas();
  await refrescarCuenta();
}

// --- Preparación ---

function prepararOperativa() {
  const guardada = preferencias.leer("boleta", {});
  $("cantidad").value = guardada.cantidad ?? 1;
  $("sl").value = guardada.sl ?? "";
  $("tp").value = guardada.tp ?? "";
  $("confirmar").addEventListener("click", enviarOrden);

  // La vista previa se ve mientras se prepara la orden: ratón sobre la boleta o foco en ella.
  const boleta = $("boleta");
  const tocar = (cambio) => () => {
    cambio();
    operativa.recienEnviada = false;
    actualizarPrevia();
  };
  boleta.addEventListener("mouseenter", tocar(() => (operativa.sobreBoleta = true)));
  boleta.addEventListener("mouseleave", () => {
    operativa.sobreBoleta = false;
    actualizarPrevia();
  });
  boleta.addEventListener("focusin", tocar(() => (operativa.focoEnBoleta = true)));
  boleta.addEventListener("focusout", (evento) => {
    operativa.focoEnBoleta = boleta.contains(evento.relatedTarget);
    actualizarPrevia();
  });
  boleta.addEventListener("input", tocar(() => {}));
  $("cerrar-todo").addEventListener("click", () => {
    completarMinutoSimulado();
    accionCuenta("/api/cuenta/cerrar-todo", "POST");
  });

  const panel = $("operar");
  const boton = $("boton-operar");
  const abierto = preferencias.leer("operar", true);
  panel.classList.toggle("plegado", !abierto);
  boton.setAttribute("aria-pressed", String(abierto));
  boton.addEventListener("click", () => {
    const abrir = panel.classList.contains("plegado");
    panel.classList.toggle("plegado", !abrir);
    boton.setAttribute("aria-pressed", String(abrir));
    preferencias.guardar("operar", abrir);
  });

  $("boton-cuentas").addEventListener("click", () => {
    const ajustes = $("ajustes-cuenta");
    ajustes.hidden = !ajustes.hidden;
    if (!ajustes.hidden) mostrarCuentas();
  });
  $("cuenta-activa").addEventListener("change", () => cambiarCuenta({ activa: true }));
  $("renombrar-cuenta").addEventListener("click", () => {
    const nombre = $("nombre-cuenta").value.trim();
    if (!nombre) {
      mostrarAviso("La cuenta necesita un nombre");
      return;
    }
    cambiarCuenta({ nombre });
  });
  conSegundoClic($("reiniciar-cuenta"), "Se borrará el historial y el balance volverá al inicial. Repite para confirmar.", () =>
    cambiarCuenta(undefined, `/api/cuentas/${$("cuenta-activa").value}/reiniciar`, "POST"),
  );
  conSegundoClic($("borrar-cuenta"), "Se borrará la cuenta con todo su historial. Repite para confirmar.", () =>
    cambiarCuenta(undefined, `/api/cuentas/${$("cuenta-activa").value}`, "DELETE"),
  );
  $("crear-cuenta").addEventListener("click", () => {
    const nombre = $("nueva-nombre").value.trim();
    const balance = Number($("nueva-balance").value);
    const perfil = $("nueva-tipo").value; // retos.js rellena los perfiles de reto (spec 006)
    if (!perfil && (!nombre || !(balance > 0))) {
      mostrarAviso("La cuenta nueva necesita nombre y balance inicial");
      return;
    }
    $("nueva-nombre").value = "";
    // En un reto, el balance inicial es el del perfil y el nombre, si no se escribe, también.
    const cuerpo = perfil ? { perfil, ...(nombre && { nombre }) } : { nombre, balance_inicial: balance };
    cambiarCuenta(cuerpo, "/api/cuentas", "POST");
  });
  $("guardar-costes").addEventListener("click", () => {
    const costes = {};
    for (const campo of ["spread_ticks", "deslizamiento_ticks", "comision_mini", "comision_micro"]) {
      costes[campo] = Number($(`coste-${campo}`).value);
    }
    cambiarCuenta(costes);
  });

  // Al cambiar de instrumento o timeframe: boleta del instrumento nuevo, líneas y marcas.
  alCargar.push(() => {
    mostrarBoleta();
    pintarLineas();
    pintarMarcas();
  });
  mostrarBoleta();
  mostrarCuentas();
  return refrescarCuenta();
}
