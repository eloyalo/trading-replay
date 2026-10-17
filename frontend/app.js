const { createChart, CandlestickSeries } = LightweightCharts;

const TIMEFRAMES = Object.keys(MINUTOS_TF);
// Días que devuelve /api/velas de cada timeframe (`VENTANA_POR_DEFECTO` en app.py), para pedir tramos a la derecha.
const DIAS_VENTANA = { "1m": 3, "5m": 14, "15m": 31, "30m": 62, "1h": 92, "4h": 366, "1D": 3660 };
const DIAS = ["Dom", "Lun", "Mar", "Mié", "Jue", "Vie", "Sáb"];

// Preferencias del usuario en el navegador. Si el almacenamiento falla, se usan los valores por defecto.
const preferencias = {
  leer(clave, defecto) {
    try {
      const valor = localStorage.getItem(`trading-replay.${clave}`);
      return valor === null ? defecto : JSON.parse(valor);
    } catch {
      return defecto;
    }
  },
  guardar(clave, valor) {
    try {
      localStorage.setItem(`trading-replay.${clave}`, JSON.stringify(valor));
    } catch {
      // sin almacenamiento: la preferencia dura hasta recargar
    }
  },
};

const colores = getComputedStyle(document.documentElement);
const color = (nombre) => colores.getPropertyValue(nombre).trim();

const grafico = createChart(document.getElementById("grafico"), {
  autoSize: true,
  layout: {
    background: { color: color("--fondo") },
    textColor: color("--texto"),
  },
  grid: {
    vertLines: { color: color("--borde") },
    horzLines: { color: color("--borde") },
  },
  // Hueco a la derecha de la última vela para poder dibujar en el futuro del replay (spec 004, RF-2).
  timeScale: { timeVisible: true, secondsVisible: false, rightOffset: 15 },
});

const serie = grafico.addSeries(CandlestickSeries, {
  upColor: color("--verde"),
  downColor: color("--rojo"),
  borderVisible: false,
  wickUpColor: color("--verde"),
  wickDownColor: color("--rojo"),
  priceFormat: { type: "price", precision: 2, minMove: 0.01 },
});

// Estado de lo que se muestra. `time` de cada vela es la hora de Nueva York
// expresada como si fuera UTC, así que el gráfico enseña directamente la hora ET.
const estado = {
  simbolo: "NQ",
  tf: "15m",
  velas: [],
  inicioDatos: null,
  cargando: false,
  completo: false,
  peticion: 0,
  // Modo backtest (spec 008): se carga hasta `ancla` (segundos, como `time`) en vez de hasta el final, y
  // se pide más a la derecha al desplazarse. Con null, como siempre.
  ancla: null,
  completoDerecha: true,
  ciego: preferencias.leer("ciego", false), // modo a ciegas: sin día, mes ni año (spec 003, RF-14)
};

// Funciones a las que avisar cuando el gráfico se va a recargar entero, y cuando ya se ha cargado.
const alRecargar = [];
const alCargar = [];
// Con `Esc`, cada una cancela lo que tenga en marcha (un dibujo, un panel abierto) y devuelve true
// si lo ha hecho. Si ninguna lo hace, `Esc` sale del replay.
const cancelaciones = [];

// Con una ventana modal abierta (retos.js), los atajos del gráfico no se aplican.
const hayVentana = () => Boolean(document.querySelector("dialog[open]"));

const horaET = (time) => new Date(time * 1000).toISOString().slice(0, 16);

// "Mar 2024-05-14 10:37", o "Mar 10:37" en modo a ciegas.
function textoMomento(time, conHora = true) {
  const iso = horaET(time);
  const dia = DIAS[new Date(time * 1000).getUTCDay()];
  const hora = conHora ? ` ${iso.slice(11)}` : "";
  return estado.ciego ? `${dia}${hora}` : `${dia} ${iso.slice(0, 10)}${hora}`;
}

// Marcas del eje: en modo a ciegas, día de la semana en vez de fecha; si no, las de la librería.
function marcaEje(time, tipo) {
  if (!estado.ciego) return null;
  return tipo >= 3 ? horaET(time).slice(11) : DIAS[new Date(time * 1000).getUTCDay()];
}

function aplicarFormatoFechas() {
  // Funciones nuevas en cada llamada para que el gráfico se redibuje con el modo actual.
  grafico.applyOptions({
    localization: { timeFormatter: (time) => textoMomento(time, estado.tf !== "1D") },
    timeScale: { tickMarkFormatter: (time, tipo) => marcaEje(time, tipo) },
  });
}

// Las llamadas que dependen del reloj del replay van en fila, para que una carga
// del gráfico y un avance del reloj no se crucen.
let cola = Promise.resolve();
function enSerie(tarea) {
  const resultado = cola.then(tarea);
  cola = resultado.catch(() => {});
  return resultado;
}

async function api(ruta, opciones) {
  const respuesta = await fetch(ruta, opciones);
  const datos = await respuesta.json();
  if (!respuesta.ok) {
    const detalle = Array.isArray(datos.detail) ? datos.detail.map((e) => e.msg).join("; ") : datos.detail;
    throw new Error(detalle ?? respuesta.statusText);
  }
  return datos;
}

function pedirVelas(hasta, desde) {
  const params = new URLSearchParams({ simbolo: estado.simbolo, tf: estado.tf });
  if (hasta) params.set("hasta", hasta);
  if (desde) params.set("desde", desde);
  return enSerie(() => api(`/api/velas?${params}`));
}

async function cargar() {
  const peticion = ++estado.peticion;
  for (const avisar of alRecargar) avisar();
  Object.assign(estado, { velas: [], completo: false, completoDerecha: estado.ancla === null, cargando: true });
  serie.setData([]);
  redibujarIndicadores();
  mostrarInfo("Cargando…");
  try {
    const datos = await pedirVelas(estado.ancla === null ? undefined : horaET(estado.ancla));
    if (peticion !== estado.peticion) return; // el usuario ya cambió de instrumento o timeframe
    estado.velas = datos.velas;
    estado.inicioDatos = datos.inicio_datos;
    serie.setData(estado.velas);
    redibujarIndicadores();
    if (estado.ancla === null) grafico.timeScale().scrollToRealTime();
    for (const avisar of alCargar) avisar();
  } catch (error) {
    mostrarInfo(error.message);
    return;
  } finally {
    if (peticion === estado.peticion) estado.cargando = false;
  }
  mostrarInfo();
}

// Al acercarse al borde izquierdo se pide la ventana anterior y se añade delante.
async function cargarAnteriores() {
  if (estado.cargando || estado.completo || !estado.velas.length) return;
  const peticion = estado.peticion;
  estado.cargando = true;
  try {
    const datos = await pedirVelas(horaET(estado.velas[0].time));
    if (peticion !== estado.peticion) return;
    // En 1D la etiqueta (00:00) es posterior al inicio real del día (18:00 de la víspera),
    // así que puede volver una vela ya mostrada: solo se añaden las anteriores.
    const anteriores = datos.velas.filter((v) => v.time < estado.velas[0].time);
    if (!anteriores.length) {
      estado.completo = true;
    } else {
      estado.velas = anteriores.concat(estado.velas);
      serie.setData(estado.velas);
      redibujarIndicadores();
      for (const avisar of alCargar) avisar();
    }
    mostrarInfo();
  } finally {
    if (peticion === estado.peticion) estado.cargando = false;
  }
}

// En modo backtest, al acercarse al borde derecho se pide el tramo siguiente. La última vela cargada
// puede estar a medias (`hasta` cae dentro de ella), así que se pide otra vez entera y se sustituye.
async function cargarPosteriores() {
  if (estado.cargando || estado.completoDerecha || !estado.velas.length) return;
  const peticion = estado.peticion;
  estado.cargando = true;
  try {
    const desde = estado.velas.at(-1).time;
    // Una ventana entera sin datos (festivo y fin de semana en 1m) no es el final: se prueba con la siguiente.
    let nuevas = [];
    for (let intento = 1; intento <= 4 && nuevas.length <= 1; intento++) {
      const hasta = desde + intento * DIAS_VENTANA[estado.tf] * 86400;
      const datos = await pedirVelas(horaET(hasta), horaET(desde));
      if (peticion !== estado.peticion) return;
      nuevas = datos.velas.filter((v) => v.time >= desde);
    }
    if (nuevas.length <= 1) estado.completoDerecha = true;
    if (nuevas.length) {
      estado.velas = estado.velas.slice(0, -1).concat(nuevas);
      serie.setData(estado.velas);
      redibujarIndicadores();
      for (const avisar of alCargar) avisar();
    }
    mostrarInfo();
  } finally {
    if (peticion === estado.peticion) estado.cargando = false;
  }
}

grafico.timeScale().subscribeVisibleLogicalRangeChange((rango) => {
  if (rango && rango.from < 20) cargarAnteriores();
  if (rango && rango.to > estado.velas.length - 20) cargarPosteriores();
});

function mostrarInfo(texto) {
  const info = document.getElementById("info");
  if (texto) {
    info.textContent = texto;
    return;
  }
  const { velas } = estado;
  if (!velas.length) {
    info.textContent = "Sin datos";
    return;
  }
  const conHora = estado.tf !== "1D"; // la vela diaria se etiqueta a las 00:00: la hora no dice nada
  const desde = textoMomento(velas[0].time, conHora);
  const hasta = textoMomento(velas.at(-1).time, conHora);
  info.textContent = `${velas.length.toLocaleString("es")} velas · ${desde} → ${hasta} (hora de Nueva York)`;
}

function crearBotones(contenedor, opciones, clave) {
  for (const opcion of opciones) {
    const boton = document.createElement("button");
    boton.textContent = opcion.etiqueta ?? opcion;
    boton.title = opcion.titulo ?? "";
    boton.dataset.valor = opcion.valor ?? opcion;
    boton.addEventListener("click", () => {
      if (estado[clave] === boton.dataset.valor) return;
      estado[clave] = boton.dataset.valor;
      marcar(contenedor, estado[clave]);
      cargar();
    });
    contenedor.append(boton);
  }
  marcar(contenedor, estado[clave]);
}

function marcar(contenedor, valor) {
  for (const boton of contenedor.children) {
    boton.setAttribute("aria-pressed", String(boton.dataset.valor === valor));
  }
}

async function iniciar() {
  const indicador = document.getElementById("estado");
  aplicarFormatoFechas();
  try {
    const [estadoApi, instrumentos] = await Promise.all([api("/api/estado"), api("/api/instrumentos")]);
    indicador.textContent = `Backend conectado · v${estadoApi.version}`;
    indicador.className = "estado estado--ok";

    crearBotones(
      document.getElementById("simbolos"),
      instrumentos.map((i) => ({ valor: i.simbolo, etiqueta: i.simbolo, titulo: i.nombre })),
      "simbolo",
    );
    crearBotones(document.getElementById("timeframes"), TIMEFRAMES, "tf");
    crearPanelIndicadores(); // indicadores.js
    prepararDibujo(); // dibujo.js
    await prepararReplay(); // replay.js
    cargar();
  } catch (error) {
    console.error(error);
    indicador.textContent = "Backend sin respuesta";
    indicador.className = "estado estado--error";
  }
}

// Los demás archivos se cargan después de este; se arranca cuando ya están todos.
document.addEventListener("DOMContentLoaded", iniciar);
