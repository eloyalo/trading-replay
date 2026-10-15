# 001 · Esqueleto del proyecto

- **Estado:** Hecha (2026-10-15)
- **Fase:** 0
- **Creada:** 2026-10-15 · **Actualizada:** 2026-10-15

## Problema

Antes de trabajar con datos o con el replay hace falta una base que arranque: entorno de Python, servidor y una página con el gráfico. Sobre ella se irán montando las fases siguientes.

## Alcance

**Incluye:**
- Proyecto Python gestionado con `uv`, con sus dependencias fijadas.
- Servidor FastAPI que sirve la API y el frontend desde el mismo puerto.
- Página web con un gráfico vacío de Lightweight Charts.
- Un solo comando para arrancarlo todo.

**No incluye:**
- Datos reales (fase 1).
- Replay, órdenes ni nada de trading.

## Requisitos

1. RF-1: `./iniciar.sh` instala lo que falte y arranca el servidor en `http://127.0.0.1:8000`.
2. RF-2: `GET /api/estado` devuelve JSON con `ok: true` y la versión de la app.
3. RF-3: la página principal muestra un gráfico de velas vacío que ocupa la ventana, y un indicador de si el backend responde.
4. RF-4: el frontend funciona sin internet. La librería del gráfico va incluida en el proyecto, no se carga desde un CDN.
5. RF-5: el servidor solo escucha en `127.0.0.1`, no es accesible desde otros equipos de la red.

## Criterios de aceptación

- [x] Dado el proyecto recién clonado, cuando ejecuto `./iniciar.sh`, entonces el servidor arranca sin errores.
- [x] Cuando abro `http://127.0.0.1:8000`, entonces veo el gráfico vacío y el indicador "Backend conectado".
- [x] Cuando ejecuto los tests (`uv run pytest`), entonces pasan.

## Dudas

- Ninguna.
