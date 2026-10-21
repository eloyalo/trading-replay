// Backtest de estrategias (spec 008): ventana con las pestañas de lanzar, resultados e historial, y modo
// backtest del gráfico para recorrer las operaciones con su SL, su TP y las marcas de la estrategia.
// El backtest corre en el backend; aquí se lanza, se sigue su progreso y se enseña el resultado.

const NOMBRE_RESULTADO_INTENTO = { aprobado: "Aprobado", suspendido: "Suspendido", en_curso: "Sin terminar" };
const NOMBRE_SESION = { asia: "Asia", londres: "Londres", nueva_york: "Nueva York", null: "Fuera de sesión" };
const SESIONES_FILTRO = [
  ["asia", "Asia"],
  ["londres", "Londres"],
  ["nueva_york", "Nueva York"],
];
// Día de la semana del día de trading de la entrada: el domingo por la tarde ya es lunes.
const DIAS_FILTRO = [
  ["lunes", "Lun"],
  ["martes", "Mar"],
  ["miércoles", "Mié"],
  ["jueves", "Jue"],
  ["viernes", "Vie"],
];
const POR_PAGINA = 200;
const MS_SONDEO = 300;
const MS_CONFIRMAR_BORRADO = 4000;
const VELAS_A_LA_DERECHA = 80; // al ir a una operación, cuántas velas se cargan después de su cierre
const CAMPOS_COSTES_BT = ["spread_ticks", "deslizamiento_ticks", "comision_mini", "comision_micro"];

const bt = {
  estrategias: [],
  ejecucion: null, // la que se ve en "Resultados"
  datos: null, // última respuesta de /api/backtests/{id}
  filtro: null, // {desde, hasta, anios, sesiones, dias, lado}
  mostradas: 0, // operaciones ya pintadas en la lista
  sondeo: null, // intervalo que sigue el backtest en marcha
  trabajoVisto: null, // id del último trabajo terminado que ya se ha atendido
  curva: null, // gráfico de la curva de capital
  serieCurva: null,
  grafico: null, // modo backtest: {id, simbolo, consulta, total, indice, op, tramo, centrar}
};

const marcasBacktest = LightweightCharts.createSeriesMarkers(serie, []);

// --- Formatos ---

const numero = (x, decimales = 2) => x.toLocaleString("es", { minimumFractionDigits: decimales, maximumFractionDigits: decimales });
const textoR = (r) => (r == null ? "—" : `${r < 0 ? "−" : r > 0 ? "+" : ""}${numero(Math.abs(r), 2)} R`);
const fechaHora = (iso) => iso.slice(0, 16).replace("T", " ");
const textoPrecio = (x) => (x == null ? "—" : numero(x, 2));

// Día de trading de un instante ET: lo de después de las 18:00 ya es del día siguiente.
function diaTradingDe(iso, menosUnMinuto = false) {
  const t = aSegundos(iso) + 6 * 3600 - (menosUnMinuto ? 60 : 0);
  return new Date(t * 1000).toISOString().slice(0, 10);
}

function duracionTexto(minutos) {
  if (minutos == null) return "—";
  if (minutos < 60) return `${Math.round(minutos)} min`;
  if (minutos < 1440) return `${Math.floor(minutos / 60)} h ${String(Math.round(minutos % 60)).padStart(2, "0")} min`;
  return `${numero(minutos / 1440, 1)} días`;
}

function textoParametros(parametros) {
  return Object.entries(parametros)
    .map(([clave, valor]) => `${clave} = ${typeof valor === "boolean" ? (valor ? "sí" : "no") : valor}`)
    .join(" · ");
}

function profitFactor(r) {
  if (!r.operaciones) return "—";
  return r.profit_factor == null ? "∞" : numero(r.profit_factor, 2);
}

function celda(texto, clase = "") {
  return crear("td", clase, texto);
}

// --- Ventana y pestañas ---

function abrirVentanaBacktest(pestana) {
  if (replay.activo) {
    mostrarAviso("El backtest enseña todo el histórico: sal del replay para usarlo");
    return;
  }
  const ventana = $("ventana-backtest");
  if (!ventana.open) ventana.showModal();
  elegirPestana(pestana ?? (bt.ejecucion ? "resultados" : "lanzar"));
}

function elegirPestana(nombre) {
  for (const boton of document.querySelectorAll("#ventana-backtest [data-pestana]")) {
    const elegida = boton.dataset.pestana === nombre;
    boton.setAttribute("aria-selected", String(elegida));
    $(`pestana-${boton.dataset.pestana}`).hidden = !elegida;
  }
  if (nombre === "lanzar") cargarEstrategias();
  if (nombre === "historial") pintarHistorial();
}

// --- Lanzar ---

async function cargarEstrategias(elegir) {
  const aviso = $("bt-aviso-lanzar");
  try {
    bt.estrategias = await api("/api/estrategias");
  } catch (error) {
    aviso.textContent = error.message;
    return;
  }
  const selector = $("bt-estrategia");
  const anterior = elegir ?? (selector.value || preferencias.leer("backtest.estrategia", null));
  selector.replaceChildren(...bt.estrategias.map((e) => new Option(e.error ? `${e.nombre} (con error)` : e.nombre, e.id)));
  selector.value = bt.estrategias.some((e) => e.id === anterior) ? anterior : (bt.estrategias[0]?.id ?? "");
  mostrarEstrategia();
}

const estrategiaElegida = () => bt.estrategias.find((e) => e.id === $("bt-estrategia").value);

function mostrarEstrategia() {
  const e = estrategiaElegida();
  $("bt-descripcion").textContent = e ? e.descripcion || "Sin descripción." : "No hay estrategias en la carpeta estrategias/.";
  $("bt-ruta").textContent = e ? `${e.ruta} · velas de ${e.timeframe ?? "?"}` : "";
  $("bt-duplicar").disabled = !e;
  $("bt-ver-codigo").disabled = !e;
  $("bt-codigo").hidden = true;
  $("bt-ver-codigo").setAttribute("aria-expanded", "false");
  const error = $("bt-error-estrategia");
  error.hidden = !e?.error;
  if (e?.error) {
    const donde = e.error.archivo ? `${e.error.archivo}${e.error.linea ? `, línea ${e.error.linea}` : ""}: ` : "";
    error.textContent = `${donde}${e.error.mensaje}`;
  }
  crearParametros(e);
  $("bt-lanzar").disabled = !e || Boolean(e.error) || Boolean(bt.sondeo);
}

function crearParametros(e) {
  const contenedor = $("bt-parametros");
  contenedor.replaceChildren();
  if (!e || e.error) return;
  if (!e.parametros.length) contenedor.append(crear("p", "nota", "Esta estrategia no tiene parámetros."));
  const guardados = preferencias.leer(`backtest.parametros.${e.id}`, {});
  const grupos = new Map(); // sección plegable -> su cuadrícula (spec 012, RF-1)
  for (const p of e.parametros) {
    const valor = typeof guardados[p.clave] === typeof p.defecto ? guardados[p.clave] : p.defecto;
    const etiqueta = crear("label", p.tipo === "bool" ? "bt-casilla" : "");
    let entrada;
    if (p.opciones) {
      entrada = document.createElement("select");
      for (const opcion of p.opciones) entrada.add(new Option(String(opcion), String(opcion)));
      entrada.value = String(valor);
    } else if (p.tipo === "bool") {
      entrada = document.createElement("input");
      entrada.type = "checkbox";
      entrada.checked = Boolean(valor);
    } else {
      entrada = document.createElement("input");
      entrada.type = p.tipo === "str" ? "text" : "number";
      if (p.minimo != null) entrada.min = p.minimo;
      if (p.maximo != null) entrada.max = p.maximo;
      if (entrada.type === "number") entrada.step = p.paso ?? (p.tipo === "int" ? 1 : "any");
      entrada.value = String(valor);
    }
    entrada.dataset.clave = p.clave;
    entrada.dataset.tipo = p.tipo;
    entrada.dataset.texto = p.texto;
    etiqueta.title = `Por defecto: ${p.defecto}`;
    if (p.tipo === "bool") etiqueta.append(entrada, ` ${p.texto}`);
    else etiqueta.append(p.texto, entrada);
    if (!p.grupo) {
      contenedor.append(etiqueta);
      continue;
    }
    if (!grupos.has(p.grupo)) {
      const seccion = crear("details", "bt-grupo");
      const cuadricula = crear("div", "bt-parametros");
      seccion.append(crear("summary", "", p.grupo), cuadricula);
      seccion.open = preferencias.leer(`backtest.grupo.${e.id}.${p.grupo}`, false);
      seccion.addEventListener("toggle", () => preferencias.guardar(`backtest.grupo.${e.id}.${p.grupo}`, seccion.open));
      contenedor.append(seccion);
      grupos.set(p.grupo, cuadricula);
    }
    grupos.get(p.grupo).append(etiqueta);
  }
}

function valoresParametros() {
  const valores = {};
  for (const entrada of $("bt-parametros").querySelectorAll("[data-clave]")) {
    const { clave, tipo, texto } = entrada.dataset;
    if (tipo === "bool") valores[clave] = entrada.checked;
    else if (entrada.tagName === "SELECT") {
      const original = estrategiaElegida().parametros.find((p) => p.clave === clave).opciones;
      valores[clave] = original.find((o) => String(o) === entrada.value);
    } else if (tipo === "str") valores[clave] = entrada.value;
    else {
      if (entrada.value.trim() === "") throw new Error(`Falta «${texto}»`);
      valores[clave] = Number(entrada.value);
    }
  }
  return valores;
}

async function lanzar() {
  const aviso = $("bt-aviso-lanzar");
  aviso.textContent = "";
  const e = estrategiaElegida();
  if (!e || e.error) return;
  let parametros;
  try {
    parametros = valoresParametros();
  } catch (error) {
    aviso.textContent = error.message;
    return;
  }
  const costes = Object.fromEntries(CAMPOS_COSTES_BT.map((c) => [c, Number($(`bt-coste-${c}`).value)]));
  const cuerpo = { estrategia: e.id, simbolo: $("bt-simbolo").value, parametros, costes };
  if ($("bt-desde").value) cuerpo.desde = $("bt-desde").value;
  if ($("bt-hasta").value) cuerpo.hasta = $("bt-hasta").value;
  if ($("bt-perfil").value) cuerpo.perfil = $("bt-perfil").value;
  preferencias.guardar("backtest.estrategia", e.id);
  preferencias.guardar(`backtest.parametros.${e.id}`, parametros);
  preferencias.guardar("backtest.lanzar", { simbolo: cuerpo.simbolo, desde: cuerpo.desde ?? "", hasta: cuerpo.hasta ?? "", costes, perfil: cuerpo.perfil ?? "" });
  try {
    await api("/api/backtests", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo) });
  } catch (error) {
    aviso.textContent = error.message;
    return;
  }
  seguirProgreso();
}

function seguirProgreso() {
  if (bt.sondeo) return;
  bt.sondeo = setInterval(sondear, MS_SONDEO);
  $("bt-lanzar").disabled = true;
  sondear();
}

function dejarDeSeguir() {
  clearInterval(bt.sondeo);
  bt.sondeo = null;
  $("bt-progreso").hidden = true;
  mostrarEstrategia();
}

async function sondear() {
  let trabajo;
  try {
    trabajo = await api("/api/backtests/en-marcha");
  } catch {
    return; // el servidor no responde: se vuelve a probar en el siguiente intervalo
  }
  if (!trabajo) {
    dejarDeSeguir();
    return;
  }
  $("bt-progreso").hidden = trabajo.estado !== "en_marcha";
  $("bt-progreso-relleno").style.width = `${trabajo.progreso * 100}%`;
  $("bt-progreso-texto").textContent = `${trabajo.nombre} en ${trabajo.simbolo}: ${Math.round(trabajo.progreso * 100)} %`;
  if (trabajo.estado === "en_marcha") return;
  dejarDeSeguir();
  if (bt.trabajoVisto === trabajo.id) return;
  bt.trabajoVisto = trabajo.id;
  const aviso = $("bt-aviso-lanzar");
  if (trabajo.estado === "hecho") {
    if (!replay.activo) {
      abrirVentanaBacktest("resultados");
      await abrirEjecucion(trabajo.ejecucion);
    }
  } else if (trabajo.estado === "error") {
    const e = trabajo.error;
    const donde = e.archivo ? `${e.archivo}${e.linea ? `, línea ${e.linea}` : ""}${e.vela ? ` (vela de ${e.vela})` : ""}: ` : "";
    aviso.textContent = `Error en la estrategia. ${donde}${e.mensaje}`;
  } else if (trabajo.estado === "cancelado") {
    aviso.textContent = "Backtest cancelado.";
  }
}

async function verCodigo(boton, caja, ruta) {
  const abrir = caja.hidden;
  boton.setAttribute("aria-expanded", String(abrir));
  caja.hidden = !abrir;
  if (!abrir) return;
  caja.textContent = "Cargando…";
  try {
    caja.textContent = (await api(ruta)).codigo;
  } catch (error) {
    caja.textContent = error.message;
  }
}

async function duplicar() {
  const e = estrategiaElegida();
  if (!e) return;
  const aviso = $("bt-aviso-lanzar");
  try {
    const copia = await api(`/api/estrategias/${e.id}/duplicar`, { method: "POST" });
    await cargarEstrategias(copia.id);
    aviso.textContent = "";
    $("bt-descripcion").textContent = `Copia creada en ${copia.ruta}. Ábrela en tu editor y guarda los cambios: la siguiente ejecución los usa.`;
  } catch (error) {
    aviso.textContent = error.message;
  }
}

// --- Resultados ---

const filtroVacio = () => ({ desde: "", hasta: "", anios: new Set(), sesiones: new Set(), dias: new Set(), lado: "" });

function consultaFiltro() {
  const f = bt.filtro;
  const params = new URLSearchParams();
  if (f.desde) params.set("desde", f.desde);
  if (f.hasta) params.set("hasta", f.hasta);
  if (f.anios.size) params.set("anios", [...f.anios].join(","));
  if (f.sesiones.size) params.set("sesiones", [...f.sesiones].join(","));
  if (f.dias.size) params.set("dias", [...f.dias].join(","));
  if (f.lado) params.set("lado", f.lado);
  return params;
}

async function abrirEjecucion(id) {
  bt.filtro = filtroVacio();
  bt.ejecucion = null;
  elegirPestana("resultados");
  await pintarResultados(id);
}

async function pintarResultados(id = bt.ejecucion?.id) {
  if (id == null) return;
  const consulta = consultaFiltro();
  consulta.set("limite", POR_PAGINA);
  let datos;
  try {
    datos = await api(`/api/backtests/${id}?${consulta}`);
  } catch (error) {
    $("bt-sin-resultados").textContent = error.message;
    $("bt-sin-resultados").hidden = false;
    $("bt-resultados-contenido").hidden = true;
    return;
  }
  const nueva = bt.ejecucion?.id !== datos.ejecucion.id;
  bt.datos = datos;
  bt.ejecucion = datos.ejecucion;
  $("bt-sin-resultados").hidden = true;
  $("bt-resultados-contenido").hidden = false;
  if (nueva) {
    pintarCabecera();
    pintarFiltros();
  }
  if (nueva) pintarReto(datos.reto);
  pintarCifras(datos.resumen);
  pintarCurva(datos.curva);
  pintarDesglose(datos.desglose);
  $("bt-operaciones").replaceChildren();
  bt.mostradas = 0;
  anadirOperaciones(datos.operaciones);
}

// --- Reto de prop firm (spec 009) ---

function pintarReto(reto) {
  $("bt-reto").hidden = !reto;
  document.querySelector(".bt-tabla--operaciones").classList.toggle("bt-sin-reto", !reto);
  if (!reto) return;
  const r = reto.resumen;
  const dias = (dias, naturales) => (dias == null ? "—" : `${numero(dias, 1)} días`) + (naturales == null ? "" : ` · ${numero(naturales, 1)} naturales`);
  const lista = (filas, clave) => filas.map((f) => `${f.motivo}: ${numero(f[clave], 0)}`).join(" · ");
  $("bt-reto-titulo").textContent = `Reto: ${reto.titulo ?? reto.perfil}`;
  $("bt-reto-cifras").replaceChildren(
    tarjetaCifra("Intentos", numero(r.intentos, 0), `${r.aprobados} aprobados · ${r.suspendidos} suspendidos · ${r.en_curso} sin terminar`),
    tarjetaCifra("% de aprobados", r.aprobacion == null ? "—" : porcentaje(r.aprobacion), "De los intentos terminados", r.aprobacion >= 0.5 ? "positivo" : ""),
    tarjetaCifra("Hasta aprobar", dias(r.dias_hasta_aprobar, r.naturales_hasta_aprobar), "Días del reto (con operaciones) y días naturales, de media"),
    tarjetaCifra("Hasta suspender", dias(r.dias_hasta_suspender, r.naturales_hasta_suspender), "De media"),
    tarjetaCifra(
      "Beneficio medio",
      `${r.beneficio_aprobados == null ? "—" : formatoDinero(r.beneficio_aprobados)} / ${r.beneficio_suspendidos == null ? "—" : formatoDinero(r.beneficio_suspendidos)}`,
      "Intentos aprobados / suspendidos",
    ),
    tarjetaCifra("Por qué suspende", r.motivos_suspension.length ? r.motivos_suspension[0].motivo : "—", lista(r.motivos_suspension, "intentos")),
    tarjetaCifra("Órdenes que el reto no admitió", numero(r.rechazadas.reduce((n, f) => n + f.ordenes, 0), 0), lista(r.rechazadas, "ordenes")),
  );
  $("bt-intentos").replaceChildren(...reto.intentos.map(filaIntento));
}

function filaIntento(i) {
  const fila = crear("tr");
  const desde = diaTradingDe(i.inicio);
  const hasta = diaTradingDe(i.fin ?? i.inicio, true);
  const resultado = celda("");
  resultado.append(crear("span", `chip chip--${i.resultado}`, NOMBRE_RESULTADO_INTENTO[i.resultado]));
  fila.append(
    celda(String(i.numero)),
    celda(desde === hasta ? desde : `${desde} → ${hasta}`),
    resultado,
    celda(i.motivo ?? "", "bt-motivo-intento"),
    celda(String(i.dias)),
    celda(formatoDinero(i.beneficio), tono(i.beneficio)),
    celda(formatoDinero(i.mejor_dia), tono(i.mejor_dia)),
    celda(String(i.operaciones)),
  );
  fila.title = "Ver solo las operaciones de este intento";
  fila.addEventListener("click", () => {
    bt.filtro.desde = desde;
    bt.filtro.hasta = hasta;
    pintarFiltros();
    pintarResultados().then(() => $("bt-titulo-operaciones").scrollIntoView({ behavior: "smooth", block: "start" }));
  });
  return fila;
}

function pintarCabecera() {
  const e = bt.ejecucion;
  $("bt-titulo-ejecucion").textContent = `${e.nombre} · ${e.simbolo} · velas de ${e.timeframe}`;
  const detalle = $("bt-detalle-ejecucion");
  const c = e.costes;
  detalle.replaceChildren(
    `Días de trading ${diaTradingDe(e.desde)} → ${diaTradingDe(e.hasta, true)} · ${textoParametros(e.parametros) || "sin parámetros"} · ` +
      `spread ${c.spread_ticks} tick, comisión ${numero(c.comision_mini)} $ por lado · lanzado el ${e.creada.slice(0, 16).replace("T", " ")} UTC en ${numero(e.segundos, 1)} s`,
  );
  if (e.codigo_cambiado) {
    detalle.append(" ", crear("span", "chip chip--aviso", e.estrategia_borrada ? "El archivo ya no existe" : "El código ha cambiado desde entonces"));
  }
  $("bt-codigo-ejecucion").hidden = true;
  $("bt-ver-codigo-ejecucion").setAttribute("aria-expanded", "false");
}

function chips(contenedor, opciones, conjunto) {
  contenedor.replaceChildren(
    ...opciones.map(([valor, texto]) => {
      const boton = crear("button", "", texto);
      boton.type = "button";
      boton.setAttribute("aria-pressed", String(conjunto.has(valor)));
      boton.addEventListener("click", () => {
        if (conjunto.has(valor)) conjunto.delete(valor);
        else conjunto.add(valor);
        boton.setAttribute("aria-pressed", String(conjunto.has(valor)));
        pintarResultados();
      });
      return boton;
    }),
  );
}

function pintarFiltros() {
  const e = bt.ejecucion;
  const f = bt.filtro;
  const primero = Number(diaTradingDe(e.desde).slice(0, 4));
  const ultimo = Number(diaTradingDe(e.hasta, true).slice(0, 4));
  const anios = [];
  for (let a = primero; a <= ultimo; a++) anios.push([a, String(a)]);
  chips($("bt-filtro-anios"), anios, f.anios);
  chips($("bt-filtro-sesiones"), SESIONES_FILTRO, f.sesiones);
  chips($("bt-filtro-dias"), DIAS_FILTRO, f.dias);
  $("bt-filtro-desde").value = f.desde;
  $("bt-filtro-hasta").value = f.hasta;
  $("bt-filtro-lado").value = f.lado;
}

function tarjetaCifra(titulo, valor, detalle = "", clase = "") {
  const tarjeta = crear("div", "bt-cifra");
  tarjeta.append(crear("span", "bt-cifra__titulo", titulo), crear("span", `bt-cifra__valor ${clase}`, valor));
  if (detalle) tarjeta.append(crear("span", "bt-cifra__detalle", detalle));
  return tarjeta;
}

function pintarCifras(r) {
  const hay = r.operaciones > 0;
  const dinero = (x) => (x == null ? "—" : formatoDinero(x));
  $("bt-cifras").replaceChildren(
    tarjetaCifra("Operaciones", numero(r.operaciones, 0), `${r.ganadoras} ganadoras · ${r.perdedoras} perdedoras`),
    tarjetaCifra("% de acierto", r.acierto == null ? "—" : porcentaje(r.acierto)),
    tarjetaCifra("Beneficio neto", formatoDinero(r.neto), `Bruto ${formatoDinero(r.bruto)} · comisiones ${formatoSaldo(r.comisiones)}`, tono(r.neto)),
    tarjetaCifra("Profit factor", profitFactor(r), "Ganancias ÷ pérdidas"),
    tarjetaCifra("Esperanza", dinero(r.esperanza), `${textoR(r.esperanza_r)} por operación`, tono(r.esperanza ?? 0)),
    tarjetaCifra("Drawdown máximo", hay ? formatoSaldo(r.drawdown) : "—", hay ? `${numero(r.drawdown_r, 2)} R` : ""),
    tarjetaCifra(
      "Ganancia y pérdida media",
      `${dinero(r.ganancia_media)} / ${dinero(r.perdida_media)}`,
      `Proporción ${r.proporcion == null ? "—" : numero(r.proporcion, 2)} · ${textoR(r.r_ganadoras)} / ${textoR(r.r_perdedoras)}`,
    ),
    tarjetaCifra("Rachas máximas", `${r.racha_ganadoras} / ${r.racha_perdedoras}`, "Ganadoras / perdedoras seguidas"),
    tarjetaCifra("Duración media", duracionTexto(r.duracion_media), r.por_mes == null ? "" : `${numero(r.por_mes, 1)} operaciones al mes`),
    tarjetaCifra(
      "SL y TP en el mismo minuto",
      `${r.dudosas} de ${r.operaciones}`,
      "Con velas de 1m no se sabe cuál llegó antes: cuenta el SL",
      r.dudosas ? "aviso-texto" : "",
    ),
  );
}

function pintarCurva(puntos) {
  if (!bt.curva) {
    bt.curva = LightweightCharts.createChart($("bt-curva"), {
      autoSize: true,
      layout: { background: { color: color("--fondo") }, textColor: color("--texto") },
      grid: { vertLines: { color: color("--borde") }, horzLines: { color: color("--borde") } },
      timeScale: { timeVisible: false },
      handleScroll: false,
      handleScale: false,
    });
    bt.serieCurva = bt.curva.addSeries(LightweightCharts.BaselineSeries, {
      baseValue: { type: "price", price: 0 },
      topLineColor: color("--verde"),
      topFillColor1: color("--verde-suave"),
      topFillColor2: "rgba(38, 166, 154, 0.05)",
      bottomLineColor: color("--rojo"),
      bottomFillColor1: "rgba(239, 83, 80, 0.05)",
      bottomFillColor2: color("--rojo-suave"),
      priceFormat: { type: "price", precision: 0, minMove: 1 },
    });
  }
  bt.serieCurva.setData(puntos);
  bt.curva.timeScale().fitContent();
}

function pintarDesglose(desglose) {
  const tablas = [
    ["Año", desglose.anio, (g) => String(g)],
    ["Sesión", desglose.sesion, (g) => NOMBRE_SESION[g]],
    ["Día", desglose.dia, (g) => g[0].toUpperCase() + g.slice(1)],
    ["Lado", desglose.lado, (g) => g[0].toUpperCase() + g.slice(1)],
  ];
  $("bt-desglose").replaceChildren(
    ...tablas.map(([titulo, filas, nombre]) => {
      const tabla = crear("table", "bt-tabla bt-tabla--desglose");
      const cabecera = crear("tr");
      for (const texto of [titulo, "Ops.", "% acierto", "Neto", "PF", "Esp. R"]) cabecera.append(crear("th", "", texto));
      tabla.append(crear("thead"));
      tabla.tHead.append(cabecera);
      const cuerpo = crear("tbody");
      for (const g of filas) {
        const fila = crear("tr");
        fila.append(
          celda(nombre(g.grupo)),
          celda(String(g.operaciones)),
          celda(g.acierto == null ? "—" : porcentaje(g.acierto)),
          celda(formatoDinero(g.neto), tono(g.neto)),
          celda(profitFactor(g)),
          celda(textoR(g.esperanza_r)),
        );
        cuerpo.append(fila);
      }
      if (!filas.length) cuerpo.append(Object.assign(crear("tr"), { innerHTML: '<td colspan="6" class="vacia">Sin operaciones</td>' }));
      tabla.append(cuerpo);
      return tabla;
    }),
  );
}

function filaOperacion(op, indice) {
  const fila = crear("tr");
  fila.title = op.motivo_entrada ? `${op.motivo_entrada} · ver en el gráfico` : "Ver en el gráfico";
  const largo = op.lado === "largo";
  const sl = op.sl_final != null && op.sl_final !== op.sl_inicial ? `${textoPrecio(op.sl_inicial)} → ${textoPrecio(op.sl_final)}` : textoPrecio(op.sl_inicial);
  const motivo = celda(op.motivo_salida);
  if (op.dudosa) {
    motivo.append(crear("span", "aviso-texto", " ⚠"));
    motivo.title = "El SL y el TP cayeron en el mismo minuto: se dio por bueno el SL";
  }
  fila.append(
    celda(String(op.numero)),
    celda(fechaHora(op.apertura)),
    celda(largo ? "Largo" : "Corto", largo ? "positivo" : "negativo"),
    celda(`${op.cantidad} ${op.contrato}`),
    celda(textoPrecio(op.entrada)),
    celda(textoPrecio(op.salida)),
    celda(sl),
    celda(textoPrecio(op.tp_final)),
    motivo,
    celda(formatoDinero(op.pnl_neto), tono(op.pnl_neto)),
    celda(textoR(op.r), tono(op.r ?? 0)),
    celda(op.intento == null ? "" : String(op.intento), "solo-reto"),
  );
  fila.addEventListener("click", () => verEnGrafico(indice));
  return fila;
}

function anadirOperaciones(operaciones) {
  const cuerpo = $("bt-operaciones");
  operaciones.forEach((op, i) => cuerpo.append(filaOperacion(op, bt.mostradas + i)));
  bt.mostradas += operaciones.length;
  const total = bt.datos.total;
  $("bt-titulo-operaciones").textContent = `Operaciones (${numero(total, 0)})`;
  $("bt-ver-mas").hidden = bt.mostradas >= total;
  $("bt-ver-mas").textContent = `Ver más (quedan ${numero(total - bt.mostradas, 0)})`;
  if (!total) cuerpo.append(Object.assign(crear("tr"), { innerHTML: '<td colspan="12" class="vacia">Ninguna operación con estos filtros</td>' }));
}

async function verMas() {
  const consulta = consultaFiltro();
  consulta.set("inicio", bt.mostradas);
  consulta.set("limite", POR_PAGINA);
  const datos = await api(`/api/backtests/${bt.ejecucion.id}?${consulta}`);
  anadirOperaciones(datos.operaciones);
}

// --- Historial ---

async function pintarHistorial() {
  const aviso = $("bt-aviso-historial");
  let ejecuciones;
  try {
    ejecuciones = await api("/api/backtests");
    aviso.textContent = "";
  } catch (error) {
    aviso.textContent = error.message;
    return;
  }
  const cuerpo = $("bt-historial");
  if (!ejecuciones.length) {
    cuerpo.replaceChildren(Object.assign(crear("tr"), { innerHTML: '<td colspan="12" class="vacia">Todavía no hay ejecuciones</td>' }));
    return;
  }
  cuerpo.replaceChildren(...ejecuciones.map(filaHistorial));
}

function filaHistorial(e) {
  const r = e.resumen;
  const fila = crear("tr");
  const nombre = celda(e.nombre);
  if (e.codigo_cambiado) {
    nombre.append(" ", crear("span", "chip chip--aviso", e.estrategia_borrada ? "archivo borrado" : "código cambiado"));
  }
  if (e.reto) {
    const aprobados = e.reto.aprobacion == null ? "—" : porcentaje(e.reto.aprobacion);
    nombre.append(crear("span", "bt-reto-historial", `${e.reto.titulo ?? e.perfil}: ${aprobados} aprobados`));
  }
  const acciones = crear("div", "bt-acciones");
  const abrir = crear("button", "", "Abrir");
  abrir.type = "button";
  abrir.addEventListener("click", () => abrirEjecucion(e.id));
  const borrar = crear("button", "", "Borrar");
  borrar.type = "button";
  let confirmar = null;
  borrar.addEventListener("click", async () => {
    if (!confirmar) {
      borrar.textContent = "¿Seguro?";
      borrar.classList.add("peligro");
      confirmar = setTimeout(() => {
        confirmar = null;
        borrar.textContent = "Borrar";
        borrar.classList.remove("peligro");
      }, MS_CONFIRMAR_BORRADO);
      return;
    }
    clearTimeout(confirmar);
    try {
      await api(`/api/backtests/${e.id}`, { method: "DELETE" });
    } catch (error) {
      $("bt-aviso-historial").textContent = error.message;
    }
    if (bt.ejecucion?.id === e.id) {
      bt.ejecucion = null;
      $("bt-resultados-contenido").hidden = true;
      $("bt-sin-resultados").hidden = false;
    }
    pintarHistorial();
  });
  acciones.append(abrir, borrar);
  const periodo = celda(diaTradingDe(e.desde));
  periodo.append(document.createElement("br"), `→ ${diaTradingDe(e.hasta, true)}`);
  fila.append(
    celda(fechaHora(e.creada)),
    nombre,
    celda(textoParametros(e.parametros), "bt-parametros-texto"),
    celda(e.simbolo),
    periodo,
    celda(numero(r.operaciones, 0)),
    celda(r.acierto == null ? "—" : porcentaje(r.acierto)),
    celda(profitFactor(r)),
    celda(textoR(r.esperanza_r)),
    celda(r.operaciones ? formatoSaldo(r.drawdown) : "—"),
    celda(formatoDinero(r.neto), tono(r.neto)),
  );
  fila.insertCell().append(acciones);
  return fila;
}

// --- Modo backtest del gráfico (RF-14 a RF-16) ---

// Fin de la vela de `tf` que contiene `t`. La diaria se etiqueta a las 00:00 y acaba a las 18:00.
function finVela(t, tf) {
  const inicio = cubeta(t, tf);
  return tf === "1D" ? inicio + 18 * 3600 : inicio + MINUTOS_TF[tf] * 60;
}

async function verEnGrafico(indice = 0) {
  if (replay.activo) return;
  const e = bt.ejecucion;
  bt.grafico = {
    id: e.id,
    simbolo: e.simbolo,
    consulta: consultaFiltro().toString(),
    total: bt.datos.total,
    indice: -1,
    op: null,
    tramo: { operaciones: [], marcas: [] },
    centrar: false,
  };
  document.body.classList.add("modo-backtest");
  $("ventana-backtest").close();
  if (!bt.datos.total) {
    mostrarBarra("Ninguna operación con estos filtros");
    return;
  }
  await irAOperacion(indice);
}

async function irAOperacion(indice) {
  const g = bt.grafico;
  if (!g || indice < 0 || indice >= g.total) return;
  const params = new URLSearchParams(g.consulta);
  params.set("inicio", indice);
  params.set("limite", 1);
  let datos;
  try {
    datos = await api(`/api/backtests/${g.id}?${params}`);
  } catch (error) {
    mostrarBarra(error.message);
    return;
  }
  const op = datos.operaciones[0];
  if (!op || bt.grafico !== g) return;
  Object.assign(g, { indice, op, total: datos.total });
  mostrarBarra();
  const cambiaSimbolo = estado.simbolo !== g.simbolo;
  if (cambiaSimbolo) {
    estado.simbolo = g.simbolo;
    marcar($("simbolos"), estado.simbolo);
  }
  const velas = estado.velas;
  const cargada =
    !cambiaSimbolo && estado.ancla !== null && velas.length && op.t_apertura >= velas[0].time && op.t_cierre < velas.at(-1).time;
  if (cargada) {
    centrarOperacion();
    pintarBacktest();
    return;
  }
  estado.ancla = finVela(op.t_cierre + VELAS_A_LA_DERECHA * MINUTOS_TF[estado.tf] * 60, estado.tf);
  await cargar();
}

function centrarOperacion() {
  const op = bt.grafico?.op;
  if (!op || !estado.velas.length) return;
  const desde = tiempoALogico(estado.velas, op.t_minuto_entrada, estado.tf);
  const hasta = tiempoALogico(estado.velas, op.t_minuto_salida, estado.tf);
  const ancho = Math.max((hasta - desde) * 1.8, 60);
  const inicio = desde - (ancho - (hasta - desde)) / 2;
  grafico.timeScale().setVisibleLogicalRange({ from: inicio, to: inicio + ancho });
}

async function pedirTramo() {
  const g = bt.grafico;
  if (!g) return;
  if (estado.simbolo !== g.simbolo || !estado.velas.length) {
    g.tramo = { operaciones: [], marcas: [] };
    pintarBacktest();
    return;
  }
  const desde = estado.velas[0].time - (estado.tf === "1D" ? 6 * 3600 : 0);
  const hasta = finVela(estado.velas.at(-1).time, estado.tf);
  const params = new URLSearchParams({ desde: horaET(desde), hasta: horaET(hasta) });
  try {
    const tramo = await api(`/api/backtests/${g.id}/tramo?${params}`);
    if (bt.grafico !== g) return;
    g.tramo = tramo;
  } catch (error) {
    mostrarBarra(error.message);
  }
  pintarBacktest();
}

function mostrarBarra(aviso = "") {
  const g = bt.grafico;
  $("bt-aviso").textContent = aviso;
  $("bt-aviso").classList.toggle("aviso--error", Boolean(aviso));
  const texto = $("bt-operacion");
  if (!g?.op) {
    texto.textContent = "";
  } else {
    const op = g.op;
    texto.replaceChildren(
      // Con filtros, el número de la operación en la ejecución entera no coincide con su posición.
      `Operación ${numero(g.indice + 1, 0)} de ${numero(g.total, 0)}${op.numero !== g.indice + 1 ? ` (n.º ${op.numero})` : ""} · `,
      crear("span", op.lado === "largo" ? "positivo" : "negativo", op.lado === "largo" ? "Largo" : "Corto"),
      ` ${op.cantidad} ${op.contrato} · ${fechaHora(op.apertura)} · `,
      crear("span", tono(op.pnl_neto), formatoDinero(op.pnl_neto)),
      ` · ${textoR(op.r)} · ${op.motivo_salida}${op.dudosa ? " ⚠" : ""}`,
    );
    texto.title = op.motivo_entrada || "";
  }
  $("bt-anterior").disabled = !g?.op || g.indice <= 0;
  $("bt-siguiente").disabled = !g?.op || g.indice >= g.total - 1;
}

function pintarBacktest() {
  pintarMarcasBacktest();
  primitivaBacktest.pedirRepintado?.();
  $("bt-copiar-fibonacci").hidden = !fibonacciDeLaOperacion();
}

// La figura de Fibonacci que la estrategia dibujó para la operación que se está viendo (spec 012, RF-24).
function fibonacciDeLaOperacion() {
  const g = bt.grafico;
  if (!g?.op || estado.simbolo !== g.simbolo) return null;
  return g.tramo.marcas.find((m) => m.tipo === "fibonacci" && m.datos && m.t <= g.op.t_cierre && (m.t_fin ?? Infinity) >= g.op.t_apertura) ?? null;
}

// "Copiar como dibujo": la figura pasa a los dibujos propios, que se pueden mover, y se guarda como cualquier dibujo.
function copiarFibonacciComoDibujo() {
  const marca = fibonacciDeLaOperacion();
  if (!marca) return;
  if (dibujo.simbolo !== estado.simbolo) cargarDibujos();
  const { origen, final } = marca.datos;
  dibujo.lista.push({
    id: crypto.randomUUID(),
    tipo: "fibonacci",
    puntos: [
      { t: origen.t, precio: origen.precio },
      { t: final.t, precio: final.precio },
    ],
  });
  guardarDibujos();
  repintarDibujos();
  mostrarBarra("Fibonacci copiado a tus dibujos");
}

function pintarMarcasBacktest() {
  const g = bt.grafico;
  if (!g || estado.simbolo !== g.simbolo) {
    marcasBacktest.setMarkers([]);
    return;
  }
  const primera = estado.velas[0]?.time ?? Infinity;
  const lista = [];
  for (const op of g.tramo.operaciones) {
    const largo = op.lado === "largo";
    const actual = op.numero === g.op?.numero;
    lista.push({
      time: cubeta(op.t_minuto_entrada, estado.tf),
      position: largo ? "belowBar" : "aboveBar",
      shape: largo ? "arrowUp" : "arrowDown",
      color: actual ? color("--azul-claro") : color(largo ? "--verde" : "--rojo"),
      text: `#${op.numero}`,
    });
    lista.push({
      time: cubeta(op.t_minuto_salida, estado.tf),
      position: largo ? "aboveBar" : "belowBar",
      shape: "circle",
      color: op.pnl_neto >= 0 ? color("--verde") : color("--rojo"),
      text: actual ? `${op.motivo_salida} ${formatoDinero(op.pnl_neto)}` : "",
    });
  }
  marcasBacktest.setMarkers(lista.filter((m) => m.time >= primera).sort((a, b) => a.time - b.time));
}

// Coordenada x de un instante: dentro de su vela, según la parte de la vela que ya ha pasado.
function xDe(t) {
  const logico = tiempoALogico(estado.velas, t, estado.tf);
  if (logico === null) return null;
  const escala = grafico.timeScale();
  const x = escala.logicalToCoordinate(logico);
  const siguiente = escala.logicalToCoordinate(logico + 1);
  if (x === null || siguiente === null) return null;
  const duracion = MINUTOS_TF[estado.tf] * 60;
  const fraccion = estado.tf === "1D" ? 0 : (t - cubeta(t, estado.tf)) / duracion;
  return x + (fraccion - 0.5) * (siguiente - x);
}

class PrimitivaBacktest {
  constructor() {
    this.zonas = null; // de la operación actual
    this.marcas = []; // de la estrategia
    this.fondo = { renderer: () => ({ draw: (destino) => this.pintarZonas(destino) }), zOrder: () => "bottom" };
    this.frente = { renderer: () => ({ draw: (destino) => this.pintarMarcas(destino) }), zOrder: () => "top" };
  }

  attached({ requestUpdate }) {
    this.pedirRepintado = requestUpdate;
  }

  detached() {
    this.pedirRepintado = null;
  }

  updateAllViews() {
    const g = bt.grafico;
    this.zonas = null;
    this.marcas = [];
    if (!g || estado.simbolo !== g.simbolo || !estado.velas.length) return;
    const y = (precio) => (precio == null ? null : serie.priceToCoordinate(precio));
    const op = g.op;
    if (op) {
      const x1 = xDe(op.t_apertura);
      const x2 = xDe(op.t_cierre);
      if (x1 !== null && x2 !== null) {
        this.zonas = {
          x1,
          x2: Math.max(x2, x1 + 2),
          entrada: y(op.entrada),
          salida: y(op.salida),
          sl: y(op.sl_inicial),
          slFinal: op.sl_final !== op.sl_inicial ? y(op.sl_final) : null,
          tp: y(op.tp_final),
        };
      }
    }
    for (const m of g.tramo.marcas) {
      const x1 = xDe(m.t);
      const x2 = m.t_fin == null ? null : xDe(m.t_fin);
      if (x1 === null) continue;
      const marca = { ...m, x1, x2, y1: y(m.precio), y2: y(m.precio2) };
      if (m.tipo === "fibonacci") {
        // La figura de la spec 012: del origen al final del impulso, con los niveles que usó la estrategia.
        const xFinal = m.datos ? xDe(m.datos.final.t) : null;
        if (xFinal === null || marca.y1 === null || marca.y2 === null) continue;
        marca.fib = {
          p1: { x: x1, y: marca.y1, precio: m.datos.origen.precio },
          p2: { x: xFinal, y: marca.y2, precio: m.datos.final.precio },
        };
      }
      this.marcas.push(marca);
    }
  }

  paneViews() {
    return [this.fondo, this.frente];
  }

  pintarZonas(destino) {
    const z = this.zonas;
    if (!z || z.entrada === null) return;
    destino.useMediaCoordinateSpace(({ context: ctx }) => {
      const ancho = z.x2 - z.x1;
      for (const [precio, variable] of [
        [z.sl, "--zona-sl"],
        [z.tp, "--zona-tp"],
      ]) {
        if (precio === null) continue;
        ctx.fillStyle = color(variable);
        ctx.fillRect(z.x1, Math.min(precio, z.entrada), ancho, Math.abs(precio - z.entrada));
      }
      ctx.lineWidth = 1;
      ctx.strokeStyle = color("--gris");
      ctx.beginPath();
      ctx.moveTo(z.x1, z.entrada);
      ctx.lineTo(z.x2, z.entrada);
      ctx.stroke();
      if (z.slFinal !== null) {
        ctx.strokeStyle = color("--rojo");
        ctx.setLineDash([4, 3]);
        ctx.beginPath();
        ctx.moveTo(z.x1, z.slFinal);
        ctx.lineTo(z.x2, z.slFinal);
        ctx.stroke();
      }
      if (z.salida !== null) {
        ctx.strokeStyle = color("--texto");
        ctx.setLineDash([4, 3]);
        ctx.beginPath();
        ctx.moveTo(z.x1, z.entrada);
        ctx.lineTo(z.x2, z.salida);
        ctx.stroke();
      }
      ctx.setLineDash([]);
    });
  }

  pintarMarcas(destino) {
    if (!this.marcas.length) return;
    destino.useMediaCoordinateSpace(({ context: ctx, mediaSize }) => {
      const tinta = color("--violeta");
      ctx.font = "11px system-ui, sans-serif";
      ctx.lineWidth = 1;
      for (const m of this.marcas) {
        const x2 = m.x2 ?? mediaSize.width;
        ctx.strokeStyle = tinta;
        ctx.fillStyle = tinta;
        if (m.tipo === "fibonacci") {
          // El 0 % (final del impulso) coincide con la extensión 1,0: se dibuja solo una vez.
          const final = m.datos.extensiones.includes(1) ? [] : [0];
          const config = { ...configFibonacci(), retrocesos: [...final, ...m.datos.retrocesos, 1], extensiones: m.datos.extensiones, conExtensiones: true };
          pintarFibonacci(ctx, mediaSize.width, m.fib.p1, m.fib.p2, config, { xFin: x2, tinta, texto: tinta });
          ctx.font = "11px system-ui, sans-serif";
        } else if (m.tipo === "rango" && m.y1 !== null && m.y2 !== null) {
          ctx.globalAlpha = 0.12;
          ctx.fillRect(m.x1, Math.min(m.y1, m.y2), x2 - m.x1, Math.abs(m.y2 - m.y1));
          ctx.globalAlpha = 1;
          ctx.strokeRect(m.x1, Math.min(m.y1, m.y2), x2 - m.x1, Math.abs(m.y2 - m.y1));
          if (m.texto) ctx.fillText(m.texto, m.x1 + 3, Math.min(m.y1, m.y2) - 4);
        } else if (m.tipo === "nivel" && m.y1 !== null) {
          ctx.setLineDash([5, 4]);
          ctx.beginPath();
          ctx.moveTo(m.x1, m.y1);
          ctx.lineTo(x2, m.y1);
          ctx.stroke();
          ctx.setLineDash([]);
          if (m.texto) ctx.fillText(m.texto, m.x1 + 3, m.y1 - 4);
        } else if (m.tipo === "texto" && m.y1 !== null && m.texto) {
          ctx.textAlign = "center";
          ctx.fillText(m.texto, m.x1, m.y1 - 8);
          ctx.textAlign = "start";
        }
      }
    });
  }
}

const primitivaBacktest = new PrimitivaBacktest();
serie.attachPrimitive(primitivaBacktest);

function salirModoBacktest() {
  if (!bt.grafico) return;
  bt.grafico = null;
  estado.ancla = null;
  document.body.classList.remove("modo-backtest");
  pintarBacktest();
  mostrarBarra();
  cargar();
}

// Atajos del modo backtest: ← y → recorren las operaciones y Esc sale. Se escuchan antes que los del
// replay (fase de captura) para que `R` no empiece un replay mientras se mira un backtest (RF-16).
function atajoBacktest(evento) {
  if (!bt.grafico || hayVentana() || evento.ctrlKey || evento.metaKey || evento.altKey || esCampo(evento.target)) return;
  const g = bt.grafico;
  const acciones = {
    ArrowLeft: () => irAOperacion(g.indice - 1),
    ArrowRight: () => irAOperacion(g.indice + 1),
    Escape: () => cancelaciones.some((cancelar) => cancelar()) || salirModoBacktest(),
    r: () => {},
    R: () => {},
  };
  const accion = acciones[evento.key];
  if (!accion) return;
  evento.preventDefault();
  evento.stopPropagation();
  accion();
}

// --- Preparación ---

async function prepararBacktest() {
  for (const boton of document.querySelectorAll("#ventana-backtest [data-pestana]")) {
    boton.addEventListener("click", () => elegirPestana(boton.dataset.pestana));
  }
  $("boton-backtest").addEventListener("click", () => abrirVentanaBacktest());
  $("bt-estrategia").addEventListener("change", mostrarEstrategia);
  $("bt-recargar").addEventListener("click", () => cargarEstrategias());
  $("bt-ver-codigo").addEventListener("click", () => {
    const e = estrategiaElegida();
    if (e) verCodigo($("bt-ver-codigo"), $("bt-codigo"), `/api/estrategias/${e.id}/codigo`);
  });
  $("bt-duplicar").addEventListener("click", duplicar);
  $("bt-lanzar").addEventListener("click", lanzar);
  $("bt-cancelar").addEventListener("click", () => api("/api/backtests/en-marcha/cancelar", { method: "POST" }).catch(() => {}));

  $("bt-ver-codigo-ejecucion").addEventListener("click", () => {
    if (bt.ejecucion) verCodigo($("bt-ver-codigo-ejecucion"), $("bt-codigo-ejecucion"), `/api/backtests/${bt.ejecucion.id}/codigo`);
  });
  $("bt-ver-grafico").addEventListener("click", () => verEnGrafico(0));
  $("bt-ver-mas").addEventListener("click", verMas);
  for (const [id, campo] of [
    ["bt-filtro-desde", "desde"],
    ["bt-filtro-hasta", "hasta"],
    ["bt-filtro-lado", "lado"],
  ]) {
    $(id).addEventListener("change", () => {
      bt.filtro[campo] = $(id).value;
      pintarResultados();
    });
  }
  $("bt-quitar-filtros").addEventListener("click", () => {
    bt.filtro = filtroVacio();
    pintarFiltros();
    pintarResultados();
  });

  $("bt-anterior").addEventListener("click", () => irAOperacion(bt.grafico.indice - 1));
  $("bt-siguiente").addEventListener("click", () => irAOperacion(bt.grafico.indice + 1));
  $("bt-copiar-fibonacci").addEventListener("click", copiarFibonacciComoDibujo);
  $("bt-resultados").addEventListener("click", () => abrirVentanaBacktest("resultados"));
  $("bt-salir").addEventListener("click", salirModoBacktest);
  window.addEventListener("keydown", atajoBacktest, true);

  // Una recarga entera (ir a otra operación, cambiar de timeframe) vuelve a centrar la operación actual.
  alRecargar.push(() => {
    if (bt.grafico) bt.grafico.centrar = true;
  });
  alCargar.push(() => {
    const g = bt.grafico;
    if (!g) return;
    if (g.centrar) {
      g.centrar = false;
      centrarOperacion();
    }
    pedirTramo();
  });

  // Instrumentos y valores de la última vez en el formulario de lanzar.
  const instrumentos = await api("/api/instrumentos");
  const guardado = preferencias.leer("backtest.lanzar", {});
  const simbolos = $("bt-simbolo");
  for (const i of instrumentos) simbolos.add(new Option(`${i.simbolo} · ${i.nombre}`, i.simbolo));
  simbolos.value = guardado.simbolo ?? estado.simbolo;
  const disponible = instrumentos.filter((i) => i.desde);
  if (disponible.length) {
    $("bt-desde").min = $("bt-hasta").min = disponible[0].desde.slice(0, 10);
    $("bt-desde").max = $("bt-hasta").max = disponible[0].hasta.slice(0, 10);
  }
  const perfiles = await api("/api/perfiles").catch(() => []);
  for (const p of perfiles) $("bt-perfil").add(new Option(p.titulo, p.id));
  $("bt-perfil").value = perfiles.some((p) => p.id === guardado.perfil) ? guardado.perfil : "";
  $("bt-desde").value = guardado.desde ?? "";
  $("bt-hasta").value = guardado.hasta ?? "";
  for (const campo of CAMPOS_COSTES_BT) {
    if (guardado.costes?.[campo] != null) $(`bt-coste-${campo}`).value = guardado.costes[campo];
  }

  // Si hay un backtest en marcha (por ejemplo, tras recargar la página), se sigue.
  const enMarcha = await api("/api/backtests/en-marcha").catch(() => null);
  if (enMarcha?.estado === "en_marcha") seguirProgreso();
  else if (enMarcha) bt.trabajoVisto = enMarcha.id;
}
