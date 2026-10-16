"""Lanza los tests de JavaScript del frontend (tests/js) con Node, si está instalado."""

import shutil
import subprocess
from pathlib import Path

import pytest

CARPETA = Path(__file__).parent / "js"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node no está instalado")
def test_calculos_js():
    resultado = subprocess.run(
        ["node", "--test", *sorted(str(p) for p in CARPETA.glob("*.test.mjs"))],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert resultado.returncode == 0, resultado.stdout + resultado.stderr
