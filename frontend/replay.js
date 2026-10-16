// Replay (spec 003). El reloj vive en el backend: aquí se le pide avanzar y se dibujan
// los minutos de 1m que devuelve, sumándolos a la vela en formación del timeframe activo.

const VELOCIDADES = [1, 2, 3, 5, 10, 60, 300, 1000];
const MAX_VELOCIDAD_SIMULADA = 10; // por encima, cada minuto dura 1 s o menos y no se simula
const MS_POR_PASO_SIMULADO = 250; // cada cuánto se mueve el precio simulado
const MAX_MINUTOS_POR_PETICION = 500; // como `replay.MAX_MINUTOS` en el backend

const replay = {
  activo: false,
  instante: null, // segundos, hora ET como si fuera UTC (igual que `time` de las velas)
  fin: false,
  jugando: false,
  velocidad: preferencias.leer("velocidad", 1),
  modo: preferencias.leer("modo", "real"),
  enVuelo: false, // nunca hay más de un avance pendiente
  reloj: { inicio: 0, hechos: 0 }, // minutos pedidos desde que empezó el play (modo real)
  animacion: null, // minuto que se está dibujando en modo simulado
};

const $ = (id) => document.getElementById(id);
const aSegundos = (iso) => Date.parse(`${iso}Z`) / 1000;

// Vela del timeframe activo que resulta de sumar `minuto` a la última del gráfico, sin guardarla.
// `cubeta()` está en calculos.js y replica la alineación de `almacen.consultar`.
function combinar(minuto) {
  const time = cubeta(minuto.time, estado.tf);
  const ultima = estado.velas.at(-1);
  if (!ultima || ultima.time !== time) return { ...minuto, time };
  return {
    time,
    open: ultima.open,
    high: Math.max(ultima.high, minuto.high),
    low: Math.min(ultima.low, minuto.low),
    close: minuto.close,
    volume: Math.round((ultima.volume + minuto.volume) * 1e4) / 1e4,
  };
}

function aplicarMinutos(minutos) {
  const tocadas = [];
  for (const minuto of minutos) {
    const vela = combinar(minuto);
    const ultima = estado.velas.at(-1);
    if (ultima && vela.time < ultima.time) continue; // no debería pasar: el reloj solo avanza
    if (ultima && vela.time === ultima.time) estado.velas[estado.velas.length - 1] = vela;
    else estado.velas.push(vela);
    if (tocadas.at(-1)?.time === vela.time) tocadas[tocadas.length - 1] = vela;
    else tocadas.push(vela);
  }
  if (tocadas.length > 200) {
    serie.setData(estado.velas);
    redibujarIndicadores();
  } else if (tocadas.length) {
    for (const vela of tocadas) serie.update(vela);
    actualizarIndicadores(estado.velas.length - tocadas.length);
  }
  if (tocadas.length) mostrarInfo();
  if (previaVisible()) actualizarPrevia(); // operativa.js: el SL y el TP previstos siguen al precio
}

async function avanzar(cuerpo) {
  const peticion = estado.peticion;
  const datos = await enSerie(() =>
    api("/api/replay/avanzar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ simbolo: estado.simbolo, ...cuerpo }),
    }),
  );
  replay.instante = aSegundos(datos.instante);
  replay.fin = datos.fin;
  mostrarReloj();
  actualizarCuenta(datos.cuenta, datos.ejecuciones); // operativa.js
  // Si el gráfico se ha recargado mientras tanto, la recarga ya incluye estos minutos.
  return peticion === estado.peticion ? datos.velas : [];
}

async function paso(cuerpo) {
  if (replay.enVuelo) return;
  replay.enVuelo = true;
  try {
    aplicarMinutos(await avanzar(cuerpo));
    if (replay.fin) pausar();
  } catch (error) {
    pausar();
    mostrarAviso(error.message);
  } finally {
    replay.enVuelo = false;
  }
}

// --- Play ---

const simulando = () => replay.modo === "simulado" && replay.velocidad <= MAX_VELOCIDAD_SIMULADA;

function bucle(ahora) {
  if (!replay.jugando) return;
  const msPorMinuto = 60000 / replay.velocidad;
  if (simulando()) {
    animar(ahora, msPorMinuto);
  } else {
    if (replay.animacion) terminarAnimacion();
    const debidos = Math.floor((ahora - replay.reloj.inicio) / msPorMinuto) - replay.reloj.hechos;
    if (debidos > 0 && !replay.enVuelo) {
      // Si el equipo va lento, los minutos atrasados se piden juntos en vez de acumular retraso.
      const minutos = Math.min(debidos, MAX_MINUTOS_POR_PETICION);
      replay.reloj.hechos += minutos;
      paso({ minutos });
    }
  }
  requestAnimationFrame(bucle);
}

function reiniciarReloj() {
  replay.reloj = { inicio: performance.now(), hechos: 0 };
}

function jugar() {
  if (!replay.activo || replay.jugando || replay.fin) return;
  replay.jugando = true;
  reiniciarReloj();
  const animacion = replay.animacion;
  if (animacion) animacion.inicio = performance.now() - animacion.transcurrido;
  actualizarControles();
  requestAnimationFrame(bucle);
}

function pausar() {
  if (!replay.jugando) return;
  replay.jugando = false;
  const animacion = replay.animacion;
  if (animacion) animacion.transcurrido = performance.now() - animacion.inicio;
  actualizarControles();
}

const alternarPlay = () => (replay.jugando ? pausar() : jugar());

// --- Movimiento simulado dentro del minuto (RF-9) ---
// Se pide el minuto al empezarlo y se dibuja poco a poco: apertura → extremo más cercano →
// otro extremo → cierre, con algo de ruido. El último fotograma es siempre la vela real.

function animar(ahora, msPorMinuto) {
  const animacion = replay.animacion;
  if (!animacion) {
    if (replay.enVuelo || replay.fin) return;
    replay.enVuelo = true;
    avanzar({ minutos: 1 })
      .then((velas) => {
        if (velas.length) replay.animacion = nuevaAnimacion(velas[0]);
        else if (replay.fin) pausar();
        mostrarReloj();
      })
      .catch((error) => {
        pausar();
        mostrarAviso(error.message);
      })
      .finally(() => (replay.enVuelo = false));
    return;
  }
  const transcurrido = ahora - animacion.inicio;
  if (transcurrido >= msPorMinuto) {
    terminarAnimacion();
    if (replay.fin) pausar();
    return;
  }
  const pasoActual = Math.floor(transcurrido / MS_POR_PASO_SIMULADO);
  if (pasoActual === animacion.paso) return;
  animacion.paso = pasoActual;
  const precio = precioSimulado(animacion.vela, transcurrido / msPorMinuto);
  animacion.alto = Math.max(animacion.alto, precio);
  animacion.bajo = Math.min(animacion.bajo, precio);
  const { time, open } = animacion.vela;
  const vela = combinar({ time, open, high: animacion.alto, low: animacion.bajo, close: precio, volume: 0 });
  serie.update(vela);
  indicadoresProvisionales(vela);
  if (previaVisible()) actualizarPrevia();
}

function nuevaAnimacion(vela) {
  return { vela, inicio: performance.now(), transcurrido: 0, paso: -1, alto: vela.open, bajo: vela.open };
}

function terminarAnimacion() {
  const { vela } = replay.animacion;
  replay.animacion = null;
  aplicarMinutos([vela]);
  mostrarReloj();
}

// Precio inventado en la fracción `p` (0 a 1) del minuto, siempre dentro del rango real de la vela.
function precioSimulado({ open, high, low, close }, p) {
  const [primero, segundo] = open - low < high - open ? [low, high] : [high, low];
  const puntos = [open, primero, segundo, close];
  const tramos = [1, 2, 3].map((i) => Math.abs(puntos[i] - puntos[i - 1]));
  const total = tramos.reduce((a, b) => a + b, 0);
  if (!total) return open;
  let recorrido = p * total;
  let precio = close;
  for (let i = 0; i < 3; i++) {
    if (recorrido <= tramos[i]) {
      const fraccion = tramos[i] ? recorrido / tramos[i] : 1;
      precio = puntos[i] + (puntos[i + 1] - puntos[i]) * fraccion;
      break;
    }
    recorrido -= tramos[i];
  }
  const ruido = (Math.random() - 0.5) * 0.15 * (high - low);
  return Math.min(high, Math.max(low, precio + ruido));
}

// --- Acciones ---

async function empezar(cuerpo) {
  if (!confirmarSalto("empezar")) return; // operativa.js: con algo abierto, segundo clic
  pausar();
  mostrarAviso();
  try {
    const datos = await enSerie(() =>
      api("/api/replay", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ simbolo: estado.simbolo, ...cuerpo }),
      }),
    );
    entrar(datos.instante);
    borrarTodosLosDibujos(); // spec 004, RF-6
    cargar();
    trasSalto(datos);
  } catch (error) {
    mostrarAviso(error.message);
  }
}

function entrar(instante) {
  Object.assign(replay, { activo: true, instante: aSegundos(instante), fin: false, animacion: null });
  document.body.classList.add("en-replay");
  actualizarControles();
}

const momentoAleatorio = () => empezar({ aleatorio: true, sesion: $("sesion").value });

function irAFecha() {
  const valor = $("fecha").value;
  if (!valor) {
    mostrarAviso("Elige fecha y hora (hora de Nueva York)");
    return;
  }
  empezar({ inicio: valor });
}

function siguienteVela() {
  if (!replay.activo || replay.fin) return;
  pausar();
  if (replay.animacion) terminarAnimacion();
  paso({ tf: estado.tf });
}

async function salir() {
  if (!replay.activo || !confirmarSalto("salir")) return;
  pausar();
  mostrarAviso();
  const datos = await enSerie(() => api("/api/replay", { method: "DELETE" })).catch(() => null);
  Object.assign(replay, { activo: false, instante: null, fin: false, animacion: null });
  document.body.classList.remove("en-replay");
  actualizarControles();
  cargar();
  trasSalto(datos);
}

// --- Interfaz ---

function mostrarReloj() {
  const reloj = $("reloj");
  if (!replay.activo) {
    reloj.textContent = "";
    return;
  }
  // En modo simulado el backend ya ha pasado el minuto que se está dibujando: se muestra ese minuto.
  const instante = replay.animacion ? replay.animacion.vela.time : replay.instante;
  const fin = replay.fin && !replay.animacion ? " · fin de los datos" : "";
  reloj.textContent = textoMomento(instante) + fin;
}

function mostrarAviso(texto = "") {
  const aviso = $("aviso");
  aviso.textContent = texto;
  aviso.classList.toggle("aviso--error", Boolean(texto));
  if (!texto && replay.activo && simulando()) aviso.textContent = "Precio simulado dentro del minuto";
}

function actualizarControles() {
  const play = $("play");
  play.textContent = replay.jugando ? "⏸ Pausa" : "▶ Play";
  play.setAttribute("aria-pressed", String(replay.jugando));
  play.disabled = replay.fin;
  $("siguiente").disabled = replay.fin;
  mostrarReloj();
  if (!$("aviso").classList.contains("aviso--error")) mostrarAviso();
}

function cambiarCiego(ciego) {
  estado.ciego = ciego;
  preferencias.guardar("ciego", ciego);
  aplicarFormatoFechas();
  mostrarInfo();
  mostrarReloj();
  mostrarHistorial(); // operativa.js: sin fecha en modo a ciegas (spec 005, RF-21)
}

function crearOpciones(select, opciones, valor) {
  for (const [valorOpcion, texto] of opciones) select.add(new Option(texto, valorOpcion));
  select.value = String(valor);
}

const esCampo = (elemento) => elemento.closest?.("input, select, textarea");

function atajo(evento) {
  if (hayVentana()) return; // con una ventana abierta, el teclado es suyo (Esc la cierra)
  if (evento.key === "Escape" && cancelaciones.some((cancelar) => cancelar())) {
    evento.preventDefault();
    return;
  }
  if (evento.ctrlKey || evento.metaKey || evento.altKey || esCampo(evento.target)) return;
  const acciones = {
    ArrowRight: replay.activo && siguienteVela,
    " ": replay.activo && alternarPlay,
    r: momentoAleatorio,
    R: momentoAleatorio,
    Escape: replay.activo && salir,
  };
  const accion = acciones[evento.key];
  if (!accion) return;
  evento.preventDefault();
  // Si el foco está en un botón, Espacio lo pulsaría además de hacer el atajo.
  if (evento.target instanceof HTMLButtonElement) evento.target.blur();
  accion();
}

// Prepara los controles y retoma el replay si el backend tiene uno en marcha (por ejemplo, tras recargar).
async function prepararReplay() {
  crearOpciones(
    $("velocidad"),
    VELOCIDADES.map((v) => [v, v === 1 ? "Tiempo real (1x)" : `${v}x`]),
    replay.velocidad,
  );
  crearOpciones(
    $("modo"),
    [
      ["real", "Movimiento real"],
      ["simulado", "Movimiento simulado"],
    ],
    replay.modo,
  );
  $("ciego").checked = estado.ciego;

  $("aleatorio").addEventListener("click", momentoAleatorio);
  $("ir").addEventListener("click", irAFecha);
  $("siguiente").addEventListener("click", siguienteVela);
  $("play").addEventListener("click", alternarPlay);
  $("salir").addEventListener("click", salir);
  $("ciego").addEventListener("change", (e) => cambiarCiego(e.target.checked));
  $("velocidad").addEventListener("change", (e) => {
    replay.velocidad = Number(e.target.value);
    preferencias.guardar("velocidad", replay.velocidad);
    reiniciarReloj();
    actualizarControles();
  });
  $("modo").addEventListener("change", (e) => {
    replay.modo = e.target.value;
    preferencias.guardar("modo", replay.modo);
    reiniciarReloj();
    actualizarControles();
  });
  document.addEventListener("keydown", atajo);
  // Al recargar el gráfico (cambio de timeframe o de instrumento) el minuto animado ya viene incluido.
  alRecargar.push(() => {
    replay.animacion = null;
    mostrarReloj();
  });

  const enCurso = await api("/api/replay");
  if (enCurso.activo) entrar(enCurso.instante);
  else actualizarControles();
  await prepararOperativa(); // operativa.js
  prepararRetos(); // retos.js
}
