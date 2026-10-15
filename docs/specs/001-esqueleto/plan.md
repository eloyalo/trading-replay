# 001 · Plan técnico

Referencia: [spec.md](spec.md)

## Enfoque

Un único proceso: FastAPI sirve la API bajo `/api` y los archivos estáticos del frontend en `/`. El frontend es HTML y JavaScript sin paso de compilación, para que sea fácil de tocar. Si más adelante crece mucho, se puede pasar a Vite o similar.

## Componentes

| Módulo / archivo | Cambio |
|------------------|--------|
| `pyproject.toml` | Proyecto `trading-replay`, dependencias (`fastapi`, `uvicorn`) y dependencias de desarrollo (`pytest`, `httpx`) |
| `backend/trading_replay/app.py` | App FastAPI, ruta `/api/estado` y montaje del frontend |
| `frontend/index.html`, `app.js`, `estilos.css` | Página con el gráfico vacío e indicador de estado |
| `frontend/vendor/lightweight-charts.standalone.production.js` | Lightweight Charts 5.2.1 incluido en el proyecto |
| `tests/test_estado.py` | Test de `/api/estado` y de que se sirve la página |
| `iniciar.sh` | `uv sync` y arranque de `uvicorn` en 127.0.0.1:8000 |

## Estructura de carpetas

```
backend/trading_replay/   ← código Python (API y, más adelante, el motor)
frontend/                 ← web estática
datos/                    ← histórico descargado (fase 1), fuera de git
tests/
```

## Riesgos

- Si el proyecto está en un disco NTFS (ntfs-3g), el `.venv` funciona pero algo más lento. Si da problemas con enlaces simbólicos, se usa `UV_LINK_MODE=copy`.
- Python 3.14 es reciente: si alguna dependencia no tiene versión compatible, se fija 3.13 con `uv python pin`.

## Cómo se prueba

- `uv run pytest`
- Prueba manual: arrancar con `./iniciar.sh` y abrir el navegador.
