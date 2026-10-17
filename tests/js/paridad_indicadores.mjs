// Calcula indicadores con frontend/calculos.js para el test de paridad con Python
// (tests/test_backtest_indicadores.py). Lee {velas, indicadores} por la entrada estándar y escribe
// los valores de cada indicador en la salida. No es un test por sí mismo: no acaba en .test.mjs.
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const c = require("../../frontend/calculos.js");

const { velas, indicadores } = JSON.parse(readFileSync(0, "utf8"));
const resultado = {};
for (const [clave, nombre, parametro] of indicadores) {
  resultado[clave] = c.calcular(c.INDICADORES[nombre](parametro), velas).valores;
}
process.stdout.write(JSON.stringify(resultado));
