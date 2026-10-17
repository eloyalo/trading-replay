# 009 · Plan técnico

Referencia: [spec.md](spec.md)

## Enfoque

Las reglas del reto ya existen y son puras (`operativa/reto.py`). Lo que no es reutilizable es la vigilancia minuto a minuto, que vive en `operativa/servicio.py` y usa la cuenta activa global. Se saca a un módulo nuevo, `operativa/vigilancia.py`, con funciones que reciben el motor, el estado del reto y el perfil, y devuelven el evento si se rompe algo. El servicio del replay las llama igual que antes y el backtest también. Así las reglas son las mismas por construcción (RF-2).

## Vigilancia común (`operativa/vigilancia.py`)

Funciones sacadas de `servicio.py` sin cambiar lo que hacen:

| Función | Antes en `servicio.py` | Qué hace |
|---|---|---|
| `recta_balance(m, simbolo)` | `_recta_balance` | Balance en vivo como recta del BID |
| `liquidar_a(m, simbolo, minuto, bid)` | `_liquidar_a` | Cierra todo con el BID en un precio dentro del minuto |
| `hora_de_cierre(estado, perfil, m, simbolo, minuto) → evento` | `_hora_de_cierre` | A la hora de cierre, cierra todo en la apertura del minuto |
| `vigilar(estado, perfil, m, simbolo, minuto) → evento` | `_vigilar` | Pérdida máxima y límite diario con el peor precio; pico con el mejor |
| `vigilar_ahora(estado, perfil, m, instante) → evento` | `_vigilar_ahora` | Tras una ejecución en el acto |
| `validar_orden(estado, perfil, m, orden, instante)` | `_validar_en_reto` | Lanza `OrdenNoValida` si el reto no la admite |

`servicio.py` se queda con lo suyo (eventos para el frontend, guardar el estado) y llama a estas funciones. Los tests de las specs 005 y 006 tienen que seguir pasando sin tocarlos.

## Reto en el backtest (`backtest/reto_bt.py`)

`RetoBacktest(perfil)` lleva el intento en curso (`EstadoReto`), sus días y la lista de intentos terminados. El ejecutor lo llama en estos puntos:

```
al empezar una vela de un día de trading nuevo (antes de sus minutos):
    reto.cambiar_dia(instante)  → cerrar_dia del anterior si se operó (trailing al cierre, aprobado)
    si el intento ha terminado → liquidar lo abierto ("Fin del intento"), empezar otro: balance del perfil
en cada minuto con exposición:
    hora_de_cierre → motor.procesar → vigilar      (el mismo orden que el replay)
    si se ha suspendido → el siguiente intento empieza el día de trading siguiente
tras una ejecución en el acto (orden a mercado al cierre de una vela): vigilar_ahora
al enviar una orden de la estrategia: validar_orden; si no la admite, no se envía y se cuenta (RF-4)
```

- **Días:** un `Dia(fecha, pnl)` por cada día de trading con ejecuciones; el PnL es el cambio del balance en el día, con comisiones, como en `bd.dias`.
- **Intento suspendido a mitad de día:** queda terminado y no admite órdenes; el siguiente empieza al llegar el día siguiente (RF-5).
- **Motivo de salida** de lo que cierra el reto: el ejecutor lo apunta como los otros cierres (`_motivo_cierre`).
- **Balance:** `MotorBacktest` empieza con el balance del perfil; al empezar un intento se vuelve a poner.
- **Intento de cada operación:** el ejecutor anota en `OperacionBT.intento` el intento en curso al abrirla.

## Métricas (`backtest/metricas.py`)

`resumen_reto(intentos, rechazadas)` → RF-7. Un intento es `{numero, inicio, fin, resultado, motivo, dias, beneficio, mejor_dia, operaciones}`. Los días naturales van del inicio del primer día de trading al final del último.

## Datos

`datos/backtests.sqlite`:

- `ejecuciones`: columnas nuevas `perfil` (id o NULL) y `reto` (JSON con el resumen del reto y las órdenes rechazadas, o NULL).
- `operaciones`: columna nueva `intento` (o NULL).
- Tabla nueva `intentos (ejecucion, numero, inicio, fin, resultado, motivo, dias, beneficio, mejor_dia, operaciones)`.

La base de datos ya puede existir con ejecuciones de la 008: al abrirla se añaden las columnas que falten (`ALTER TABLE ... ADD COLUMN`). Las ejecuciones viejas quedan sin reto.

## API

- `POST /api/backtests`: campo nuevo `perfil` (opcional). 422 si no existe.
- `GET /api/backtests/{id}`: con reto, además `reto: {perfil, titulo, resumen, intentos}`, y cada operación con su `intento`.
- `GET /api/backtests`: cada ejecución con `perfil` y el resumen del reto.

## Frontend (`backtest.js`)

- **Lanzar:** selector "Reto" ("Sin reto" y los perfiles de `/api/perfiles`).
- **Resultados:** con reto, una sección antes de las cifras con tarjetas (intentos, % de aprobados, días hasta aprobar, motivo de suspensión más común, órdenes rechazadas) y la tabla de intentos. Al pulsar un intento, se ponen los filtros de fecha en su periodo. La lista de operaciones gana la columna "Intento".
- **Historial:** columna "Reto" con el perfil y el % de aprobados.

## Riesgos

- **Sacar la vigilancia de `servicio.py`** puede romper los retos del replay. Lo cubren los tests de la 006 y se mueve el código sin cambiarlo.
- **Rapidez:** la vigilancia solo corre en los minutos con exposición, que ya se procesan uno a uno. Coste pequeño.

## Cómo se prueba

- Tests del reto en el backtest con velas sintéticas y un perfil de prueba hecho en el test: aprobado al cerrar el día, suspendido por pérdida máxima al precio de ruptura, intento siguiente al día siguiente, límite diario en pausa, consistencia y días mínimos, contratos máximos y hora de cierre.
- Migración: una base de datos con el esquema de la 008 se abre y gana las columnas.
- API: lanzar con perfil, resultado con reto, 422 con un perfil que no existe.
- Datos reales y Chrome headless: ruptura y Danny con el Topstep 50K.
