"""Pivotes y swings sin mirar al futuro (spec 012, RF-12).

Una vela es pivote alto si su máximo supera el de las `n` velas anteriores y no es menor que el de las
`n` siguientes (y al revés, el bajo). Hasta que no han cerrado esas `n` velas no se sabe, así que un pivote
se entrega `n` velas tarde: es lo que pasaría en vivo.

Con los pivotes se arma un zigzag que alterna altos y bajos (dos altos seguidos se quedan en el mayor).
Los dos últimos puntos del zigzag son el último impulso.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Pivote:
    indice: int  # posición de la vela en `velas`
    precio: float
    alto: bool
    confirmado_en: int  # índice de la vela al cerrar la cual se supo


class Pivotes:
    def __init__(self, n: int = 5):
        if n < 1:
            raise ValueError("Los pivotes necesitan al menos 1 vela a cada lado")
        self.n = n
        self.zigzag: list[Pivote] = []
        self._examinada = -1  # última vela examinada como posible pivote

    def actualizar(self, velas) -> list[Pivote]:
        """Examina las velas que ya tienen `n` cerradas detrás. Devuelve los pivotes nuevos que ha entrado
        en el zigzag (puede ser ninguno). Llamarla cuando cierra una vela de `velas`."""
        n, nuevos = self.n, []
        altos, bajos = velas.high, velas.low
        ultima = len(velas) - 1 - n
        for i in range(self._examinada + 1, ultima + 1):
            if i < n:
                continue
            izquierda_alta, derecha_alta = max(altos[i - n : i]), max(altos[i + 1 : i + n + 1])
            izquierda_baja, derecha_baja = min(bajos[i - n : i]), min(bajos[i + 1 : i + n + 1])
            if altos[i] > izquierda_alta and altos[i] >= derecha_alta:
                nuevos.append(self._anadir(Pivote(i, altos[i], True, i + n)))
            if bajos[i] < izquierda_baja and bajos[i] <= derecha_baja:
                nuevos.append(self._anadir(Pivote(i, bajos[i], False, i + n)))
        self._examinada = max(self._examinada, ultima)
        return [p for p in nuevos if p is not None]

    def _anadir(self, pivote: Pivote) -> Pivote | None:
        z = self.zigzag
        if z and z[-1].alto == pivote.alto:
            mejor = pivote.precio > z[-1].precio if pivote.alto else pivote.precio < z[-1].precio
            if not mejor:
                return None
            z[-1] = pivote
            return pivote
        z.append(pivote)
        return pivote

    @property
    def impulso(self) -> tuple[Pivote, Pivote] | None:
        """(origen, final) del último impulso: bajo → alto si es alcista, alto → bajo si es bajista."""
        return (self.zigzag[-2], self.zigzag[-1]) if len(self.zigzag) >= 2 else None
