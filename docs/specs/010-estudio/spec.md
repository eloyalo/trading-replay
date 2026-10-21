# 010 · Estudio: gráficos didácticos para vídeo

- **Estado:** En curso (aprobada por el usuario el 2026-10-18; implementada, falta su revisión)
- **Fase:** 8 (en paralelo a las fases 6 y 7; ver `FASES.md`)
- **Creada:** 2026-10-18 · **Actualizada:** 2026-10-18

## Problema

El canal de YouTube del usuario (proyecto `Canal Trading`, en inglés) necesita gráficos de velas exactos y anotados para enseñar cada concepto. Hay dos tipos:

- **El ejemplo perfecto:** una vela con mecha corta, un doble techo de libro o una ruptura con volumen. Hacen falta velas con los valores exactos que dice el guion, algo que un gráfico real casi nunca da.
- **El caso real:** una fecha concreta de NQ, ES u oro donde se vea el concepto, con niveles, flechas y trazos que aparecen a medida que lo explica la voz.

Hoy eso supondría grabar la pantalla a mano con la interfaz del simulador, que está en español y llena de paneles de operar. Hace falta un apartado separado, el **Estudio**, que:

- Monte la escena a partir de una descripción en JSON que escribe la IA desde el guion.
- La reproduzca con un reloj controlado.
- Saque capturas y vídeo sin intervención.

También debe servir para que el usuario dibuje a mano y se grabe, si lo prefiere.

## Alcance

**Incluye:**
- Una página nueva, `/estudio`, separada del replay, las cuentas y el backtest. No toca sus datos ni su estado.
- Un formato de **escena** en JSON con los datos del gráfico y una lista de **pasos** con tiempo (revelar velas, dibujar, resaltar, mover la cámara, mostrar indicadores...).
- Cuatro orígenes de datos: histórico real (NQ, ES, GC), **acciones y ETF de Dukascopy bajo demanda** (añadido a petición del usuario el 2026-10-18), velas escritas a mano y velas que aporta quien llama.
- Reloj determinista: la escena en el instante `t` se ve siempre igual, sin depender de la velocidad del equipo.
- Modo limpio para capturar: sin interfaz, textos del gráfico en inglés, tema de colores recibido desde fuera, 1920×1080 (16:9) y 1080×1920 (9:16).
- Una orden de terminal que captura una escena en PNG (un instante) o en MP4 (la escena entera), con Chrome sin interfaz.
- Un modo manual con **pincel**: el usuario dibuja a mano sobre el gráfico, el trazo se guarda en la escena con sus tiempos y se vuelve a reproducir igual al capturar.

**No incluye:**
- Widgets que no son gráficos de velas: libro de órdenes animado, calculadora de tamaño de posición, curva de capital explicada. Irán en una spec aparte (011) con el mismo reloj y la misma captura.
- Un buscador automático de ejemplos reales ("encuentra un doji en NQ 15m"). Mientras tanto, Claude busca las fechas con consultas a DuckDB sobre los Parquet. Si se repite mucho, será otra spec.
- Narración, música, montaje o textos grandes en pantalla: son del canal (audio-ai, Kdenlive y plantillas propias).
- Usar las acciones en el replay, las cuentas o el backtest: esa parte está hecha para futuros (contratos, día de trading de 18:00 a 18:00). Las acciones solo se ven en el Estudio.

## Requisitos

### Escena
1. **RF-1 · Formato de escena.** Un JSON con versión (`formato: 1`), lienzo (aspecto 16:9 o 9:16, tema), datos y pasos. Las claves van en español, como el resto del proyecto. Los textos que se ven (etiquetas), en el idioma que traiga la escena; el canal los manda en inglés. Ejemplo orientativo (el detalle va en el plan):

   ```json
   {
     "formato": 1,
     "lienzo": { "aspecto": "16:9", "tema": "canal" },
     "datos": { "tipo": "real", "instrumento": "NQ", "tf": "15m",
                "desde": "2024-03-08 09:30", "hasta": "2024-03-08 16:00" },
     "indicadores": [{ "tipo": "volumen" }],
     "pasos": [
       { "t": 0,   "accion": "revelar", "hasta": "2024-03-08 11:00", "duracion": 4 },
       { "t": 4.5, "accion": "horizontal", "precio": 18240, "etiqueta": "Resistance", "duracion": 0.8 },
       { "t": 6,   "accion": "pincel", "trazo": "trazos/rodeo-1.json" },
       { "t": 8,   "accion": "resaltar", "velas": ["2024-03-08 11:15"], "atenuar_resto": true },
       { "t": 10,  "accion": "camara", "desde": "2024-03-08 10:30", "hasta": "2024-03-08 12:30", "duracion": 1.5 }
     ]
   }
   ```

2. **RF-2 · Datos reales.** Instrumento, timeframe y rango en hora de Nueva York, con las mismas velas que `almacen.consultar` (mismo OHLC y misma alineación). El Estudio lee el histórico sin el recorte del replay y funciona tanto si hay un replay en marcha como si no.
3. **RF-3 · Velas escritas a mano.** Lista de velas con apertura, máximo, mínimo, cierre y, si se quiere, volumen. Llevan tiempos ficticios (por ejemplo, una vela por día desde una fecha neutra) y un aviso opcional *Illustrative* en una esquina, que el canal pone siempre que los datos son inventados.
4. **RF-4 · Acciones y ETF de Dukascopy.** Con `datos.tipo: "real"` y un símbolo que no sea NQ, ES ni GC (por ejemplo `NVDA` o `SPY`), el Estudio descarga de Dukascopy el CFD de la acción (`NVDAUSUSD`) **bajo demanda**: un archivo por año para el diario y uno por día para el intradía. Lo guarda en caché en `datos/estudio/` y no lo vuelve a pedir. Más detalles:
   - Sin descargas masivas: una escena diaria de un año cuesta una petición.
   - Precios ajustados por splits con una tabla editable (Dukascopy no los ajusta: NVDA sale a ~495 $ a principios de 2024).
   - Solo la sesión regular (9:30–16:00 ET), que es lo que da Dukascopy. El volumen es el del CFD, no el de la bolsa, así que es orientativo.
   - Comprobado el 2026-10-18: NVDA el 2024-08-29 da 121,33 / 124,41 / 116,71 / 117,52 (bid), frente a 121,36 / 124,43 / 116,71 / 117,59 reales.
4b. **RF-4b · Velas aportadas.** El mismo formato que RF-3, con un nombre de símbolo libre y sin aviso: sirve para datos reales de otra fuente.
5. **RF-5 · Pasos.** Cada paso tiene un instante de inicio `t` en segundos y, si se anima, una `duracion`. Acciones de la primera versión:

   | Acción | Qué hace |
   |---|---|
   | `revelar` | Hace aparecer velas una a una hasta una fecha, como en el replay. Opcional: la última vela se forma tick a tick. |
   | `horizontal`, `tendencia`, `rectangulo` | Las herramientas de la spec 004, dibujándose de forma progresiva, con etiqueta opcional. |
   | `zona` | Rectángulo de soporte o resistencia que se extiende hacia la derecha. |
   | `flecha` | Flecha de un punto (tiempo, precio) a otro. |
   | `marca` | Círculo o punto sobre una vela, con etiqueta opcional. |
   | `etiqueta` | Texto corto anclado a un tiempo y un precio. |
   | `pincel` | Trazo a mano alzada, desde un archivo de trazo (RF-12) o desde puntos dados. |
   | `resaltar` | Destaca unas velas y atenúa el resto. |
   | `ohlc` | Señala la apertura, el máximo, el mínimo y el cierre de una vela, con sus valores (para enseñar a leer una vela). |
   | `indicador` | Muestra u oculta un indicador de la spec 004 (medias, VWAP, volumen, RSI, ATR). |
   | `camara` | Mueve o amplía la vista hasta un rango de tiempo y, si se indica, de precio. |
   | `operacion` | Caja de entrada, stop y objetivo como las del panel de operar, con R:R opcional. |
   | `ocultar` | Quita un elemento dibujado antes (cada paso puede llevar `id`). |

6. **RF-6 · Validación.** Una escena con errores (fecha fuera del histórico, precio imposible, `id` repetido, paso que se sale de la duración) se rechaza con un mensaje que dice qué paso falla, antes de capturar nada.

### Reloj y captura
7. **RF-7 · Reloj determinista.** La página expone `estudio.cargar(escena)`, `estudio.duracion()` e `estudio.ir(t)`. `ir(t)` deja el gráfico exactamente como debe estar en el instante `t`, en cualquier orden y sin animaciones pendientes. Las animaciones se calculan a partir de `t`, nunca de `requestAnimationFrame`.
8. **RF-8 · Modo limpio.** En modo captura solo se ve el gráfico: sin barras, botones ni textos en español. Las fechas, las horas y los números del eje salen en inglés (`en-US`). El tema (fondo, velas, colores de cada tipo de dibujo, tipografía y grosor de línea) llega en un JSON, para que el estilo del canal viva en el canal.
9. **RF-9 · Formatos.** 1920×1080 y 1080×1920. En vertical, el eje de precios y las etiquetas son más grandes para que se lean en un móvil.
10. **RF-10 · Captura.** `uv run trading-replay estudio capturar escena.json` genera:
    - `--foto 12.5`: un PNG del instante 12,5 s (se puede repetir).
    - Por defecto: un MP4 H.264 de la escena entera a 30 fps (`--fps 60` opcional), a partir de fotogramas tomados con `ir(t)` y unidos con ffmpeg.
    - `--salida carpeta/`: dónde dejarlo.

    Arranca su propio servidor en un puerto libre y lo cierra al terminar, sin tocar el que esté usando el usuario.
11. **RF-11 · Atribución.** Lightweight Charts pide atribución. En modo captura, el logotipo de TradingView se puede quitar (opción de la escena) siempre que el vídeo lleve la atribución en la descripción. El canal lo pone en su plantilla de descripción.

### Modo manual
12. **RF-12 · Pincel y grabar trazos.** En `/estudio` con interfaz, el usuario carga una escena, la reproduce, la para en un instante y dibuja con el pincel: color y grosor del tema, deshacer y borrar. Al soltar, el trazo se guarda con sus puntos (tiempo y precio) y el ritmo con el que se dibujó, como archivo de trazo y como paso `pincel` de la escena. Al capturar se reproduce igual, ya limpio.
13. **RF-13 · Grabarse a mano.** Con una tecla (`F`) se pasa al modo limpio a pantalla completa para grabar la pantalla con otra herramienta (por ejemplo Spectacle) mientras se dibuja en directo.
14. **RF-14 · Línea de tiempo.** Barra con play/pausa, posición, duración y los pasos marcados, para revisar una escena antes de capturarla.

## Criterios de aceptación

- [x] Dos capturas de la misma escena en el mismo instante dan imágenes idénticas píxel a píxel (test).
- [x] `ir(8)` después de `ir(20)` da la misma imagen que `ir(8)` desde cero (test).
- [x] Una escena real de NQ 15m muestra las mismas velas que `almacen.consultar` para ese rango (test).
- [x] Una escena de velas escritas a mano muestra exactamente los OHLC dados, y el paso `ohlc` enseña esos valores.
- [x] Una escena de 20 s se captura en un MP4 de 1920×1080 a 30 fps con 600 fotogramas, en menos de 3 minutos en el equipo del usuario.
- [ ] La misma escena en 9:16 se lee bien en un móvil (revisión del usuario).
- [x] En modo captura no aparece ningún texto en español y las fechas salen en inglés.
- [x] Un trazo dibujado a mano se guarda en la escena y sale igual en la captura.
- [x] Una escena con un paso inválido se rechaza con un mensaje que nombra el paso.
- [x] Con un replay en marcha, el Estudio funciona y el replay sigue igual (sin velas futuras en el replay y sin recortes en el Estudio).

## Dudas

Resueltas el 2026-10-18:

- **Lugar:** dentro de trading-replay, como apartado separado (elegido por el usuario).
- **Datos de acciones:** de Dukascopy, bajo demanda y solo para el Estudio (RF-4, pedido por el usuario).
- **Tema por defecto:** **(decidido por Claude)** el Estudio trae un tema oscuro neutro y la escena puede sustituir cualquier color o la tipografía.
- **Escenas de prueba:** **(decidido por Claude)** una vela explicada con velas escritas a mano, un caso real de NQ y el NVDA de agosto de 2024 para L1-01 del canal.
