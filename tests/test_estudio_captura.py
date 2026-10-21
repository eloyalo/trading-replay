"""Captura del Estudio (spec 010, RF-7 y RF-10). Necesita Chrome y ffmpeg; si faltan, se salta."""

import shutil

import pytest

from trading_replay.estudio import captura

hay_chrome = any(shutil.which(n) for n in captura.NAVEGADORES)
pytestmark = pytest.mark.skipif(not (hay_chrome and shutil.which("ffmpeg")), reason="hace falta Chrome y ffmpeg")

ESCENA = {
    "formato": 1,
    "duracion": 3,
    "datos": {"tipo": "manual", "velas": [[10, 12, 9, 11], [11, 11.5, 8, 9], [9, 13, 8.5, 12.5], [12.5, 14, 12, 13.5]]},
    "pasos": [
        {"t": 0, "accion": "revelar", "desde": 0, "hasta": 3, "duracion": 1.5},
        {"t": 0.5, "accion": "horizontal", "precio": 12, "etiqueta": "Resistance", "duracion": 1},
        {"t": 1, "accion": "camara", "desde": 1, "hasta": 3, "duracion": 1},
    ],
}


def test_mismo_instante_misma_imagen_en_cualquier_orden():
    with captura.sesion(ESCENA) as (pestana, _):
        pestana.evaluar("estudio.ir(1.2)")
        primera = pestana.foto()
        pestana.evaluar("estudio.ir(2.9)")
        pestana.evaluar("estudio.ir(1.2)")
        assert pestana.foto() == primera
        pestana.evaluar("estudio.ir(0)")
        pestana.evaluar("estudio.ir(1.2)")
        assert pestana.foto() == primera


def test_video_con_los_fotogramas_esperados(tmp_path):
    r = captura.video(ESCENA, tmp_path / "e.mp4", fps=10)
    assert r["fotogramas"] == 30
    assert (tmp_path / "e.mp4").stat().st_size > 1000


def test_escena_invalida_no_abre_chrome():
    with pytest.raises(Exception, match="precio no válido"):
        with captura.sesion({**ESCENA, "pasos": [{"t": 0, "accion": "horizontal", "precio": -1}]}):
            pass
