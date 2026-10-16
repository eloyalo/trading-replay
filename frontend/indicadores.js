// Indicadores (spec 004): series de la librería, panel de configuración y leyenda. Los cálculos
// están en calculos.js y solo usan `estado.velas`, que en replay ya llega recortado al instante
// del reloj: ningún indicador ve el futuro.

const { LineSeries, HistogramSeries, LineStyle } = LightweightCharts;

const CONFIG_INICIAL = {
  medias: [
    { activa: false, tipo: "EMA", periodo: 9, color: "#f0b429" },
    { activa: false, tipo: "EMA", periodo: 21, color: "#ec407a" },
    { activa: false, tipo: "SMA", periodo: 200, color: "#e0e0e0" },
  ],
  vwap: { activa: false },
  volumen: { activa: true },
  rsi: { activa: false, periodo: 14 },
  atr: { activa: false, periodo: 14 },
  diaAnterior: { activa: false },
  overnight: { activa: false },
};

function leerConfig() {
  const guardada = preferencias.leer("indicadores", {});
  const config = structuredClone(CONFIG_INICIAL);
  config.medias.forEach((media, i) => Object.assign(media, guardada.medias?.[i]));
  for (const clave of Object.keys(config)) {
    if (clave !== "medias") Object.assign(config[clave], guardada[clave]);
  }
  return config;
}

const indicadores = {
  config: leerConfig(),
  activos: [], // indicadores con sus series, creados para el timeframe `tf`
  tf: null,
  puntos: 0, // puntos que tiene cada serie (incluida la vela provisional)
  cursor: null, // `time` de la vela bajo el cursor, o null
  provisional: null, // {vela, valores} con la vela provisional del movimiento simulado
};

// Volumen como "indicador": el valor es el volumen de la propia vela.
const VOLUMEN = { paso: (velas, i) => ({ estado: null, valor: velas[i].volume }) };

// Qué se dibuja para la configuración y el timeframe. Cada línea es una serie de la librería;
// `campo` elige la parte del valor cuando el indicador da varias (máximo, mínimo...).
function definir(config, tf) {
  const lista = [];
  const intradia = tf !== "1D";
  const nivel = (campo, nombre, colorLinea, estilo) => ({
    campo,
    nombre,
    opciones: { color: colorLinea, lineWidth: 1, lineStyle: estilo, crosshairMarkerVisible: false, lastValueVisible: false },
  });

  for (const media of config.medias) {
    if (!media.activa) continue;
    lista.push({
      nombre: `${media.tipo} ${media.periodo}`,
      calculo: INDICADORES[media.tipo.toLowerCase()](media.periodo),
      lineas: [{ opciones: { color: media.color, lineWidth: 2 } }],
    });
  }
  if (config.vwap.activa && intradia) {
    lista.push({
      nombre: "VWAP",
      calculo: INDICADORES.vwap(),
      cortarDias: true, // se reinicia cada día: sin raya vertical entre un día y otro
      lineas: [{ opciones: { color: color("--vwap"), lineWidth: 2 } }],
    });
  }
  if (config.diaAnterior.activa && intradia) {
    lista.push({
      nombre: "Día anterior",
      calculo: INDICADORES.diaAnterior(),
      cortarDias: true,
      lineas: [
        nivel("high", "Máx", color("--verde"), LineStyle.Dashed),
        nivel("low", "Mín", color("--rojo"), LineStyle.Dashed),
        nivel("close", "Cierre", color("--gris"), LineStyle.Dashed),
      ],
    });
  }
  if (config.overnight.activa && MINUTOS_TF[tf] <= 30) {
    lista.push({
      nombre: "Overnight",
      calculo: INDICADORES.overnight(),
      lineas: [
        nivel("high", "Máx", color("--ambar"), LineStyle.Dotted),
        nivel("low", "Mín", color("--ambar"), LineStyle.Dotted),
      ],
    });
  }
  if (config.volumen.activa) {
    lista.push({
      nombre: "Vol",
      calculo: VOLUMEN,
      volumen: true,
      lineas: [
        {
          tipo: HistogramSeries,
          colorVela: (vela) => (vela.close >= vela.open ? color("--verde-suave") : color("--rojo-suave")),
          opciones: { priceScaleId: "volumen", priceFormat: { type: "volume" }, lastValueVisible: false },
        },
      ],
    });
  }
  if (config.rsi.activa) {
    lista.push({
      nombre: `RSI ${config.rsi.periodo}`,
      calculo: INDICADORES.rsi(config.rsi.periodo),
      panelPropio: true,
      lineas: [
        {
          opciones: {
            color: color("--violeta"),
            lineWidth: 1,
            autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 100 } }),
          },
          niveles: [30, 70],
        },
      ],
    });
  }
  if (config.atr.activa) {
    lista.push({
      nombre: `ATR ${config.atr.periodo}`,
      calculo: INDICADORES.atr(config.atr.periodo),
      panelPropio: true,
      lineas: [{ opciones: { color: color("--azul-claro"), lineWidth: 1 } }],
    });
  }
  return lista;
}

function crearSeries() {
  for (const activo of indicadores.activos) {
    for (const linea of activo.lineas) grafico.removeSeries(linea.serie);
  }
  indicadores.tf = estado.tf;
  indicadores.activos = definir(indicadores.config, estado.tf);
  let panel = 0;
  for (const activo of indicadores.activos) {
    const enPanel = activo.panelPropio ? ++panel : 0;
    for (const linea of activo.lineas) {
      linea.serie = grafico.addSeries(
        linea.tipo ?? LineSeries,
        { priceLineVisible: false, priceFormat: serie.options().priceFormat, ...linea.opciones },
        enPanel,
      );
      if (activo.panelPropio) linea.serie.priceScale().applyOptions({ scaleMargins: { top: 0.1, bottom: 0.1 } });
      for (const precio of linea.niveles ?? []) {
        linea.serie.createPriceLine({ price: precio, color: color("--gris"), lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false });
      }
    }
    if (activo.volumen) {
      // Abajo del todo del panel de precio y por detrás de las velas.
      const volumen = activo.lineas[0].serie;
      volumen.priceScale().applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
      volumen.setSeriesOrder(0);
    }
  }
  // El precio se queda con la mayor parte de la altura.
  grafico.panes().forEach((p, i) => p.setStretchFactor(i === 0 ? 4 : 1));
}

const valorDe = (linea, valor) => (linea.campo ? valor?.[linea.campo] : valor);

// ¿Se corta la línea entre la vela `anterior` y `vela`? Sí si la segunda no tiene valor o, en los
// indicadores que se reinician cada día (VWAP, día anterior), si cambia el día de trading.
function hayCorte(activo, linea, anterior, vela, valor) {
  return valorDe(linea, valor) == null || (activo.cortarDias && diaTrading(anterior.time) !== diaTrading(vela.time));
}

// Punto de la serie para `vela`. Lightweight Charts une con una recta los puntos a los dos lados
// de un hueco, y cada tramo toma el color del punto donde empieza: para cortar la línea, el punto
// anterior al corte se pinta transparente.
function punto(activo, linea, vela, valor, corteDespues) {
  const { time } = vela;
  const value = valorDe(linea, valor);
  if (value == null) return { time };
  if (linea.colorVela) return { time, value, color: linea.colorVela(vela) };
  return corteDespues ? { time, value, color: "transparent" } : { time, value };
}

// Punto de la vela `i` de `velas`, mirando si la siguiente (si la hay) corta la línea.
function puntoEn(activo, linea, velas, valores, i) {
  const corte = i + 1 < velas.length && hayCorte(activo, linea, velas[i], velas[i + 1], valores[i + 1]);
  return punto(activo, linea, velas[i], valores[i], corte);
}

// Recalcula todo: al cargar el gráfico, al añadir historia o al cambiar la configuración.
function redibujarIndicadores() {
  indicadores.provisional = null;
  if (indicadores.tf !== estado.tf) crearSeries();
  const velas = estado.velas;
  for (const activo of indicadores.activos) {
    activo.resultado = calcular(activo.calculo, velas);
    const { valores } = activo.resultado;
    for (const linea of activo.lineas) linea.serie.setData(velas.map((_, i) => puntoEn(activo, linea, velas, valores, i)));
  }
  indicadores.puntos = velas.length;
  mostrarLeyenda();
}

// El replay ha cambiado o añadido velas a partir de la posición `desde` (siempre al final).
function actualizarIndicadores(desde) {
  indicadores.provisional = null;
  const velas = estado.velas;
  // Si se añaden velas, el último punto dibujado puede cambiar de color (corte). Solo se puede
  // tocar mientras siga siendo el último de la serie, es decir, antes de añadir los nuevos.
  const inicio = desde > 0 && desde === indicadores.puntos ? desde - 1 : desde;
  for (const activo of indicadores.activos) {
    actualizarDesde(activo.calculo, velas, activo.resultado, desde);
    const { valores } = activo.resultado;
    for (const linea of activo.lineas) {
      for (let i = inicio; i < velas.length; i++) linea.serie.update(puntoEn(activo, linea, velas, valores, i));
    }
  }
  indicadores.puntos = velas.length;
  mostrarLeyenda();
}

// Vela provisional del movimiento simulado: se dibuja sin guardarla.
function indicadoresProvisionales(vela) {
  const velas = estado.velas;
  const nueva = velas.at(-1)?.time !== vela.time;
  // Primer fotograma de una vela nueva: el último punto aún es el último de la serie.
  const retocarAnterior = nueva && velas.length > 0 && indicadores.puntos === velas.length;
  const valores = indicadores.activos.map((activo) => {
    const valor = valorProvisional(activo.calculo, velas, activo.resultado, vela);
    for (const linea of activo.lineas) {
      if (retocarAnterior) {
        const i = velas.length - 1;
        const corte = hayCorte(activo, linea, velas[i], vela, valor);
        linea.serie.update(punto(activo, linea, velas[i], activo.resultado.valores[i], corte));
      }
      linea.serie.update(punto(activo, linea, vela, valor, false));
    }
    return valor;
  });
  if (nueva) indicadores.puntos = velas.length + 1;
  indicadores.provisional = { vela, valores };
  mostrarLeyenda();
}

// --- Leyenda (RF-11) ---

const formatoPrecio = (x) => (x == null ? "—" : x.toFixed(2));

function mostrarLeyenda() {
  const velas = estado.velas;
  let vela = null;
  let valores = [];
  const i = indicadores.cursor === null ? -1 : indiceVela(velas, indicadores.cursor);
  if (i >= 0 && velas[i].time === indicadores.cursor) {
    vela = velas[i];
    valores = indicadores.activos.map((a) => a.resultado?.valores[i]);
  } else if (indicadores.provisional) {
    ({ vela, valores } = indicadores.provisional);
  } else if (velas.length) {
    vela = velas.at(-1);
    valores = indicadores.activos.map((a) => a.resultado?.valores.at(-1));
  }

  const leyenda = document.getElementById("leyenda");
  leyenda.replaceChildren();
  const fila = (...partes) => {
    const div = document.createElement("div");
    for (const [texto, clase, estilo] of partes) {
      const span = document.createElement("span");
      span.textContent = texto;
      if (clase) span.className = clase;
      if (estilo) span.style.color = estilo;
      div.append(span);
    }
    leyenda.append(div);
  };
  if (!vela) return;
  const tono = vela.close >= vela.open ? color("--verde") : color("--rojo");
  fila(
    [`${estado.simbolo} · ${estado.tf}`, "leyenda__titulo"],
    ["A"], [formatoPrecio(vela.open), "", tono],
    ["Máx"], [formatoPrecio(vela.high), "", tono],
    ["Mín"], [formatoPrecio(vela.low), "", tono],
    ["C"], [formatoPrecio(vela.close), "", tono],
  );
  indicadores.activos.forEach((activo, k) => {
    const valor = valores[k];
    const partes = [[activo.nombre, "leyenda__titulo"]];
    for (const linea of activo.lineas) {
      if (linea.nombre) partes.push([linea.nombre]);
      partes.push([formatoPrecio(valorDe(linea, valor)), "", linea.colorVela ? tono : linea.opciones.color]);
    }
    fila(...partes);
  });
}

grafico.subscribeCrosshairMove((parametros) => {
  indicadores.cursor = parametros.time ?? null;
  mostrarLeyenda();
});

// --- Panel de configuración (RF-10) ---

function guardarConfig() {
  preferencias.guardar("indicadores", indicadores.config);
  crearSeries();
  redibujarIndicadores();
}

function crearPanelIndicadores() {
  const panel = document.getElementById("panel-indicadores");
  const boton = document.getElementById("boton-indicadores");
  const { config } = indicadores;

  const casilla = (objeto, texto, ...extras) => {
    const fila = document.createElement("label");
    fila.className = "panel__fila";
    const marca = document.createElement("input");
    marca.type = "checkbox";
    marca.checked = objeto.activa;
    marca.addEventListener("change", () => {
      objeto.activa = marca.checked;
      guardarConfig();
    });
    const nombre = document.createElement("span");
    nombre.textContent = texto;
    fila.append(marca, nombre, ...extras);
    panel.append(fila);
  };
  const periodo = (objeto) => {
    const campo = document.createElement("input");
    Object.assign(campo, { type: "number", min: 1, max: 500, step: 1, value: objeto.periodo, title: "Periodo" });
    campo.addEventListener("change", () => {
      const valor = Math.round(Number(campo.value));
      if (!(valor >= 1 && valor <= 500)) {
        campo.value = objeto.periodo;
        return;
      }
      objeto.periodo = valor;
      guardarConfig();
    });
    return campo;
  };
  const titulo = (texto) => {
    const h = document.createElement("h3");
    h.textContent = texto;
    panel.append(h);
  };

  titulo("Medias móviles");
  for (const media of config.medias) {
    const tipo = document.createElement("select");
    tipo.title = "Tipo de media";
    for (const t of ["EMA", "SMA"]) tipo.add(new Option(t, t));
    tipo.value = media.tipo;
    tipo.addEventListener("change", () => {
      media.tipo = tipo.value;
      guardarConfig();
    });
    const colorMedia = document.createElement("input");
    Object.assign(colorMedia, { type: "color", value: media.color, title: "Color" });
    colorMedia.addEventListener("change", () => {
      media.color = colorMedia.value;
      guardarConfig();
    });
    casilla(media, "", tipo, periodo(media), colorMedia);
  }
  titulo("Sobre el precio");
  casilla(config.vwap, "VWAP (diario, no en 1D)");
  casilla(config.volumen, "Volumen (de ticks)");
  casilla(config.diaAnterior, "Día anterior: máximo, mínimo y cierre");
  casilla(config.overnight, "Overnight: máximo y mínimo (hasta 30m)");
  titulo("En panel propio");
  casilla(config.rsi, "RSI", periodo(config.rsi));
  casilla(config.atr, "ATR", periodo(config.atr));

  const alternar = (abrir = panel.hidden) => {
    panel.hidden = !abrir;
    boton.setAttribute("aria-pressed", String(abrir));
  };
  boton.addEventListener("click", () => alternar());
  document.addEventListener("mousedown", (evento) => {
    if (!panel.hidden && !panel.contains(evento.target) && !boton.contains(evento.target)) alternar(false);
  });
  cancelaciones.push(() => {
    if (panel.hidden) return false;
    alternar(false);
    return true;
  });
}
