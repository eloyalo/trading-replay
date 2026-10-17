// Retos de prop firm (spec 006): panel del reto, ventanas de aprobado (con confeti) y de suspendido,
// resumen de todas las cuentas y tipo de cuenta al crearla. La línea de liquidación está en operativa.js.

const NOMBRE_ESTADO = { en_curso: "En curso", aprobado: "Aprobado", suspendido: "Suspendido" };
const NOMBRE_RESULTADO = { aprobado: "Aprobado", suspendido: "Suspendido", abandonado: "Abandonado" };
const TIPO_PERDIDA = {
  estatica: ["fija", "No se mueve nunca"],
  trailing_cierre: ["trailing al cierre", "Sube con el balance al cierre de cada día y no baja"],
  trailing_intradia: ["trailing intradía", "Sube con el balance en vivo más alto, con lo abierto, y no baja"],
};
const COLORES_CONFETI = ["--verde", "--rojo", "--ambar", "--azul", "--violeta", "--azul-claro", "--texto"];
const MS_CONFETI = 6000;

const porcentaje = (x, decimales = 1) => `${(x * 100).toLocaleString("es", { maximumFractionDigits: decimales })} %`;

function crear(etiqueta, clase = "", texto) {
  const elemento = document.createElement(etiqueta);
  if (clase) elemento.className = clase;
  if (texto !== undefined) elemento.textContent = texto;
  return elemento;
}

// filas: [término, valor, clase del valor, título]
function cifras(filas) {
  const lista = crear("dl", "cifras");
  for (const [termino, valor, clase, titulo] of filas) {
    const dd = crear("dd", clase || "", valor);
    if (titulo) dd.title = titulo;
    lista.append(crear("dt", "", termino), dd);
  }
  return lista;
}

function progreso(fraccion, etiqueta) {
  const barra = crear("div", "progreso");
  barra.setAttribute("role", "progressbar");
  barra.setAttribute("aria-label", etiqueta);
  barra.setAttribute("aria-valuenow", String(Math.round(fraccion * 100)));
  const relleno = crear("div", "progreso__relleno");
  relleno.style.width = `${Math.min(100, Math.max(0, fraccion * 100))}%`;
  barra.append(relleno);
  return barra;
}

const chipEstado = (estadoReto) => crear("span", `chip chip--${estadoReto}`, NOMBRE_ESTADO[estadoReto]);

// --- Textos ---

const plural = (n, una, varias) => `${n} ${n === 1 ? una : varias}`;

function textoFalta(r) {
  if (r.estado === "aprobado") return `Aprobado. ${r.motivo}.`;
  if (r.estado === "suspendido") return `Suspendido. ${r.motivo}.`;
  const partes = [];
  if (r.falta > 0) partes.push(formatoSaldo(r.falta));
  if (r.faltan_dias > 0) partes.push(plural(r.faltan_dias, "día válido", "días válidos"));
  if (!partes.length) return "Objetivo cumplido: se aprueba al cerrar el día (al saltar o salir del replay).";
  return `Para aprobar te faltan ${partes.join(" y ")}.`;
}

// La regla de consistencia con los números de la cuenta (RF-21).
function textoConsistencia(r) {
  const c = r.consistencia;
  if (!c) return [];
  const regla = porcentaje(c.porcentaje, 0);
  if (c.mejor_dia <= 0) {
    return [`Ningún día puede ser más del ${regla} del beneficio total. Todavía no tienes ningún día en positivo.`];
  }
  const lineas = [];
  if (c.porcentaje_mejor !== null) {
    lineas.push(`Mejor día ${formatoDinero(c.mejor_dia)} = ${porcentaje(c.porcentaje_mejor)} de tu beneficio (${formatoDinero(r.beneficio)}).`);
  } else {
    lineas.push(`Mejor día ${formatoDinero(c.mejor_dia)}, con un beneficio total de ${formatoDinero(r.beneficio)}.`);
  }
  if (c.falta > 0) {
    lineas.push(
      `Con la regla del ${regla} necesitas ${formatoDinero(c.beneficio_necesario)} en total: te faltan ${formatoDinero(c.falta)}, en días distintos del mejor.`,
    );
  } else {
    lineas.push(`Cumples la regla del ${regla}: con este beneficio, tu mejor día puede llegar a ${formatoSaldo(c.maximo_mejor_dia)}.`);
  }
  if (c.sube_objetivo) lineas.push(`Por eso el objetivo sube de ${formatoSaldo(r.objetivo)} a ${formatoSaldo(r.objetivo_efectivo)}.`);
  return lineas;
}

function textoDiasValidos(r) {
  const minimo = r.beneficio_minimo_dia ? ` (con al menos ${formatoSaldo(r.beneficio_minimo_dia)} de beneficio)` : "";
  return `${r.dias_validos} de ${r.dias_minimos}${minimo}`;
}

// --- Panel del reto (RF-15) ---

function mostrarReto() {
  const panel = $("panel-reto");
  const r = operativa.cuenta?.reto;
  panel.hidden = !r;
  if (!r) return;
  const cabecera = crear("div", "reto__cabecera");
  cabecera.append(crear("h3", "", r.intento > 1 ? `${r.titulo} · intento ${r.intento}` : r.titulo), chipEstado(r.estado));
  const objetivo = r.objetivo_efectivo > r.objetivo ? `${formatoSaldo(r.objetivo_efectivo)}*` : formatoSaldo(r.objetivo_efectivo);
  const filas = [
    ["Beneficio", `${formatoDinero(r.beneficio)} de ${objetivo}`, tono(r.beneficio), r.objetivo_efectivo > r.objetivo ? "Objetivo subido por la regla de consistencia" : ""],
    ["Margen hasta la pérdida máxima", formatoSaldo(r.distancia), r.distancia < r.perdida_maxima * 0.25 ? "negativo" : "", `Umbral: ${formatoSaldo(r.umbral)}`],
  ];
  if (r.pnl_dia !== null) {
    const limite = r.limite_diario ? ` de −${formatoSaldo(r.limite_diario)}` : "";
    filas.push(["Hoy", `${formatoDinero(r.pnl_dia)}${limite}`, tono(r.pnl_dia)]);
  }
  filas.push(["Día del reto", String(r.dia)], ["Días válidos", `${r.dias_validos} de ${r.dias_minimos}`]);
  const c = r.consistencia;
  if (c && c.mejor_dia > 0) {
    const excede = c.porcentaje_mejor === null || c.porcentaje_mejor > c.porcentaje;
    const valor = c.porcentaje_mejor === null ? formatoDinero(c.mejor_dia) : `${formatoDinero(c.mejor_dia)} · ${porcentaje(c.porcentaje_mejor, 0)}`;
    filas.push(["Mejor día", valor, excede ? "negativo" : "", `Máximo: el ${porcentaje(c.porcentaje, 0)} del beneficio`]);
  }
  if (r.contratos_maximos) filas.push(["Contratos", `${r.contratos_en_uso.toLocaleString("es")} de ${r.contratos_maximos}`]);
  const piezas = [cabecera, progreso(r.objetivo_efectivo ? r.beneficio / r.objetivo_efectivo : 0, "Progreso hacia el objetivo"), cifras(filas)];
  const falta = crear("p", "reto__falta", textoFalta(r));
  piezas.push(falta);
  if (r.bloqueo) piezas.push(crear("p", "reto__bloqueo", r.bloqueo));
  panel.replaceChildren(...piezas);
}

// --- Eventos: aprobado, suspendido, pausa y hora de cierre (RF-17, RF-20) ---

function atenderEventos(eventos) {
  if (!eventos?.length) return;
  pausar(); // replay.js
  for (const evento of eventos) {
    if (evento.tipo === "aprobado" || evento.tipo === "suspendido") abrirVentanaReto(evento);
    else mostrarAviso(evento.mensaje);
  }
}

function abrirVentanaReto(evento) {
  const aprobado = evento.tipo === "aprobado";
  const ventana = $("ventana-reto");
  ventana.className = `ventana ventana--${evento.tipo}`;
  const titulo = crear("h2", "", aprobado ? "¡Reto aprobado!" : "Reto suspendido");
  titulo.id = "titulo-reto";
  ventana.setAttribute("aria-labelledby", titulo.id);
  const piezas = [crear("div", "ventana__icono", aprobado ? "🏆" : "✕"), titulo];
  const reto = operativa.cuenta?.reto;
  if (evento.perfil || reto) piezas.push(crear("p", "ventana__subtitulo", evento.perfil || reto.titulo));
  piezas.push(crear("p", "", `${evento.mensaje}.`));
  if (aprobado) {
    piezas.push(
      cifras([
        ["Beneficio", formatoDinero(evento.beneficio), "positivo"],
        ["Días", String(evento.dias)],
        ["Mejor día", formatoDinero(evento.mejor_dia)],
      ]),
    );
  } else {
    piezas.push(cifras([["Balance", formatoSaldo(evento.balance)]]));
  }
  const botones = crear("div", "ventana__botones");
  const nuevo = crear("button", "boton-principal", "Nuevo intento");
  nuevo.type = "button";
  nuevo.title = "Reinicia la cuenta: el intento queda en el historial";
  nuevo.addEventListener("click", async () => {
    ventana.close();
    await cambiarCuenta(undefined, `/api/cuentas/${operativa.cuenta.id}/reiniciar`, "POST"); // operativa.js
  });
  const cerrar = crear("button", "", "Cerrar");
  cerrar.type = "button";
  cerrar.addEventListener("click", () => ventana.close());
  botones.append(nuevo, cerrar);
  piezas.push(botones);
  $("ventana-reto-contenido").replaceChildren(...piezas);
  if (!ventana.open) ventana.showModal();
  cerrar.focus();
  if (aprobado) lanzarConfeti($("confeti"));
}

// Confeti sin librerías: piezas de colores que caen girando sobre toda la pantalla.
function lanzarConfeti(lienzo) {
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const escala = devicePixelRatio || 1;
  const ancho = innerWidth;
  const alto = innerHeight;
  lienzo.width = ancho * escala;
  lienzo.height = alto * escala;
  const ctx = lienzo.getContext("2d");
  ctx.scale(escala, escala);
  const colores = COLORES_CONFETI.map(color);
  const piezas = Array.from({ length: 240 }, (_, i) => {
    // La mitad cae desde arriba y la otra mitad sale disparada desde las esquinas de abajo.
    const desdeAbajo = i % 2 === 1;
    const izquierda = i % 4 === 1;
    return {
      x: desdeAbajo ? (izquierda ? 0 : ancho) : Math.random() * ancho,
      y: desdeAbajo ? alto : -20 - Math.random() * alto * 0.5,
      vx: desdeAbajo ? (izquierda ? 1 : -1) * (3 + Math.random() * 7) : (Math.random() - 0.5) * 3,
      vy: desdeAbajo ? -(10 + Math.random() * 9) : 2 + Math.random() * 3,
      giro: Math.random() * Math.PI * 2,
      velocidadGiro: (Math.random() - 0.5) * 0.3,
      tamano: 6 + Math.random() * 7,
      color: colores[i % colores.length],
    };
  });
  const inicio = performance.now();
  let anterior = inicio;
  const cuadro = (ahora) => {
    const t = ahora - inicio;
    // La física va en pasos de 1/60 s: se mueve igual con pantallas de 60 o 120 Hz y si se pierden cuadros.
    const pasos = Math.min(30, Math.round((ahora - anterior) / (1000 / 60)));
    anterior = ahora;
    ctx.clearRect(0, 0, ancho, alto);
    ctx.globalAlpha = Math.min(1, Math.max(0, (MS_CONFETI - t) / 1000));
    for (const p of piezas) {
      for (let i = 0; i < pasos; i++) {
        p.vy = Math.min(p.vy + 0.25, 6);
        p.vx *= 0.985;
        p.x += p.vx;
        p.y += p.vy;
        p.giro += p.velocidadGiro;
      }
      ctx.save();
      ctx.translate(p.x, p.y);
      ctx.rotate(p.giro);
      ctx.fillStyle = p.color;
      ctx.fillRect(-p.tamano / 2, -p.tamano / 4, p.tamano, (p.tamano / 2) * Math.abs(Math.cos(p.giro)) + 1);
      ctx.restore();
    }
    if (t < MS_CONFETI) requestAnimationFrame(cuadro);
    else ctx.clearRect(0, 0, ancho, alto);
  };
  requestAnimationFrame(cuadro);
}

// --- Resumen de cuentas (RF-21) ---

async function abrirResumen() {
  const ventana = $("ventana-cuentas");
  $("cuentas-aviso").textContent = "";
  mostrarNuevaCuenta(false);
  if (!ventana.open) ventana.showModal();
  await pintarResumen();
}

async function pintarResumen() {
  const contenedor = $("tarjetas-cuentas");
  try {
    const tarjetas = await enSerie(() => api("/api/cuentas/resumen"));
    contenedor.replaceChildren(...tarjetas.map(tarjetaCuenta));
  } catch (error) {
    $("cuentas-aviso").textContent = error.message;
  }
}

async function usarCuenta(id) {
  try {
    await pedir(`/api/cuentas/${id}`, "PATCH", { activa: true }); // operativa.js
    $("cuentas-aviso").textContent = "";
  } catch (error) {
    $("cuentas-aviso").textContent = error.message;
  }
  await pintarResumen();
  await mostrarCuentas(); // operativa.js: selector de cuenta del panel de operar
  await refrescarCuenta();
}

// Nueva cuenta desde el resumen (RF-22): la crea, la deja activa y la enseña en la lista.
function mostrarNuevaCuenta(visible) {
  const formulario = $("resumen-nueva");
  formulario.hidden = !visible;
  $("boton-nueva-cuenta").setAttribute("aria-expanded", String(visible));
  if (!visible) return;
  formulario.reset();
  $("resumen-nueva-tipo").dispatchEvent(new Event("change"));
  $("resumen-nueva-tipo").focus();
}

async function crearDesdeResumen() {
  const aviso = $("cuentas-aviso");
  const cuerpo = cuerpoNuevaCuenta("resumen-nueva"); // operativa.js
  if (!cuerpo) {
    aviso.textContent = "La cuenta nueva necesita nombre y balance inicial";
    return;
  }
  try {
    await pedir("/api/cuentas", "POST", cuerpo); // operativa.js
  } catch (error) {
    aviso.textContent = error.message;
    return;
  }
  aviso.textContent = "";
  mostrarNuevaCuenta(false);
  await pintarResumen();
  document.querySelector("#tarjetas-cuentas .tarjeta--activa")?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  await mostrarCuentas(); // operativa.js: selector de cuenta del panel de operar
  await refrescarCuenta();
}

function seccion(titulo, ...hijos) {
  const caja = crear("section", "tarjeta__seccion");
  caja.append(crear("h4", "", titulo), ...hijos);
  return caja;
}

function tarjetaCuenta(t) {
  const r = t.reto;
  const tarjeta = crear("article", `tarjeta${t.activa ? " tarjeta--activa" : ""}`);
  const cabecera = crear("header", "tarjeta__cabecera");
  const nombre = crear("div", "tarjeta__nombre");
  nombre.append(crear("h3", "", t.nombre));
  if (r) {
    const perfil = [r.titulo === t.nombre ? "" : r.titulo, r.intento > 1 ? `intento ${r.intento}` : ""].filter(Boolean).join(" · ");
    if (perfil) nombre.append(crear("span", "tarjeta__perfil", perfil));
  }
  cabecera.append(nombre);
  if (r) cabecera.append(chipEstado(r.estado));
  if (t.activa) {
    cabecera.append(crear("span", "chip chip--activa", "Activa"));
  } else {
    const usar = crear("button", "", "Usar");
    usar.type = "button";
    usar.title = "Operar con esta cuenta";
    usar.addEventListener("click", () => usarCuenta(t.id));
    cabecera.append(usar);
  }
  tarjeta.append(cabecera);

  const acierto = t.acierto === null ? "—" : `${porcentaje(t.acierto, 0)} (${t.ganadoras} de ${t.operaciones})`;
  const filas = [
    ["Balance", formatoSaldo(t.balance)],
    ["Beneficio", `${formatoDinero(t.beneficio)} · ${porcentaje(t.rentabilidad, 2)}`, tono(t.beneficio)],
    ["Operaciones", String(t.operaciones)],
    ["Acierto", acierto],
  ];
  if (t.mayor_ganancia > 0) filas.push(["Mayor ganancia", formatoDinero(t.mayor_ganancia), "positivo"]);
  if (t.mayor_perdida < 0) filas.push(["Mayor pérdida", formatoDinero(t.mayor_perdida), "negativo"]);
  if (t.operaciones) filas.push(["Comisiones", formatoSaldo(t.comisiones)]);
  filas.push(["Días operados", String(t.dias_operados)]);
  tarjeta.append(cifras(filas));
  if (r) tarjeta.append(...seccionesReto(r, t.intentos));
  return tarjeta;
}

function seccionesReto(r, intentos) {
  const piezas = [];
  const fraccion = r.objetivo_efectivo ? r.beneficio / r.objetivo_efectivo : 0;
  piezas.push(progreso(fraccion, "Progreso hacia el objetivo"), crear("p", `tarjeta__falta tarjeta__falta--${r.estado}`, textoFalta(r)));

  const reglas = [
    ["Objetivo", r.objetivo_efectivo > r.objetivo ? `${formatoSaldo(r.objetivo_efectivo)} (era ${formatoSaldo(r.objetivo)})` : formatoSaldo(r.objetivo)],
    ["Pérdida máxima", `${formatoSaldo(r.perdida_maxima)} · ${TIPO_PERDIDA[r.tipo_perdida][0]}`, "", TIPO_PERDIDA[r.tipo_perdida][1]],
    ["Umbral actual", formatoSaldo(r.umbral)],
    ["Margen", formatoSaldo(r.distancia), r.distancia < r.perdida_maxima * 0.25 ? "negativo" : ""],
    ["Límite diario", r.limite_diario ? formatoSaldo(r.limite_diario) : "no tiene"],
    ["Días válidos", textoDiasValidos(r)],
  ];
  if (r.contratos_maximos) reglas.push(["Contratos", `hasta ${r.contratos_maximos} (o ${r.contratos_maximos * 10} micros)`]);
  if (r.hora_cierre) reglas.push(["Cierre obligatorio", `${r.hora_cierre} ET`]);
  piezas.push(seccion("Reglas", cifras(reglas)));

  const consistencia = textoConsistencia(r);
  if (consistencia.length) {
    piezas.push(seccion(`Consistencia (${porcentaje(r.consistencia.porcentaje, 0)})`, ...consistencia.map((linea) => crear("p", "", linea))));
  }

  const dias = crear("ol", "lista dias");
  for (const d of r.dias) {
    const fila = crear("li");
    const marca = d.valido ? "válido" : "no válido";
    fila.append(crear("span", "", `Día ${d.numero}${d.en_curso ? " (en curso)" : ""}`), crear("span", "dias__marca", marca), crear("span", `cifra ${tono(d.pnl)}`, formatoDinero(d.pnl)));
    dias.append(fila);
  }
  if (!r.dias.length) dias.append(crear("li", "vacia", "Todavía no has operado en este reto"));
  piezas.push(seccion("Días", dias));

  if (intentos.length) {
    const lista = crear("ul", "lista");
    for (const intento of intentos) {
      const fila = crear("li");
      const texto = `Intento ${intento.numero} · ${NOMBRE_RESULTADO[intento.resultado]} · ${plural(intento.dias, "día", "días")}`;
      fila.append(crear("span", "", texto), crear("span", `cifra ${tono(intento.beneficio)}`, formatoDinero(intento.beneficio)));
      if (intento.motivo) fila.title = intento.motivo;
      lista.append(fila);
    }
    piezas.push(seccion("Intentos anteriores", lista));
  }
  return piezas;
}

// --- Tipo de cuenta nueva (RF-3), en el panel de operar y en el resumen de cuentas ---

async function prepararTiposDeCuenta() {
  let lista;
  try {
    lista = await api("/api/perfiles");
  } catch (error) {
    mostrarAviso(error.message);
    return;
  }
  const porEmpresa = Map.groupBy(lista, (p) => p.empresa);
  for (const prefijo of ["nueva", "resumen-nueva"]) {
    const selector = $(`${prefijo}-tipo`);
    for (const [empresa, deEmpresa] of porEmpresa) {
      const grupo = document.createElement("optgroup");
      grupo.label = empresa;
      grupo.append(...deEmpresa.map((p) => new Option(`${p.nombre} · ${formatoSaldo(p.balance_inicial)}`, p.id)));
      selector.append(grupo);
    }
    selector.addEventListener("change", () => {
      const perfil = lista.find((p) => p.id === selector.value);
      $(`${prefijo}-balance`).disabled = Boolean(perfil);
      $(`${prefijo}-balance`).value = perfil ? perfil.balance_inicial : 50000;
      $(`${prefijo}-nombre`).placeholder = perfil ? perfil.titulo : "Reto 50k";
    });
  }
}

function prepararRetos() {
  $("boton-resumen-cuentas").addEventListener("click", abrirResumen);
  $("boton-nueva-cuenta").addEventListener("click", () => mostrarNuevaCuenta($("resumen-nueva").hidden));
  $("cancelar-nueva-cuenta").addEventListener("click", () => mostrarNuevaCuenta(false));
  $("resumen-nueva").addEventListener("submit", (evento) => {
    evento.preventDefault();
    crearDesdeResumen();
  });
  for (const ventana of document.querySelectorAll("dialog.ventana")) {
    // Clic en el fondo oscuro, fuera del recuadro: se cierra.
    ventana.addEventListener("click", (evento) => {
      const caja = ventana.getBoundingClientRect();
      const dentro = evento.clientX >= caja.left && evento.clientX <= caja.right && evento.clientY >= caja.top && evento.clientY <= caja.bottom;
      if (evento.target === ventana && !dentro) ventana.close();
    });
    for (const boton of ventana.querySelectorAll("[data-cerrar]")) boton.addEventListener("click", () => ventana.close());
  }
  prepararTiposDeCuenta();
  mostrarReto();
}
