const { createChart, CandlestickSeries } = LightweightCharts;

const TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "4h", "1D"];

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
  timeScale: { timeVisible: true, secondsVisible: false },
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
};

const horaET = (time) => new Date(time * 1000).toISOString().slice(0, 16);

async function pedirVelas(hasta) {
  const params = new URLSearchParams({ simbolo: estado.simbolo, tf: estado.tf });
  if (hasta) params.set("hasta", hasta);
  const respuesta = await fetch(`/api/velas?${params}`);
  const datos = await respuesta.json();
  if (!respuesta.ok) throw new Error(datos.detail ?? respuesta.statusText);
  return datos;
}

async function cargar() {
  const peticion = ++estado.peticion;
  Object.assign(estado, { velas: [], completo: false, cargando: true });
  serie.setData([]);
  mostrarInfo("Cargando…");
  try {
    const datos = await pedirVelas();
    if (peticion !== estado.peticion) return; // el usuario ya cambió de instrumento o timeframe
    estado.velas = datos.velas;
    estado.inicioDatos = datos.inicio_datos;
    serie.setData(estado.velas);
    grafico.timeScale().scrollToRealTime();
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
    }
    mostrarInfo();
  } finally {
    if (peticion === estado.peticion) estado.cargando = false;
  }
}

grafico.timeScale().subscribeVisibleLogicalRangeChange((rango) => {
  if (rango && rango.from < 20) cargarAnteriores();
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
  const desde = horaET(velas[0].time).replace("T", " ");
  const hasta = horaET(velas.at(-1).time).replace("T", " ");
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
  try {
    const [estadoApi, instrumentos] = await Promise.all([
      fetch("/api/estado").then((r) => r.json()),
      fetch("/api/instrumentos").then((r) => r.json()),
    ]);
    indicador.textContent = `Backend conectado · v${estadoApi.version}`;
    indicador.className = "estado estado--ok";

    crearBotones(
      document.getElementById("simbolos"),
      instrumentos.map((i) => ({ valor: i.simbolo, etiqueta: i.simbolo, titulo: i.nombre })),
      "simbolo",
    );
    crearBotones(document.getElementById("timeframes"), TIMEFRAMES, "tf");
    cargar();
  } catch {
    indicador.textContent = "Backend sin respuesta";
    indicador.className = "estado estado--error";
  }
}

iniciar();
