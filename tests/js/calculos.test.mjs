// Tests de frontend/calculos.js (spec 004). Se lanzan desde pytest (tests/test_frontend.py)
// o a mano con `node --test tests/js/`.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { test } from "node:test";

const require = createRequire(import.meta.url);
const c = require("../../frontend/calculos.js");

const MIN = 60;
// Domingo 2024-03-03 18:00 ET (inicio del día de trading del lunes 4), como segundos "UTC".
const DOMINGO_18H = Date.UTC(2024, 2, 3, 18, 0) / 1000;

function vela(time, close, extra = {}) {
  return { time, open: close, high: close + 1, low: close - 1, close, volume: 1, ...extra };
}

const cierres = (lista, inicio = DOMINGO_18H, paso = MIN) => lista.map((cierre, i) => vela(inicio + i * paso, cierre));
const valores = (nombre, parametro, velas) => c.calcular(c.INDICADORES[nombre](parametro), velas).valores;

function casi(real, esperado, tolerancia = 1e-9) {
  assert.equal(real.length, esperado.length);
  real.forEach((valor, i) => {
    if (esperado[i] === null) assert.equal(valor, null, `posición ${i}`);
    else assert.ok(Math.abs(valor - esperado[i]) < tolerancia, `posición ${i}: ${valor} ≠ ${esperado[i]}`);
  });
}

test("SMA a mano", () => {
  casi(valores("sma", 3, cierres([1, 2, 3, 4, 5, 9])), [null, null, 2, 3, 4, 6]);
});

test("EMA a mano: arranca con la SMA", () => {
  // α = 0,5. SMA(1, 2, 3) = 2; luego 0,5·4 + 0,5·2 = 3; 0,5·8 + 0,5·3 = 5,5.
  casi(valores("ema", 3, cierres([1, 2, 3, 4, 8])), [null, null, 2, 3, 5.5]);
});

test("RSI a mano (Wilder)", () => {
  // Cambios: +2, -1, +1, -2. Periodo 2: primeras medias (2+0)/2 = 1 y (0+1)/2 = 0,5 → RSI 66,67.
  // Luego subidas (1·1 + 1)/2 = 1, bajadas (0,5·1 + 0)/2 = 0,25 → 80.
  // Luego subidas (1 + 0)/2 = 0,5, bajadas (0,25 + 2)/2 = 1,125 → 30,77.
  const rsi = valores("rsi", 2, cierres([10, 12, 11, 12, 10]));
  casi(rsi, [null, null, 100 - 100 / 3, 80, 100 - 100 / (1 + 0.5 / 1.125)]);
});

test("RSI sin bajadas vale 100, y plano vale 50", () => {
  casi(valores("rsi", 2, cierres([1, 2, 3])), [null, null, 100]);
  casi(valores("rsi", 2, cierres([5, 5, 5])), [null, null, 50]);
});

test("ATR a mano (Wilder sobre el rango verdadero)", () => {
  const velas = [
    { time: 0, open: 10, high: 12, low: 9, close: 11, volume: 1 }, // rango 3
    { time: 60, open: 11, high: 15, low: 11, close: 14, volume: 1 }, // máx(4, 4, 0) = 4
    { time: 120, open: 14, high: 13, low: 10, close: 12, volume: 1 }, // máx(3, 1, 4) = 4 (hueco a la baja)
  ];
  // Periodo 2: (3 + 4)/2 = 3,5; luego (3,5·1 + 4)/2 = 3,75.
  casi(valores("atr", 2, velas), [null, 3.5, 3.75]);
});

test("VWAP pondera el precio típico y se reinicia al cambiar de día de trading", () => {
  const velas = [
    { time: DOMINGO_18H - 2 * MIN, high: 4, low: 2, close: 3, volume: 1 }, // día anterior: típico 3
    { time: DOMINGO_18H, high: 12, low: 9, close: 9, volume: 1 }, // día nuevo: típico 10
    { time: DOMINGO_18H + MIN, high: 22, low: 19, close: 19, volume: 3 }, // típico 20
  ];
  casi(valores("vwap", null, velas), [3, 10, (10 + 60) / 4]);
});

// Tres días de trading de 1m con huecos entre ellos (el viernes al domingo, como un fin de semana).
// Cada día: 18:00 → 16:14 con datos, con precios distintos por día para distinguir los niveles.
function tresDias() {
  const velas = [];
  const dias = [DOMINGO_18H - 3 * 86400, DOMINGO_18H, DOMINGO_18H + 86400]; // jueves, lunes, martes
  dias.forEach((inicio, d) => {
    for (let m = 0; m < 22 * 60 + 15; m += 1) {
      const base = 100 * (d + 1) + Math.sin(m / 50) * 10 + (m % 7);
      velas.push({ time: inicio + m * MIN, open: base, high: base + 2, low: base - 3, close: base + 1, volume: 1 + (m % 3) });
    }
  });
  return velas;
}

function agregar(velas, tf) {
  const salida = [];
  for (const v of velas) {
    const time = c.cubeta(v.time, tf);
    const ultima = salida.at(-1);
    if (ultima?.time === time) {
      ultima.high = Math.max(ultima.high, v.high);
      ultima.low = Math.min(ultima.low, v.low);
      ultima.close = v.close;
      ultima.volume += v.volume;
    } else {
      salida.push({ ...v, time });
    }
  }
  return salida;
}

test("Niveles del día anterior: exactos en 1m, 15m y 1h; el primer día cargado no cuenta", () => {
  const minutos = tresDias();
  const porDia = new Map();
  for (const v of minutos) {
    const dia = c.diaTrading(v.time);
    const d = porDia.get(dia) ?? { high: -Infinity, low: Infinity };
    porDia.set(dia, { high: Math.max(d.high, v.high), low: Math.min(d.low, v.low), close: v.close });
  }
  const [jueves, lunes, martes] = [...porDia.keys()];
  for (const tf of ["1m", "15m", "1h"]) {
    const velas = agregar(minutos, tf);
    const res = valores("diaAnterior", null, velas);
    velas.forEach((v, i) => {
      const dia = c.diaTrading(v.time);
      if (dia === jueves) {
        assert.equal(res[i], null, `${tf}: el primer día no tiene día anterior`);
        return;
      }
      // El jueves es el primer día cargado y puede estar incompleto: el lunes no tiene nivel.
      if (dia === lunes) {
        assert.equal(res[i], null, `${tf}: el día siguiente al primero cargado no tiene nivel`);
        return;
      }
      assert.equal(dia, martes);
      const esperado = porDia.get(lunes);
      assert.equal(res[i].high, esperado.high, `${tf} máximo`);
      assert.equal(res[i].low, esperado.low, `${tf} mínimo`);
      assert.equal(res[i].close, esperado.close, `${tf} cierre`);
    });
  }
});

test("Niveles overnight: máximo y mínimo de 18:00 a 9:30, iguales en 1m, 5m, 15m y 30m", () => {
  const minutos = tresDias();
  const esperado = new Map();
  for (const v of minutos) {
    const m = (v.time % 86400) / 60;
    if (m >= 18 * 60 || m < 9 * 60 + 30) {
      const dia = c.diaTrading(v.time);
      const d = esperado.get(dia) ?? { high: -Infinity, low: Infinity };
      esperado.set(dia, { high: Math.max(d.high, v.high), low: Math.min(d.low, v.low) });
    }
  }
  const primerDia = c.diaTrading(minutos[0].time);
  for (const tf of ["1m", "5m", "15m", "30m"]) {
    const velas = agregar(minutos, tf);
    const res = valores("overnight", null, velas);
    velas.forEach((v, i) => {
      const m = (v.time % 86400) / 60;
      const dia = c.diaTrading(v.time);
      const rth = m >= 9 * 60 + 30 && m < 18 * 60;
      if (!rth || dia === primerDia) {
        assert.equal(res[i], null, `${tf} ${m}`);
        return;
      }
      assert.deepEqual(res[i], esperado.get(dia), `${tf} ${m}`);
    });
  }
});

// Simula el replay: minutos de 1m que se van sumando a la vela en formación del timeframe.
for (const nombre of ["sma", "ema", "rsi", "atr", "vwap", "diaAnterior", "overnight"]) {
  test(`${nombre}: incremental = de cero, y las velas cerradas no cambian`, () => {
    const minutos = tresDias().slice(0, 3000);
    for (const tf of ["1m", "15m", "1h"]) {
      const indicador = c.INDICADORES[nombre](14);
      const velas = [];
      const resultado = { estados: [], valores: [] };
      for (const minuto of minutos) {
        const time = c.cubeta(minuto.time, tf);
        const ultima = velas.at(-1);
        const nueva = ultima?.time === time
          ? { time, open: ultima.open, high: Math.max(ultima.high, minuto.high), low: Math.min(ultima.low, minuto.low), close: minuto.close, volume: ultima.volume + minuto.volume }
          : { ...minuto, time };
        // La vela provisional da el mismo valor que guardarla de verdad.
        const provisional = c.valorProvisional(indicador, velas, resultado, nueva);
        const antes = resultado.valores.slice(0, -1);
        if (ultima?.time === time) velas[velas.length - 1] = nueva;
        else velas.push(nueva);
        c.actualizarDesde(indicador, velas, resultado, velas.length - 1);
        assert.deepEqual(resultado.valores.at(-1), provisional);
        assert.deepEqual(resultado.valores.slice(0, antes.length), antes, `${tf}: cambió una vela cerrada`);
      }
      assert.deepEqual(resultado.valores, c.calcular(indicador, velas).valores, tf);
    }
  });
}

test("Tiempo ↔ índice lógico: dentro, en huecos, a la derecha y a la izquierda de los datos", () => {
  // Velas de 15m con un hueco de 1 h entre la 2 y la 3.
  const t0 = DOMINGO_18H;
  const velas = [0, 15, 30, 90, 105].map((m) => vela(t0 + m * MIN, 100));
  assert.equal(c.tiempoALogico(velas, t0, "15m"), 0);
  assert.equal(c.tiempoALogico(velas, t0 + 20 * MIN, "15m"), 1); // dentro de la vela de las 18:15
  assert.equal(c.tiempoALogico(velas, t0 + 60 * MIN, "15m"), 2); // en el hueco: la vela anterior
  assert.equal(c.tiempoALogico(velas, t0 + 150 * MIN, "15m"), 7); // 3 velas después de la última (4)
  assert.equal(c.tiempoALogico(velas, t0 - 30 * MIN, "15m"), -2);
  for (const logico of [-3, 0, 1, 3, 4, 9]) {
    assert.equal(c.tiempoALogico(velas, c.logicoATiempo(velas, logico, "15m"), "15m"), logico);
  }
  assert.equal(c.logicoATiempo(velas, 2.4, "15m"), t0 + 30 * MIN);
  assert.equal(c.logicoATiempo(velas, 6, "15m"), t0 + 135 * MIN);
  assert.equal(c.tiempoALogico([], t0, "15m"), null);
});

test("Un instante en otro timeframe cae en la vela que lo contiene", () => {
  const minutos = tresDias();
  const t = minutos[700].time; // 05:40 del jueves
  for (const tf of ["1m", "15m", "1h", "4h", "1D"]) {
    const velas = agregar(minutos, tf);
    const i = c.tiempoALogico(velas, t, tf);
    assert.equal(velas[i].time, c.cubeta(t, tf), tf);
  }
});

test("SL y TP en dólares: el SL hacia dentro, el TP hacia fuera y un tick como mínimo", () => {
  const dosNQ = { multiplicador: 20, tick: 0.25, cantidad: 2 }; // 10 $ por tick
  assert.equal(c.puntosDesdeDolares(400, dosNQ, false), 10);
  assert.equal(c.puntosDesdeDolares(505, dosNQ, true), 12.75);
  assert.equal(c.puntosDesdeDolares(505, dosNQ, false), 12.5);
  assert.equal(c.puntosDesdeDolares(3, dosNQ, false), 0.25);
  const unMGC = { multiplicador: 10, tick: 0.1, cantidad: 1 }; // 1 $ por tick
  assert.equal(c.puntosDesdeDolares(37, unMGC, false), 3.7);
  const tresMES = { multiplicador: 5, tick: 0.25, cantidad: 3 }; // 3,75 $ por tick
  assert.equal(c.puntosDesdeDolares(100, tresMES, false), 6.5); // 26 ticks = 97,50 $
  assert.equal(c.puntosDesdeDolares(100, tresMES, true), 6.75); // 27 ticks = 101,25 $
  assert.equal(c.dolaresDesdePuntos(6.75, tresMES), 101.25);
  assert.equal(c.dolaresDesdePuntos(10, dosNQ), 400);
  assert.equal(c.dolaresDesdePuntos(3.7, unMGC), 37);
});

test("Fibonacci: retrocesos y extensiones de un impulso al alza (spec 012)", () => {
  const precios = (niveles) => niveles.map((n) => n.precio);
  assert.deepEqual(precios(c.fibonacciNiveles(100, 200, [0, 0.618, 0.786, 1])), [200, 138.2, 121.4, 100]);
  assert.deepEqual(precios(c.fibonacciExtensiones(100, 200, [1, 1.272, 1.618, 2.618])), [200, 227.2, 261.8, 361.8]);
});

test("Fibonacci: el impulso a la baja da los niveles simétricos", () => {
  const precios = (niveles) => niveles.map((n) => n.precio);
  assert.deepEqual(precios(c.fibonacciNiveles(200, 100, [0, 0.618, 0.786, 1])), [100, 161.8, 178.6, 200]);
  assert.deepEqual(precios(c.fibonacciExtensiones(200, 100, [1.618])), [38.2]);
  assert.equal(c.fibonacciNiveles(200, 100, [0.5])[0].valor, 0.5);
});
