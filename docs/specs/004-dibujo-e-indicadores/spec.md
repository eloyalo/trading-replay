# 004 · Herramientas de dibujo e indicadores

- **Estado:** Hecha (2026-10-16; aprobada por delegación el 2026-10-16 y revisada por el usuario, ver "Cómo se aprobó")
- **Fase:** 2
- **Creada:** 2026-10-16 · **Actualizada:** 2026-10-16

## Problema

Para practicar hace falta marcar niveles y zonas en el gráfico y ver los indicadores habituales, igual que en la plataforma con la que se opera de verdad. Sin eso el replay sirve para mirar, pero no para preparar un trade.

## Cómo se aprobó

El 2026-10-16 el usuario pidió a Claude que siguiera con el desarrollo tomando las decisiones por su cuenta, sin preguntar, y que él probaría la app después. Las decisiones que normalmente se habrían consultado están marcadas con **(decidido por Claude)** para revisarlas con calma. Cualquier cambio que pida el usuario al probarla se incorpora a esta spec.

## Alcance

**Incluye:**
- Dibujo: línea horizontal, línea de tendencia y rectángulo. Seleccionar, mover, borrar y borrar todo.
- Indicadores: medias móviles (EMA y SMA), VWAP, volumen, RSI, ATR y niveles del día anterior y de la sesión overnight.
- Panel para activar y configurar los indicadores.
- Todo funciona igual con y sin replay, y nunca usa datos posteriores al instante del replay.

**No incluye:**
- Otras herramientas de dibujo (Fibonacci, texto, flechas, medir). Se pueden añadir más adelante sobre la misma base.
- Indicadores a medida escritos por el usuario.
- Alertas.
- Plantillas de indicadores o varias configuraciones guardadas.

## Requisitos

### Dibujo
1. **RF-1 · Herramientas.** Barra de herramientas con: cursor (sin herramienta), línea horizontal, línea de tendencia, rectángulo y borrar todo.
   - **Línea horizontal:** un clic. Ocupa todo el ancho y muestra su precio en el eje.
   - **Línea de tendencia:** dos clics (inicio y fin). Es un segmento, no se prolonga.
   - **Rectángulo:** dos clics (esquinas opuestas). Relleno semitransparente.
   - Línea de tendencia y rectángulo también se pueden dibujar arrastrando.
   - Los puntos se ajustan a las velas, como en TradingView.
   - Tras dibujar se vuelve al cursor **(decidido por Claude)**, como en TradingView por defecto.
2. **RF-2 · Más allá de la última vela.** Se pueden poner puntos a la derecha de la última vela (en el futuro del replay), para proyectar una tendencia o alargar una zona. El gráfico deja un hueco de 15 velas a la derecha para eso.
3. **RF-3 · Editar.** Un clic sobre un dibujo lo selecciona y muestra sus puntos de control. Se puede arrastrar el dibujo entero o un punto de control. `Supr` o `Retroceso` borra el seleccionado.
4. **RF-4 · Anclados a tiempo y precio.** Los dibujos se guardan en tiempo y precio, así que siguen en su sitio al cambiar de timeframe, al desplazarse y al avanzar el replay.
5. **RF-5 · Por instrumento.** Cada instrumento tiene sus dibujos. Al cambiar de NQ a ES se ven los de ES.
6. **RF-6 · Duración.** Los dibujos se guardan en el navegador y sobreviven a una recarga de la página. **Se borran al empezar un replay nuevo** (momento aleatorio o ir a fecha) **(decidido por Claude)**: un nivel dibujado en otra fecha puede delatar lo que pasó después, sobre todo en modo a ciegas. Al salir del replay se conservan.

### Indicadores
7. **RF-7 · Lista.** **(decidido por Claude)** Los habituales para operar futuros de índices y oro intradía:

   | Indicador | Dónde se dibuja | Parámetros (por defecto) |
   |---|---|---|
   | Media móvil 1, 2 y 3 | Sobre el precio | Tipo EMA o SMA, periodo y color (EMA 9, EMA 21 y SMA 200) |
   | VWAP | Sobre el precio | Se reinicia cada día de trading (18:00 ET) |
   | Volumen | Barras abajo del gráfico de precio | — |
   | RSI | Panel propio | Periodo (14), con líneas en 30 y 70 |
   | ATR | Panel propio | Periodo (14) |
   | Niveles del día anterior | Sobre el precio | Máximo, mínimo y cierre del día de trading anterior |
   | Niveles overnight | Sobre el precio | Máximo y mínimo de 18:00 a 9:30 ET del día en curso, dibujados desde las 9:30 hasta el final del día |

   Por defecto solo está activo el volumen **(decidido por Claude)**. Colores por defecto de las medias: amarillo, rosa y blanco, distintos del azul de los dibujos.
8. **RF-8 · Cálculo.**
   - Medias, RSI y ATR se calculan sobre las velas del timeframe activo, como en cualquier plataforma. RSI y ATR con el suavizado de Wilder.
   - VWAP con el precio típico ((máximo + mínimo + cierre) / 3) de cada vela del timeframe activo y el volumen de ticks. No se muestra en 1D.
   - Los niveles se calculan con las velas del timeframe activo. Los del día anterior son exactos en todos los timeframes intradía. Los overnight solo se muestran hasta 30m, porque en 1h y 4h la vela que contiene las 9:30 mezcla las dos sesiones. Ninguno de los dos se muestra en 1D.
   - El volumen de Dukascopy es de ticks, no volumen real del CME: VWAP y volumen son orientativos.
9. **RF-9 · Sin ver el futuro.** Los indicadores solo usan las velas visibles en el gráfico. En replay, se actualizan a la vez que la vela en formación, también durante el movimiento simulado dentro del minuto.
10. **RF-10 · Panel de indicadores.** Un botón "Indicadores" abre un panel para activar o desactivar cada uno y cambiar sus parámetros. Los cambios se ven al momento y se recuerdan en el navegador.
11. **RF-11 · Leyenda.** Arriba a la izquierda del gráfico se ven los indicadores activos con su valor en la vela bajo el cursor (o en la última si el cursor no está en el gráfico).

### Atajos
12. **RF-12 · Atajos.** **(decidido por Claude)**
    - `H`: línea horizontal. `T`: línea de tendencia. `B`: rectángulo ("bloque"; la `R` ya es el momento aleatorio).
    - `Esc`: si hay una herramienta activa o un dibujo seleccionado, lo cancela. Si no, sale del replay como hasta ahora.
    - `Supr` / `Retroceso`: borra el dibujo seleccionado.

## Criterios de aceptación

- [x] EMA, SMA, RSI, ATR y VWAP coinciden con un cálculo de referencia hecho a mano en un caso pequeño (test).
- [x] Al actualizar la última vela o añadir una nueva, el valor incremental de cada indicador es idéntico al de recalcular todo desde cero (test).
- [x] Los niveles del día anterior coinciden con el máximo, el mínimo y el cierre del día de trading anterior en 1m, 15m y 1h (test).
- [x] En replay a 1000x con todos los indicadores activos el gráfico sigue fluido.
- [x] Durante el replay, ningún indicador cambia de valor en velas ya cerradas (no repinta con datos futuros).
- [x] Una línea de tendencia dibujada en 15m sigue uniendo los mismos dos puntos (tiempo y precio) al pasar a 1m y a 1h.
- [x] Se puede dibujar a la derecha de la última vela y el dibujo sigue ahí al avanzar el replay.
- [x] Un dibujo se puede seleccionar, mover y borrar. Los dibujos sobreviven a una recarga y se borran al empezar un replay nuevo.
- [x] En modo a ciegas, ni la leyenda ni el panel muestran la fecha.

## Dudas

Ninguna abierta. El usuario revisó la app el 2026-10-16 y dio por buenas las decisiones marcadas **(decidido por Claude)**.
