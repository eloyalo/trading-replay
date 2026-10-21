// Tests de frontend/estudio_calculos.js (spec 010). Se lanzan desde pytest (tests/test_frontend.py)
// o a mano con `node --test tests/js/`.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { test } from "node:test";

const require = createRequire(import.meta.url);
const e = require("../../frontend/estudio_calculos.js");

const DIA = 86400;
const velas = [10, 11, 12, 13, 14].map((c, i) => ({ time: i * DIA, open: c - 0.5, high: c + 1, low: c - 1, close: c }));

test("progreso de un paso", () => {
  assert.equal(e.progresoPaso({ t: 2, duracion: 4 }, 1), 0);
  assert.equal(e.progresoPaso({ t: 2, duracion: 4 }, 4), 0.5);
  assert.equal(e.progresoPaso({ t: 2, duracion: 4 }, 9), 1);
  assert.equal(e.progresoPaso({ t: 2, duracion: 0 }, 2), 1);
});

test("suavizado empieza en 0, acaba en 1 y es simétrico", () => {
  assert.equal(e.suavizar(0), 0);
  assert.equal(e.suavizar(1), 1);
  assert.ok(Math.abs(e.suavizar(0.5) - 0.5) < 1e-12);
});

test("posición lógica interpolada y extrapolada", () => {
  assert.equal(e.logico(velas, 2 * DIA, DIA), 2);
  assert.equal(e.logico(velas, 2.5 * DIA, DIA), 2.5);
  assert.equal(e.logico(velas, 7 * DIA, DIA), 7);
  assert.equal(e.logico(velas, -DIA, DIA), -1);
});

test("vela en formación: recorre apertura, extremo cercano, el otro y cierre", () => {
  const v = { time: 0, open: 10, high: 14, low: 9, close: 13 };
  // Ruta 10 → 9 → 14 → 13: tramos 1 + 5 + 1 = 7.
  assert.deepEqual(e.velaEnFormacion(v, 1 / 7), { time: 0, open: 10, high: 10, low: 9, close: 9 });
  const mitad = e.velaEnFormacion(v, 3.5 / 7);
  assert.equal(mitad.low, 9);
  assert.equal(mitad.close, 11.5);
  assert.equal(mitad.high, 11.5);
  assert.deepEqual(e.velaEnFormacion(v, 1), v);
});

test("velas visibles con revelar", () => {
  const pasos = [{ accion: "revelar", t: 1, duracion: 4, desde: DIA, hasta: 4 * DIA }];
  assert.deepEqual(e.velasVisibles(velas, pasos, 0), { completas: 2, parcial: null });
  const medio = e.velasVisibles(velas, pasos, 2.5); // 2 + 3 * 0.375 = 3.125
  assert.equal(medio.completas, 3);
  assert.ok(medio.parcial && medio.parcial.time === 3 * DIA);
  assert.deepEqual(e.velasVisibles(velas, pasos, 10), { completas: 5, parcial: null });
  assert.deepEqual(e.velasVisibles(velas, [], 0), { completas: 5, parcial: null });
});

test("la vista se calcula igual en cualquier orden (determinista)", () => {
  const base = { logico: { from: 0, to: 10 }, precio: { from: 0, to: 100 } };
  const camaras = [{ t: 1, duracion: 2, vista: { logico: { from: 4, to: 6 }, precio: null } }];
  const a = e.vistaEn(base, camaras, 2);
  e.vistaEn(base, camaras, 5);
  assert.deepEqual(e.vistaEn(base, camaras, 2), a);
  assert.deepEqual(a.logico, { from: 2, to: 8 });
  assert.deepEqual(a.precio, base.precio);
});

test("opacidad con ocultar", () => {
  const ocultar = [{ t: 2, duracion: 1, objetivos: ["x"] }];
  assert.equal(e.opacidad("x", ocultar, 1), 1);
  assert.equal(e.opacidad("x", ocultar, 2.5), 0.5);
  assert.equal(e.opacidad("y", ocultar, 9), 1);
});

test("trazo de pincel hasta un progreso", () => {
  const puntos = [[0, 10, 0], [DIA, 12, 0.5], [2 * DIA, 11, 1]];
  assert.deepEqual(e.trazoHasta(puntos, 0.25), [[0, 10, 0], [DIA / 2, 11, 0.25]]);
  assert.equal(e.trazoHasta(puntos, 1).length, 3);
});

test("rango de precio con margen y precios extra", () => {
  const r = e.rangoPrecio(velas, 0, 1, [20], 0);
  assert.deepEqual(r, { from: 9, to: 20 });
});

// --- Widgets (spec 011) ---
const LIBRO = { asks: [[50.01, 200], [50.02, 500], [50.03, 300]], bids: [[50.0, 400], [49.99, 600], [49.98, 300]] };

test("compra a mercado de 900 en el libro de L1-01", () => {
  const r = e.ejecutar(LIBRO, "compra", 900);
  assert.deepEqual(r.ejecuciones, [[50.01, 200], [50.02, 500], [50.03, 200]]);
  assert.equal(r.ultimo, 50.03);
  assert.ok(Math.abs(r.medio - 50.02) < 1e-9);
  assert.deepEqual(r.libro.asks, [[50.01, 0], [50.02, 0], [50.03, 100]]);
  assert.deepEqual(LIBRO.asks[0], [50.01, 200]); // no modifica el libro original
});

test("venta a mercado de 700", () => {
  const r = e.ejecutar(LIBRO, "venta", 700);
  assert.deepEqual(r.ejecuciones, [[50.0, 400], [49.99, 300]]);
  assert.equal(r.ultimo, 49.99);
});

test("libro a mitad de una orden, igual en cualquier orden de instantes", () => {
  const pasos = [{ accion: "orden", t: 1, duracion: 2, lado: "compra", cantidad: 900 }];
  const medio = e.libroEn(LIBRO, pasos, 2); // 450 ejecutadas
  e.libroEn(LIBRO, pasos, 3);
  assert.deepEqual(e.libroEn(LIBRO, pasos, 2), medio);
  assert.deepEqual(medio.asks.map((n) => n.cantidad), [0, 250, 300]);
  assert.equal(medio.asks[1].original, 500);
  assert.equal(medio.orden.ultimo, 50.02);
  assert.equal(e.libroEn(LIBRO, pasos, 0).orden, null);
});

test("dos órdenes encadenadas", () => {
  const pasos = [
    { accion: "orden", t: 0, duracion: 0, lado: "compra", cantidad: 300 },
    { accion: "orden", t: 1, duracion: 0, lado: "compra", cantidad: 300 },
  ];
  assert.deepEqual(e.libroEn(LIBRO, pasos, 5).asks.map((n) => n.cantidad), [0, 100, 300]);
});

test("tramos de una misma orden se acumulan (grupo)", () => {
  const pasos = [
    { accion: "orden", t: 0, duracion: 1, lado: "compra", cantidad: 200, grupo: "o1" },
    { accion: "orden", t: 2, duracion: 1, lado: "compra", cantidad: 500, grupo: "o1" },
    { accion: "orden", t: 4, duracion: 1, lado: "compra", cantidad: 200, grupo: "o1" },
  ];
  const fin = e.libroEn(LIBRO, pasos, 9).orden;
  assert.deepEqual(fin.ejecuciones, [[50.01, 200], [50.02, 500], [50.03, 200]]);
  assert.ok(Math.abs(fin.medio - 50.02) < 1e-9);
  assert.equal(fin.ultimo, 50.03);
});
