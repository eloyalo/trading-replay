// Cálculos puros, sin DOM: alineación de velas, indicadores (spec 004) y conversión entre
// tiempo e índice lógico del gráfico. Se carga en el navegador y también en Node para los tests.

// Minutos de cada timeframe, como `almacen.TIMEFRAMES` en el backend.
const MINUTOS_TF = { "1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1D": 1440 };
const SEIS_HORAS = 6 * 3600;
const UN_DIA = 86400;
const FIN_OVERNIGHT = 9 * 60 + 30; // 9:30 ET, apertura de la sesión de Nueva York
const INICIO_DIA = 18 * 60; // 18:00 ET, inicio del día de trading

// Inicio de la vela de `tf` que contiene el minuto `t`. Misma regla que `almacen.consultar`:
// 4h y 1D se alinean a las 18:00 ET y la vela diaria se etiqueta con la fecha del día de trading.
// `t` es la hora ET expresada en segundos como si fuera UTC, igual que `time` de las velas.
function cubeta(t, tf) {
  const segundos = MINUTOS_TF[tf] * 60;
  if (tf === "1D") return Math.floor((t + SEIS_HORAS) / UN_DIA) * UN_DIA;
  if (segundos >= 4 * 3600) return Math.floor((t + SEIS_HORAS) / segundos) * segundos - SEIS_HORAS;
  return Math.floor(t / segundos) * segundos;
}

// Número del día de trading (empieza a las 18:00 ET de la víspera).
const diaTrading = (t) => Math.floor((t + SEIS_HORAS) / UN_DIA);
const minutoDelDia = (t) => Math.floor((t % UN_DIA) / 60);

// --- Indicadores ---
// Cada indicador tiene `paso(velas, i, previo)`, que calcula la vela `i` a partir del estado
// que dejó la `i - 1` (`previo`, null en la primera) y devuelve `{valor, estado}`. `valor` es un
// número, un objeto con varias líneas o null si todavía no hay valor. Nunca modifica `previo`.

const INDICADORES = {
  sma(periodo) {
    return {
      paso(velas, i, previo) {
        const sale = i >= periodo ? velas[i - periodo].close : 0;
        const suma = (previo?.suma ?? 0) + velas[i].close - sale;
        return { estado: { suma }, valor: i >= periodo - 1 ? suma / periodo : null };
      },
    };
  },

  // Arranca con la SMA de las `periodo` primeras velas.
  ema(periodo) {
    const alfa = 2 / (periodo + 1);
    return {
      paso(velas, i, previo) {
        const cierre = velas[i].close;
        if (i < periodo) {
          const suma = (previo?.suma ?? 0) + cierre;
          const ema = i === periodo - 1 ? suma / periodo : null;
          return { estado: { suma, ema }, valor: ema };
        }
        const ema = alfa * cierre + (1 - alfa) * previo.ema;
        return { estado: { ema }, valor: ema };
      },
    };
  },

  // Wilder: arranca con la media simple de las `periodo` primeras subidas y bajadas.
  rsi(periodo) {
    return {
      paso(velas, i, previo) {
        if (i === 0) return { estado: { subidas: 0, bajadas: 0 }, valor: null };
        const cambio = velas[i].close - velas[i - 1].close;
        const sube = Math.max(cambio, 0);
        const baja = Math.max(-cambio, 0);
        let { subidas, bajadas } = previo;
        if (i < periodo) return { estado: { subidas: subidas + sube, bajadas: bajadas + baja }, valor: null };
        if (i === periodo) {
          subidas = (subidas + sube) / periodo;
          bajadas = (bajadas + baja) / periodo;
        } else {
          subidas = (subidas * (periodo - 1) + sube) / periodo;
          bajadas = (bajadas * (periodo - 1) + baja) / periodo;
        }
        const valor = bajadas === 0 ? (subidas === 0 ? 50 : 100) : 100 - 100 / (1 + subidas / bajadas);
        return { estado: { subidas, bajadas }, valor };
      },
    };
  },

  // Wilder sobre el rango verdadero: arranca con la media simple de los `periodo` primeros.
  atr(periodo) {
    return {
      paso(velas, i, previo) {
        const { high, low } = velas[i];
        const anterior = i ? velas[i - 1].close : null;
        const rango = i ? Math.max(high - low, Math.abs(high - anterior), Math.abs(low - anterior)) : high - low;
        if (i < periodo) {
          const suma = (previo?.suma ?? 0) + rango;
          const atr = i === periodo - 1 ? suma / periodo : null;
          return { estado: { suma, atr }, valor: atr };
        }
        const atr = (previo.atr * (periodo - 1) + rango) / periodo;
        return { estado: { atr }, valor: atr };
      },
    };
  },

  // Precio típico ponderado por volumen, desde el inicio del día de trading.
  vwap() {
    return {
      paso(velas, i, previo) {
        const { time, high, low, close, volume } = velas[i];
        const dia = diaTrading(time);
        const tipico = (high + low + close) / 3;
        const mismoDia = previo?.dia === dia;
        const pv = (mismoDia ? previo.pv : 0) + tipico * volume;
        const vol = (mismoDia ? previo.vol : 0) + volume;
        return { estado: { dia, pv, vol }, valor: vol > 0 ? pv / vol : tipico };
      },
    };
  },

  // Máximo, mínimo y cierre del día de trading anterior con datos. El primer día cargado puede
  // estar incompleto (la ventana empieza a mitad de día), así que no sirve de "día anterior".
  diaAnterior() {
    return {
      paso(velas, i, previo) {
        const { time, high, low, close } = velas[i];
        const dia = diaTrading(time);
        let hoy, anterior;
        if (previo?.dia === dia) {
          hoy = { high: Math.max(previo.hoy.high, high), low: Math.min(previo.hoy.low, low), close, completo: previo.hoy.completo };
          anterior = previo.anterior;
        } else {
          hoy = { high, low, close, completo: previo !== null };
          anterior = previo?.hoy.completo ? previo.hoy : null;
        }
        const valor = anterior && { high: anterior.high, low: anterior.low, close: anterior.close };
        return { estado: { dia, hoy, anterior }, valor };
      },
    };
  },

  // Máximo y mínimo de 18:00 a 9:30 ET, con valor desde las 9:30 hasta el final del día.
  // Solo es exacto en timeframes de 30m o menos (la vela que contiene las 9:30 empieza a las 9:30).
  overnight() {
    return {
      paso(velas, i, previo) {
        const { time, high, low } = velas[i];
        const dia = diaTrading(time);
        const minuto = minutoDelDia(time);
        const enOvernight = minuto >= INICIO_DIA || minuto < FIN_OVERNIGHT;
        const mismoDia = previo?.dia === dia;
        let alto = mismoDia ? previo.alto : null;
        let bajo = mismoDia ? previo.bajo : null;
        const completo = mismoDia ? previo.completo : previo !== null;
        if (enOvernight) {
          alto = alto === null ? high : Math.max(alto, high);
          bajo = bajo === null ? low : Math.min(bajo, low);
        }
        const valor = !enOvernight && completo && alto !== null ? { high: alto, low: bajo } : null;
        return { estado: { dia, alto, bajo, completo }, valor };
      },
    };
  },
};

// Resultado de un indicador sobre `velas`: `{estados, valores}`, uno por vela.
function calcular(indicador, velas) {
  const resultado = { estados: [], valores: [] };
  actualizarDesde(indicador, velas, resultado, 0);
  return resultado;
}

// Recalcula `resultado` desde la vela `desde` hasta el final (las anteriores no cambian).
function actualizarDesde(indicador, velas, resultado, desde) {
  const { estados, valores } = resultado;
  estados.length = Math.min(desde, estados.length);
  valores.length = estados.length;
  for (let i = estados.length; i < velas.length; i++) {
    const { estado, valor } = indicador.paso(velas, i, i ? estados[i - 1] : null);
    estados.push(estado);
    valores.push(valor);
  }
}

// Valor que tendría el indicador si la última vela fuese `vela` (o si se añadiera, cuando empieza
// después de la última). No guarda nada: es para la vela provisional del movimiento simulado.
function valorProvisional(indicador, velas, resultado, vela) {
  const ultima = velas.length - 1;
  const i = ultima >= 0 && velas[ultima].time === vela.time ? ultima : ultima + 1;
  const original = velas[i];
  velas[i] = vela;
  try {
    return indicador.paso(velas, i, i ? resultado.estados[i - 1] : null).valor;
  } finally {
    if (i === ultima) velas[i] = original;
    else velas.length = ultima + 1;
  }
}

// --- Tiempo ↔ índice lógico (para los dibujos) ---
// El índice lógico es la posición de la vela en el gráfico (0 la primera). A la derecha de la
// última vela, o a la izquierda de la primera, se extrapola con la duración de la vela.

// Índice de la última vela que empieza antes o en `t` (-1 si no hay ninguna).
function indiceVela(velas, t) {
  let bajo = 0;
  let alto = velas.length - 1;
  let encontrado = -1;
  while (bajo <= alto) {
    const medio = (bajo + alto) >> 1;
    if (velas[medio].time <= t) {
      encontrado = medio;
      bajo = medio + 1;
    } else {
      alto = medio - 1;
    }
  }
  return encontrado;
}

function tiempoALogico(velas, t, tf) {
  if (!velas.length) return null;
  const duracion = MINUTOS_TF[tf] * 60;
  const inicio = cubeta(t, tf);
  const ultima = velas.length - 1;
  if (inicio > velas[ultima].time) return ultima + (inicio - velas[ultima].time) / duracion;
  if (inicio < velas[0].time) return (inicio - velas[0].time) / duracion;
  return indiceVela(velas, inicio);
}

// Inversa de `tiempoALogico`, redondeando a la vela más cercana.
function logicoATiempo(velas, logico, tf) {
  if (!velas.length) return null;
  const duracion = MINUTOS_TF[tf] * 60;
  const i = Math.round(logico);
  const ultima = velas.length - 1;
  if (i < 0) return velas[0].time + i * duracion;
  if (i > ultima) return velas[ultima].time + (i - ultima) * duracion;
  return velas[i].time;
}

// --- SL y TP en dólares (spec 005, RF-23) ---
// La cantidad en dólares es para toda la orden y en bruto. El precio va en ticks: el SL se redondea
// hacia dentro (nunca se arriesga más de lo escrito) y el TP hacia fuera (nunca se gana menos),
// con un tick como mínimo. Se trabaja en céntimos para no arrastrar errores de coma flotante.

function puntosDesdeDolares(dolares, { multiplicador, tick, cantidad }, haciaFuera) {
  const centimosPorTick = Math.round(multiplicador * tick * cantidad * 100);
  const ticks = Math.round(dolares * 100) / centimosPorTick;
  const redondeados = haciaFuera ? Math.ceil(ticks - 1e-9) : Math.floor(ticks + 1e-9);
  return Math.round(Math.max(redondeados, 1) * tick * 100) / 100;
}

function dolaresDesdePuntos(puntos, { multiplicador, tick, cantidad }) {
  const ticks = Math.round(puntos / tick);
  return (ticks * Math.round(multiplicador * tick * cantidad * 100)) / 100;
}

if (typeof module !== "undefined") {
  module.exports = {
    MINUTOS_TF,
    cubeta,
    diaTrading,
    INDICADORES,
    calcular,
    actualizarDesde,
    valorProvisional,
    indiceVela,
    tiempoALogico,
    logicoATiempo,
    puntosDesdeDolares,
    dolaresDesdePuntos,
  };
}
