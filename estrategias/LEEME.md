# Estrategias

Cada archivo `.py` de esta carpeta es una estrategia que se puede pasar por el histórico desde la ventana **Backtest** de la app. La app las encuentra sola y, si guardas un cambio, la siguiente ejecución usa el código nuevo, sin reiniciar nada.

- Los archivos que empiezan por `_` no se cargan. Sirven para apuntes o código a medias.
- Para probar un cambio sin perder la original, usa **Duplicar** en la app: crea `nombre_2.py` y la edita aparte.
- Si una estrategia tiene un error, la app lo enseña con el archivo, la línea y el mensaje, y no deja lanzarla hasta que se corrija.

## Esqueleto

```python
"""Explicación de la estrategia con palabras: cuándo entra, dónde pone el stop y el objetivo, cuándo sale."""

from trading_replay.backtest import Estrategia, Parametro


class MiEstrategia(Estrategia):
    nombre = "Mi estrategia"
    timeframe = "5m"  # 1m, 5m, 15m, 30m, 1h o 4h
    parametros = {
        "objetivo_r": Parametro(2.0, "Objetivo en R", minimo=0.5, maximo=10, paso=0.5),
    }

    def al_empezar_dia(self):
        self.operado_hoy = False

    def al_cerrar_vela(self, vela):
        ...
```

El texto entre comillas triples del principio es la descripción que sale en la app. Una estrategia opera un solo instrumento: el que se elige al lanzarla.

## Cuándo se la avisa

| Método | Cuándo |
|---|---|
| `al_empezar(self)` | Una vez, antes de la primera vela |
| `al_empezar_dia(self)` | Al empezar cada día de trading (18:00 ET), antes de su primera vela |
| `al_cerrar_vela(self, vela)` | Al cerrar cada vela del timeframe. Es el único obligatorio |

Las variables que guardes en `self` (`self.alto = ...`) se conservan de una vela a otra.

## Qué puede ver

**Velas.** `vela` es la que acaba de cerrar: `vela.inicio`, `vela.fin`, `vela.open`, `vela.high`, `vela.low`, `vela.close`, `vela.volume`. `self.velas` tiene todas las cerradas hasta ahora: `self.velas[-1]` es la misma que `vela`, `self.velas[-2]` la anterior. También se leen por columnas, que es más rápido para muchas: `self.velas.close[-20:]`. Nunca hay velas futuras: `self.velas[len(self.velas)]` da error.

**Tiempo** (hora de Nueva York, del cierre de la vela):

| Qué | Ejemplo |
|---|---|
| `self.hora` | `"09:45"`. Se compara como texto: `self.hora >= "16:00"` |
| `self.entre(desde, hasta)` | `self.entre("09:30", "10:00")`: la vela cierra después de las 9:30 y como tarde a las 10:00. Si `desde` es mayor que `hasta` ("18:00", "03:00"), el tramo cruza la medianoche |
| `self.hora_mas(hora, minutos)` | `self.hora_mas("09:30", 15)` → `"09:45"` |
| `self.fecha` | Fecha del día de trading (lo que cierra después de las 18:00 ya es del día siguiente) |
| `self.dia_semana` | `"lunes"`, `"martes"`... del día de trading |
| `self.sesion` | `"asia"` (18:00–3:00), `"londres"` (3:00–9:30), `"nueva_york"` (9:30–17:00) o `None` |
| `self.instante` | Fecha y hora del cierre de la vela |

**Indicadores.** Los mismos del gráfico, calculados igual. Dan el valor en la vela que acaba de cerrar, o `None` si todavía no hay datos suficientes (al principio del histórico). Con `atras=1` dan el de la vela anterior, útil para ver cruces.

| Qué | Devuelve |
|---|---|
| `self.ema(20)`, `self.sma(20)` | Media exponencial o simple del cierre |
| `self.rsi(14)`, `self.atr(14)` | RSI y ATR de Wilder |
| `self.vwap()` | VWAP del día de trading |
| `self.dia_anterior()` | `.high`, `.low` y `.close` del día de trading anterior |
| `self.overnight()` | `.high` y `.low` de 18:00 a 9:30, a partir de las 9:30 |

**Parámetros.** `self.p.objetivo_r` tiene el valor elegido al lanzar. Un `Parametro` lleva el valor por defecto, el texto que se ve en la app y, si hace falta, `minimo`, `maximo`, `paso` u `opciones=["a", "b"]`. El tipo sale del valor por defecto: `2` es un entero, `2.0` un decimal, `True` un sí/no y `"09:30"` un texto.

Con `grupo="Nombre"` el parámetro sale dentro de una sección plegable del formulario (útil cuando hay muchos). Un parámetro que se llame `timeframe`, con `opciones` (`list(TIMEFRAMES)`, que sale de `trading_replay.backtest`), hace que el timeframe se elija al lanzar: el `timeframe` de la clase es entonces solo el valor por defecto.

**Otros timeframes.** `self.velas_de("1h")` da las velas cerradas de un timeframe mayor que el de la estrategia (y múltiplo suyo), armadas con las suyas. Se leen igual que `self.velas`. Una vela mayor solo aparece cuando ha cerrado entera.

**Instrumento.** `self.simbolo` es el instrumento del backtest (`"NQ"`, `"ES"` o `"GC"`) y `self.tick` su tick en puntos (0,25 en NQ y ES, 0,1 en GC), para pasar ticks a precio: `100 * self.tick`.

**Posición.** `self.posicion` son los contratos abiertos, con signo (positivo si es largo, negativo si es corto y 0 si no hay nada). `self.precio_entrada` es su precio medio. `self.ordenes` son las órdenes pendientes.

## Qué puede hacer

```python
self.comprar(contratos, tipo="mercado", precio=None, sl=None, sl_puntos=None,
             tp=None, tp_puntos=None, tp_r=None, micro=False, motivo="")
self.vender(...)          # lo mismo, para vender
self.cerrar(motivo="")    # cancela lo pendiente y cierra la posición a mercado
self.cancelar()           # cancela las órdenes de entrada pendientes (no el SL ni el TP)
self.mover_sl(precio)     # lleva el SL de la posición a otro precio
self.tomar_parcial(contratos, precio)  # orden límite que cierra parte de la posición
```

- `tipo`: `"mercado"`, `"limite"` o `"stop"`. Las dos últimas necesitan `precio`.
- **SL:** en precio (`sl=17990`) o en puntos desde la entrada (`sl_puntos=10`).
- **TP:** en precio (`tp=18050`), en puntos (`tp_puntos=20`) o en R (`tp_r=2`: dos veces la distancia de la entrada al SL).
- `micro=True` opera el micro (MNQ, MES, MGC) en lugar del mini.
- `motivo` se ve en la lista de operaciones, y el de `cerrar` como motivo de salida.
- `tomar_parcial` solo reduce la posición: si la posición se cierra antes por el SL o el TP, se cancela sola.
- Si una orden no es válida (un stop por encima del precio en un largo, por ejemplo), el motor lanza `OrdenNoValida`. Sin capturarla, el backtest se para y enseña el error con su línea. Se puede capturar para decidir otra cosa:

```python
from trading_replay.backtest import Estrategia, OrdenNoValida, Parametro

try:
    self.mover_sl(self.precio_entrada)
except OrdenNoValida:
    self.cerrar("Break-even")
```

Las órdenes se ejecutan como al operar a mano en el replay, con los mismos costes:

- Una orden a mercado sale al cierre de la vela que acaba de cerrar, que es el último precio conocido.
- Las límite y stop, y el SL y el TP, se ejecutan como pronto en el minuto siguiente, nunca con precios de la vela que las provocó.
- Si el SL o el TP pedidos en precio ya están rebasados al entrar (un SL por encima del precio de un largo), la operación se cierra en el acto.
- Si el SL y el TP caen en el mismo minuto de 1m, cuenta el SL. Los resultados dicen cuántas operaciones se resolvieron así.
- Al acabar los datos se cierra todo, con el motivo "Fin de los datos".

## Explicarse en el gráfico

Para comprobar en el gráfico que la estrategia hace lo que tiene que hacer, puede dejar marcas:

```python
self.nivel(precio, "texto")                       # línea horizontal desde ahora hasta las 17:00
self.rango("09:30", "09:45", alto, bajo, "texto")  # rectángulo entre dos horas del día
self.texto("ruptura")                             # texto en la vela que acaba de cerrar
marca = self.fibonacci((t_origen, precio_origen), (t_final, precio_final),
                       retrocesos=(0.5, 0.618), extensiones=(1.0, 1.618), texto="Impulso")
marca.fin = self.instante                         # hasta cuándo se ve la figura (si no, hasta el final)
```

`fibonacci` dibuja la figura de Fibonacci de la herramienta del gráfico, con esos niveles. En el modo backtest, el botón «Copiar Fibonacci como dibujo» la pasa a los dibujos propios.

## Ejemplos

- `ruptura_rango.py`: ruptura del rango de apertura de Nueva York.
- `cruce_medias.py`: cruce de dos medias exponenciales con el stop a una distancia de ATR.
- `danny.py`: Danny strategy, versión 1. Zonas de oferta y demanda de 15m a 4h con sus tres niveles y entrada al rechazo en 5m, con toma parcial y break-even.
- `ema_pullback.py` y `fibonacci.py` (spec 012): estrategias con muchas variantes como parámetros (medias, filtros de tendencia, tipo de entrada, stops, objetivos, parciales, trailing, sesiones...). Se pueden leer como ejemplo de estrategia grande.

### Piezas para estrategias con muchas variantes

- `trading_replay.backtest.comunes`: `parametros_sesion()` (Asia, Londres, Nueva York y ventana horaria), `parametros_operativa()` (lados, contratos, límites al día), `parametros_gestion()` (break-even, trailing) y la clase `Operativa`, que decide si se puede abrir (`puede_abrir(lado)`), envía la entrada con sus tramos (`entrar(lado, stop, [(precio, fracción), ...])`) y la lleva (`gestionar(vela)`: toma parcial, break-even, trailing y cierre forzoso). Se suman los parámetros al diccionario `parametros` con `{**parametros_sesion(), ...}`.
- `trading_replay.backtest.swings.Pivotes(n)`: pivotes de `n` velas a cada lado y su zigzag. Un pivote se entrega `n` velas después de formarse, nunca antes (no mira el futuro). `pivotes.actualizar(self.velas)` en cada vela y `pivotes.impulso` da el último (origen, final).

## Cuidado con

- Un bucle infinito dentro de `al_cerrar_vela` no se puede cancelar desde la app: hay que reiniciar el servidor.
- Probar muchas combinaciones de parámetros hasta que salga bien es la forma más fácil de engañarse con un backtest, y con estrategias que tienen decenas de opciones es todavía más fácil. Mejor decidir la regla antes y comprobarla en un periodo distinto.
- Algunas combinaciones no tienen sentido (por ejemplo, entrada límite con el stop tras el pullback, que todavía no existe): la estrategia lo dice al empezar, con el nombre del parámetro.
