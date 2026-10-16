# 005 · Plan técnico

Referencia: [spec.md](spec.md)

## Enfoque

El motor de órdenes vive en el backend y avanza con el reloj del replay: cada vez que el replay avanza, los minutos nuevos de cada instrumento con órdenes o posiciones pasan por el motor, en orden cronológico. El frontend solo envía órdenes y enseña el estado que devuelve el backend.

Tres capas:

1. **`operativa/motor.py`: motor puro**, sin disco ni HTTP. Recibe órdenes y minutos y lleva posiciones, operaciones y balance. Es lo que se testea a fondo.
2. **`operativa/bd.py`: persistencia** en SQLite (`datos/cuentas.sqlite`, ADR 0001).
3. **`operativa/servicio.py`: servicio**: carga el motor de la cuenta activa, lo conecta con la sesión de replay, guarda los cambios y arma el resumen para la API. Un cerrojo hace atómicos el avance del reloj y las órdenes.

### Precios en ticks

Todo se calcula en ticks enteros para no arrastrar errores de coma flotante:

- `bid = round(precio_cfd / tick)`, `ask = bid + spread_ticks`.
- Los precios de las órdenes se ajustan al tick más cercano al recibirlas.
- El PnL se calcula en dólares con `(salida − entrada) × multiplicador × cantidad`, redondeado al céntimo. El precio medio de una posición con varias entradas puede quedar fuera de la rejilla; es normal.

### Ejecución en un minuto `m` (apertura `o`, máximo `h`, mínimo `l`)

| Orden | Se ejecuta si | Precio |
|---|---|---|
| Compra límite `P` | `ask_o ≤ P` (hueco) / `ask_l ≤ P` | `ask_o` / `P` |
| Venta límite `P` | `bid_o ≥ P` / `bid_h ≥ P` | `bid_o` / `P` |
| Compra stop `P` | `ask_o ≥ P` (hueco) / `ask_h ≥ P` | `ask_o + desl.` / `P + desl.` |
| Venta stop `P` | `bid_o ≤ P` / `bid_l ≤ P` | `bid_o − desl.` / `P − desl.` |
| Mercado pendiente (mercado cerrado al enviarla) | siempre | `ask_o + desl.` / `bid_o − desl.` |

Cada orden guarda `activa_desde` (primer minuto en que se evalúa) y `nacida_en` (minuto dentro del cual se creó, si se creó a mitad de minuto). En el minuto en que nació, la regla del hueco en la apertura no se aplica, porque la apertura fue anterior a la orden.

**Entrada ejecutada en el minuto `m`** (límite o stop) con SL y TP: el SL nace en `m` con `activa_desde = m` y el TP con `activa_desde = m + 1 min`, salvo que la entrada fuera en la apertura (hueco): entonces los dos son activos en `m`. Es el criterio conservador de RF-14.

**SL y TP en el mismo minuto.** Las dos órdenes de un OCO se evalúan juntas. Si las dos se ejecutarían: gana la que se ejecute en la apertura (hueco); si ninguna, el SL.

**Mercado en el acto.** Con el reloj en `T`, si el último minuto visto empieza en `T − 1 min` el mercado está abierto: la orden se ejecuta al cierre de ese minuto (ASK o BID más deslizamiento). Sus SL y TP quedan activos desde `T`, con la regla del hueco, porque todo el minuto `T` es posterior a la entrada. Si el último minuto es anterior, la orden queda pendiente y se ejecuta en la apertura del siguiente.

### Posiciones y operaciones

- Una posición por contrato, con cantidad con signo y precio medio.
- Una **operación** va de plano a plano: se abre con la primera ejecución y se cierra cuando la posición vuelve a cero. Si una ejecución da la vuelta a la posición, cierra una operación y abre otra. Guarda contrato, lado, cantidad máxima, precio medio de entrada y de salida, instantes de mercado de apertura y cierre, PnL bruto, comisiones, SL inicial (si lo había, para el R de la fase 5) y la sesión de replay.
- Las comisiones de una ejecución que cierra y abre a la vez se reparten en proporción a los contratos.
- SL, TP y cierres son "solo cierre": al ejecutarse usan `min(cantidad, posición)`, y si la posición queda plana se cancelan todos los del contrato.

### Reloj y varios instrumentos

`SesionReplay` ya guarda en memoria los minutos siguientes por instrumento. Se generaliza para que cada instrumento lleve su propio cursor:

- `avanzar()` devuelve también los minutos crudos del instrumento del gráfico.
- `minutos_entre(simbolo, desde, hasta)` da los minutos de otro instrumento en el tramo que acaba de avanzar el reloj.
- `ultimo(simbolo)` da el último minuto visto de un instrumento (para el precio actual, el PnL abierto y validar stops).
- Cada sesión tiene un `id` para marcar las ejecuciones y saber cuáles dibujar.

En `POST /api/replay/avanzar`, bajo el cerrojo: se guarda el instante `A`, avanza el reloj hasta `B`, se piden los minutos `[A, B)` de los demás instrumentos con exposición y el motor los procesa mezclados por hora.

### Saltos, salida y reinicio

- Antes de empezar un replay nuevo o salir, el servicio liquida todo al último precio del instante actual (RF-17).
- La cuenta guarda `instante_replay` y `sesion_replay` cada vez que cambia algo si queda exposición (y los borra si no). Al arrancar el servidor, si la cuenta activa tiene exposición, se crea la sesión de replay en ese instante (RF-6). Como el estado de la cuenta no cambia entre dos eventos, volver al instante del último evento es coherente.

## API

| Método y ruta | Cuerpo | Respuesta |
|---|---|---|
| `GET /api/cuentas` | — | lista de cuentas |
| `POST /api/cuentas` | `{nombre, balance_inicial}` | cuenta creada (y activa) |
| `PATCH /api/cuentas/{id}` | costes y/o `activa: true` | cuenta |
| `GET /api/cuenta` | — | resumen de la cuenta activa |
| `POST /api/ordenes` | `{contrato, lado, tipo, cantidad, precio?, sl_puntos?, tp_puntos?}` | `{orden, cuenta}` |
| `PATCH /api/ordenes/{id}` | `{precio}` | `{cuenta}` |
| `DELETE /api/ordenes/{id}` | — | `{cuenta}` |
| `POST /api/posiciones/{contrato}/cerrar` | — | `{cuenta}` |
| `POST /api/cuenta/cerrar-todo` | — | `{cuenta}` |
| `GET /api/operaciones` | `limite` | operaciones cerradas, la más reciente primero |
| `GET /api/ejecuciones` | `simbolo` | ejecuciones de la sesión de replay actual |

`POST /api/replay/avanzar` añade `cuenta` (resumen) y `ejecuciones` (las nuevas). El resumen es pequeño: balance, PnL abierto, PnL de la sesión, posiciones y órdenes pendientes.

Errores: 409 si no hay replay o hay exposición donde no se permite; 422 si la orden no es válida (contrato, cantidad, stop al otro lado del precio...).

## Modelo de datos (SQLite)

```
cuentas      id, nombre, balance_inicial, balance, spread_ticks, deslizamiento_ticks,
             comision_mini, comision_micro, activa, creada, instante_replay, sesion_replay
ordenes      id, cuenta, contrato, lado, tipo, cantidad, precio, sl_puntos, tp_puntos, papel,
             grupo, activa_desde, nacida_en, estado, precio_ejecucion, ejecutada, sesion, creada_real
ejecuciones  id, cuenta, orden, contrato, lado, cantidad, precio, comision, instante, sesion, creada_real
posiciones   cuenta, contrato, cantidad, precio_medio, operacion
operaciones  id, cuenta, contrato, lado, cantidad, entrada, salida, apertura, cierre, pnl_bruto,
             comisiones, sl_inicial, sesion, abierta, suma_entrada, contratos_entrada,
             suma_salida, contratos_salida
```

Las horas de mercado se guardan en ET sin zona (como el reloj del replay) y las reales en UTC con zona.

## Frontend

- `frontend/operativa.js` (nuevo): panel de operar (boleta, resumen, posiciones, órdenes, últimas operaciones), líneas de precio en el gráfico con `createPriceLine`, arrastre de las líneas de órdenes (mismo esquema de ratón en captura que los dibujos), marcas de ejecuciones con `createSeriesMarkers` y gestión de cuentas.
- `replay.js`: pasa `cuenta` y `ejecuciones` de cada avance a `operativa.js`; el segundo clic de confirmación al saltar o salir con exposición.
- `index.html` y `estilos.css`: panel lateral derecho plegable.

## Cambios pedidos por el usuario (RF-22 a RF-25)

Todo en el frontend, salvo un dato nuevo en el resumen de la cuenta: cada posición lleva `desde`, la hora de apertura de su operación (en el formato del gráfico), para saber dónde empiezan las zonas.

- **Zonas (RF-22):** una primitiva de Lightweight Charts en `operativa.js`, como la de los dibujos. Para cada SL y TP del instrumento del gráfico, un rectángulo entre el precio medio de la posición y el precio de la orden, desde la vela de `desde` (con `tiempoALogico`) hasta el borde derecho. Si la orden se está arrastrando, usa el precio del arrastre. El importe de las etiquetas es `(precio − medio) × multiplicador × cantidad`, con signo según el lado.
- **Puntos o dólares (RF-23):** la boleta convierte a puntos antes de enviar; la API no cambia. Las conversiones van en `calculos.js` (`puntosDesdeDolares`, `dolaresDesdePuntos`) y se testean con Node.
- **Vista previa (RF-24):** tres líneas de precio propias (entrada, SL y TP) y sus zonas en la misma primitiva, empezando en la última vela. La referencia de una orden a mercado es el precio que se ve: la vela provisional del movimiento simulado si la hay (`indicadores.provisional`) o la última vela, redondeado al tick, más el spread de la cuenta si compra. Se recalcula al cambiar la boleta, en cada avance del reloj (`aplicarMinutos`), en cada fotograma del movimiento simulado y al recargar el gráfico. Está visible mientras el ratón está sobre la boleta o uno de sus campos tiene el foco, y se apaga al enviar la orden hasta que se vuelve a tocar la boleta.
- **Lado (RF-25):** selector "Compra | Venta" y un botón de confirmar con el resumen de la orden. Lado, unidad, cantidad, SL y TP se recuerdan en el navegador.

## Riesgos

- **Criterio conservador demasiado duro** con stops amplios en minutos muy volátiles. Es lo pedido en la fase 3 hasta tener ticks.
- **Escrituras en SQLite sobre NTFS** (ntfs-3g): solo se escribe cuando hay un evento (orden, ejecución), no en cada avance del reloj.
- **Dos relojes en modo simulado** (RF-16): documentado; las órdenes usan siempre el del backend.

## Cómo se prueba

Tests del motor (pytest, sin disco): precios con spread, deslizamiento y tick en los seis contratos; mercado en el acto y con mercado cerrado; límite y stop con y sin hueco; SL y TP en el mismo minuto; minuto de la entrada; solo cierre; reducir, cerrar y dar la vuelta; comisiones repartidas; el caso a mano del criterio de aceptación.

Tests de la API (con datos sintéticos): orden en ES mientras se avanza en NQ, liquidación al saltar, persistencia y reinicio (recrear el servicio y comprobar balance, historial y sesión restaurada), validaciones.

Pruebas manuales en Chrome con datos reales: comprar con SL y TP, ver líneas y marcas, arrastrar el SL, ver el resultado en el balance y en el historial, saltar con una posición abierta, modo a ciegas.
