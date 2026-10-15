# 001 · Tareas

Referencia: [plan.md](plan.md)

- [x] T1: `pyproject.toml` y entorno con `uv sync`
- [x] T2: App FastAPI con `/api/estado` y frontend estático
- [x] T3: Incluir Lightweight Charts 5.2.1 en `frontend/vendor/`
- [x] T4: Página con gráfico vacío e indicador de estado del backend
- [x] T5: Test de la API
- [x] T6: `iniciar.sh` y `.gitignore`
- [x] T7: Comprobar los criterios de aceptación (el usuario confirmó la revisión visual el 2026-10-15)

## Notas de implementación

- 2026-10-15: el `.venv` en NTFS (ntfs-3g) funciona sin cambios con Python 3.14.8; `uv sync` tarda unos 2 s.
- 2026-10-15: Starlette 1.8 marca como obsoleto usar `httpx` en `TestClient` y pide `httpx2`. Se usa `httpx2>=2.13` en las dependencias de desarrollo.
- 2026-10-15: comprobado con curl: `/api/estado`, `/` y `/app.js` responden 200 y el servidor solo escucha en `127.0.0.1:8000`.
