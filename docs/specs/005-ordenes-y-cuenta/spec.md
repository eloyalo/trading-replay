# 005 · Órdenes y cuenta simulada

- **Estado:** Hecha (2026-10-16; aprobada por delegación el 2026-10-16 y revisada por el usuario, ver "Cómo se aprobó")
- **Fase:** 3
- **Creada:** 2026-10-16 · **Actualizada:** 2026-10-16 (cambios pedidos por el usuario: RF-22 a RF-28)

## Problema

El replay sirve para mirar el mercado, pero para practicar hay que operar: meter órdenes con stop y objetivo, ver cómo se ejecutan con datos que no se conocían y llevar una cuenta cuyo balance sea el resultado de todas las operaciones, aunque cada una se haga en una fecha distinta.

## Cómo se aprobó

Como la 004: el usuario pidió a Claude que siguiera sin preguntar. Las decisiones que se habrían consultado están marcadas con **(decidido por Claude)** para revisarlas. La fase 2 está implementada pero aún no la ha revisado el usuario; se empieza la fase 3 igualmente por la misma delegación.

## Alcance

**Incluye:**
- Órdenes a mercado, límite y stop, con stop loss (SL) y take profit (TP) opcionales que forman un OCO.
- Contratos mini y micro de cada instrumento, con sus multiplicadores reales.
- Spread, deslizamiento y comisiones configurables por cuenta.
- Ejecución con los datos de 1m y criterio conservador cuando no se sabe el orden de los precios dentro del minuto.
- Posiciones con PnL abierto, operaciones cerradas con PnL neto y balance de la cuenta.
- Cuentas persistentes: el balance y el historial se conservan entre replays y entre reinicios.
- En el gráfico: líneas de la posición y de las órdenes (las de órdenes se pueden arrastrar para cambiar el precio) y marcas de las ejecuciones.

**No incluye:**
- Reglas de prop firm (fase 4).
- Diario, etiquetas y estadísticas (fase 5). Esta spec guarda lo necesario para ellas (cada operación con sus precios, instantes, comisiones y el SL inicial).
- Órdenes stop-limit, trailing stop y OCO entre órdenes sueltas **(decidido por Claude)**. El OCO que se usa al operar es el de SL/TP; lo demás se puede añadir después.
- Atajos de teclado para comprar y vender (fase 7).
- Operar fuera del replay: sin reloj no hay "ahora", así que no tiene sentido.

## Requisitos

### Contratos
1. **RF-1 · Contratos.** Cada instrumento del gráfico se puede operar con su contrato mini o micro:

   | Gráfico | Contrato | $ por punto | Tick | $ por tick |
   |---|---|---|---|---|
   | NQ | NQ / MNQ | 20 / 2 | 0,25 | 5 / 0,50 |
   | ES | ES / MES | 50 / 5 | 0,25 | 12,50 / 1,25 |
   | GC | GC / MGC | 100 / 10 | 0,10 | 10 / 1 |

2. **RF-2 · Precios en ticks.** Los datos son el BID del CFD con 3 decimales. Para operar se redondea el BID al tick más cercano y el ASK es el BID más el spread. Todos los precios de órdenes y ejecuciones están en la rejilla de ticks.

### Cuenta
3. **RF-3 · Cuentas.** Se pueden crear varias cuentas con nombre y balance inicial; una está activa y es con la que se opera. Al empezar hay una cuenta "Demo" de 50.000 $ **(decidido por Claude)**.
4. **RF-4 · Costes por cuenta.** Cada cuenta tiene su configuración, con estos valores por defecto **(decidido por Claude)**:
   - Spread: 1 tick.
   - Deslizamiento en órdenes a mercado y stop (incluidos los SL): 0 ticks.
   - Comisión por contrato y lado: 2,50 $ en minis y 0,75 $ en micros (5 $ y 1,50 $ ida y vuelta).
5. **RF-5 · Balance.** Balance = balance inicial + PnL de las operaciones cerradas − comisiones. El PnL abierto de las posiciones se ve aparte, valorado a lo que se recibiría al cerrar (los largos al BID y los cortos al ASK del último minuto).
6. **RF-6 · Persistencia.** Cuentas, órdenes, ejecuciones, posiciones y operaciones se guardan en disco (SQLite). Si se reinicia el servidor con posiciones u órdenes abiertas, el replay se retoma en el instante de la última ejecución o cambio de órdenes, para que todo cuadre.

### Órdenes
7. **RF-7 · Tipos.** Compra o venta, cantidad en contratos (entera, de 1 a 50) y tipo:
   - **Mercado:** se ejecuta en el acto al precio actual, que es el cierre del último minuto visto: al ASK si compra y al BID si vende, más el deslizamiento **(decidido por Claude)**. Así funciona también con el replay en pausa. Si el mercado está cerrado en ese instante (pausa diaria, fin de semana), espera a la apertura del siguiente minuto con datos.
   - **Límite:** precio igual o mejor. Se ejecuta cuando el precio lo toca **(decidido por Claude: "al tocar", no "al atravesar")**. Si el minuto abre ya más allá del límite, se ejecuta en la apertura, que es mejor precio.
   - **Stop:** se activa cuando el precio lo toca y se ejecuta al precio del stop (o en la apertura si el minuto abre más allá, con hueco) más el deslizamiento. Un stop de compra tiene que quedar por encima del ASK y uno de venta por debajo del BID; si no, se rechaza.
8. **RF-8 · SL y TP.** Al enviar una orden de entrada se pueden indicar SL y TP como **distancia en puntos** desde el precio de ejecución **(decidido por Claude)**, como las estrategias ATM de NinjaTrader. Al ejecutarse la entrada se crean el SL (stop) y el TP (límite) por la cantidad ejecutada. Son un OCO: cuando se ejecuta uno, se cancela el otro.
9. **RF-9 · SL y TP solo cierran.** Nunca abren posición: si la posición ya es menor que su cantidad, se ejecutan por lo que quede, y si la posición queda plana, se cancelan todos los SL y TP de ese contrato.
10. **RF-10 · Posición neta.** Hay una posición por contrato. Una compra con posición corta la reduce, la cierra o le da la vuelta. El precio medio solo cambia al aumentar la posición.
11. **RF-11 · Modificar y cancelar.** Se puede cambiar el precio de una orden pendiente (también SL y TP) o cancelarla. El cambio cuenta desde el siguiente minuto.
12. **RF-12 · Cerrar.** Botón para cerrar una posición a mercado (cancela todas las órdenes de ese contrato, como en NinjaTrader) y botón "Cerrar todo" (todas las posiciones y órdenes de la cuenta).

### Ejecución con velas de 1m
13. **RF-13 · Sin mirar el futuro.** Una orden enviada con el reloj en `T` solo se evalúa con los minutos que empiezan en `T` o después.
14. **RF-14 · Criterio conservador.** Dentro de un minuto no se sabe el orden de los precios, así que se elige siempre lo peor para el trader:
    - Si en el mismo minuto se tocan el SL y el TP, cuenta el SL, salvo que el minuto abra ya más allá de uno de los dos (entonces es ese, en la apertura).
    - En el minuto en que se ejecuta una entrada límite o stop, el SL sí puede ejecutarse (el precio pudo ir a la entrada y luego al SL). El TP solo si la entrada fue en la apertura del minuto (con hueco), porque solo entonces se sabe que el máximo o el mínimo fue posterior a la entrada. Las entradas a mercado se ejecutan antes de que empiece el minuto siguiente, así que ese minuto entero cuenta para el SL y el TP.
15. **RF-15 · Todos los instrumentos.** Las órdenes y posiciones de los tres instrumentos se evalúan aunque en el gráfico se vea otro, porque el reloj es común.
16. **RF-16 · Movimiento simulado.** Las órdenes se ejecutan siempre con los datos reales de 1m, nunca con el recorrido simulado (spec 003). En modo simulado, el backend va hasta un minuto por delante de lo dibujado: una orden a mercado se ejecuta al cierre real del minuto que se está dibujando, no al precio simulado que se ve. Para que el gráfico y la ejecución cuadren, al enviar una orden a mercado (o cerrar a mercado) se completa en el acto la vela que se está dibujando **(decidido por Claude, 2026-10-16)**: sin eso, se veía un precio y la orden salía a otro (15 puntos de diferencia en una prueba).

### Saltos y salida del replay
17. **RF-17 · Cierre al saltar.** Al empezar un replay nuevo (momento aleatorio o ir a fecha) o salir del replay, se cierran a mercado las posiciones abiertas y se cancelan las órdenes, al precio del instante actual. Si hay algo abierto, el botón pide un segundo clic en los 6 s siguientes para confirmar **(decidido por Claude)**: un trade no puede seguir en otra fecha.

### Interfaz
18. **RF-18 · Panel de operar.** A la derecha del gráfico (se puede plegar), solo durante el replay:
    - Boleta: lado (compra o venta), contrato (mini o micro del instrumento del gráfico), cantidad, tipo, precio (para límite y stop, propuesto con el último precio), SL y TP (vacío = sin él, en puntos o en dólares, RF-23) y un botón que confirma la orden y la resume ("Comprar 2 NQ a mercado"). Cambiado el 2026-10-16: antes había dos botones, Comprar y Vender, sin elegir lado antes (ver RF-24).
    - Resumen de la cuenta: balance, PnL abierto y PnL de este replay.
    - Posiciones con su PnL abierto y botón Cerrar. Órdenes pendientes con botón Cancelar. Botón Cerrar todo.
    - Últimas operaciones cerradas con su PnL neto.
19. **RF-19 · En el gráfico.** Línea de la posición (precio medio, con el PnL abierto en la etiqueta), líneas de las órdenes pendientes y de los SL y TP. Las líneas de órdenes se pueden arrastrar para cambiar el precio. Flechas en las velas donde hubo ejecuciones de este replay.
20. **RF-20 · Gestión de cuentas.** Ver las cuentas, crear una nueva, elegir la activa y cambiar sus costes. Solo fuera de una posición abierta.
21. **RF-21 · Modo a ciegas.** El historial de operaciones muestra el día de la semana y la hora del mercado, no la fecha.

### Cambios pedidos por el usuario (2026-10-16)

22. **RF-22 · Zonas de SL y TP.** Con una posición abierta, el gráfico pinta un rectángulo rojo translúcido entre el precio medio y cada SL, y uno verde entre el precio medio y cada TP, como la herramienta de posición de TradingView. Empiezan en la vela de apertura de la operación y llegan hasta el borde derecho. Al arrastrar un SL o un TP, su zona le sigue. Las etiquetas de las líneas de SL y TP muestran además lo que se perdería o ganaría en dólares ("SL 2 · −400 $").
23. **RF-23 · SL y TP en puntos o en dólares.** Un selector "Puntos | $" en la boleta. En dólares, la cantidad es para toda la orden (contratos × multiplicador) y en bruto, sin comisiones. Como el precio va en ticks **(decidido por Claude)**: el SL se redondea hacia dentro (nunca se arriesga más de lo escrito) y el TP hacia fuera (nunca se gana menos). Debajo de cada campo se ve la equivalencia en la otra unidad ("= 12,50 pts" o "= 400,00 $"). Al cambiar de unidad, los valores se convierten.
24. **RF-24 · Vista previa.** Mientras se prepara la orden (con el ratón sobre la boleta o el foco en uno de sus campos), el gráfico muestra dónde quedarían el SL (línea roja) y el TP (línea verde), con su zona y lo que se arriesga o gana en dólares. En límite y stop también la línea de entrada.
    - En una orden a mercado, la referencia es el precio actual (ASK si compra, BID si vende) y **se mueve con el precio** durante el play, también con el movimiento simulado dentro del minuto.
    - En límite y stop, la referencia es el precio escrito.
    - La vista previa desaparece al enviar la orden y vuelve al tocar de nuevo la boleta.
25. **RF-25 · Lado antes de confirmar** **(decidido por Claude)**. Para saber hacia dónde va el SL y el TP de la vista previa hay que elegir el lado antes de confirmar, así que la boleta tiene un selector "Compra | Venta" y un solo botón de confirmar, del color del lado.

### Gestión de cuentas, pedida por el usuario (2026-10-16)

El usuario quiere tener varias cuentas y decidir más adelante qué hace con cada una (fase 4). Para eso pide renombrarlas, reiniciarlas y borrarlas. Las tres acciones se hacen sobre la cuenta activa, desde los ajustes de cuenta: primero se elige la cuenta en el selector y luego se actúa **(decidido por Claude)**.

26. **RF-26 · Renombrar.** Se puede cambiar el nombre de la cuenta activa en cualquier momento, también con posiciones abiertas, porque no afecta a la operativa.
27. **RF-27 · Reiniciar.** Deja la cuenta como recién creada: el balance vuelve al balance inicial y se borran sus órdenes, ejecuciones, posiciones y operaciones. Se conservan el nombre y los costes. Solo sin posiciones ni órdenes abiertas.
28. **RF-28 · Borrar.** Elimina la cuenta y todo su historial. Solo sin posiciones ni órdenes abiertas, y nunca la única cuenta que queda. Después pasa a ser activa la cuenta más antigua de las que quedan **(decidido por Claude)**.
    - Reiniciar y borrar no se pueden deshacer, así que piden un segundo clic en el mismo botón antes de 6 s, como al saltar con algo abierto. Sin ventanas emergentes del navegador.

## Criterios de aceptación

- [x] Una orden a mercado con el replay en pausa se ejecuta en el acto al último precio; con el mercado cerrado espera a la apertura (test).
- [x] Un trade de compra de 2 NQ a mercado con SL 10 y TP 20 puntos que llega al TP liquida exactamente lo calculado a mano: (salida − entrada) × 2 × 20 − 4 × 2,50 $, y el balance cambia en esa cantidad (test).
- [x] Spread, deslizamiento y redondeo al tick dan los precios de ejecución esperados en compras y ventas, en minis y micros, en NQ, ES y GC (test).
- [x] Si el SL y el TP se tocan en el mismo minuto, se ejecuta el SL; si el minuto abre más allá del TP, se ejecuta el TP en la apertura (test).
- [x] Una orden límite no se ejecuta con un minuto anterior a su envío aunque el precio lo tocara (test).
- [x] Reducir, cerrar y dar la vuelta a una posición calculan bien el PnL y el precio medio, y los SL y TP se ajustan o se cancelan (test).
- [x] Una orden de ES se ejecuta mientras en el gráfico se ve NQ (test).
- [x] El balance y el historial siguen ahí tras reiniciar el servidor y tras saltar a otro momento aleatorio (test).
- [x] Al saltar con una posición abierta, se cierra al precio del instante actual (test).
- [x] En Chrome, con datos reales: comprar con SL y TP, ver las líneas, arrastrar el SL, ver la ejecución y el resultado en el balance.

- [x] Con 2 NQ, un SL de 400 $ equivale a 10 puntos y un TP de 505 $ a 12,75 puntos (hacia fuera); un SL de 505 $, a 12,5 (hacia dentro) (test).
- [x] Con una posición con SL y TP se ven las dos zonas, y al arrastrar el SL su zona y su etiqueta en dólares le siguen.
- [x] Con el replay en play y una orden a mercado preparada, las líneas previstas se mueven con el precio, también en modo simulado.

- [x] Renombrar la cuenta activa funciona también con una posición abierta (test).
- [x] Reiniciar devuelve el balance al inicial, vacía el historial y conserva nombre y costes; con algo abierto se rechaza (test).
- [x] Borrar elimina la cuenta y su historial y activa la más antigua; no se puede borrar la única ni la activa con algo abierto (test).
- [x] En Chrome: renombrar, reiniciar y borrar desde los ajustes de cuenta, con el segundo clic de confirmación.

## Dudas

Ninguna abierta. El usuario revisó la app el 2026-10-16 y dio por buenas las decisiones marcadas **(decidido por Claude)**.
