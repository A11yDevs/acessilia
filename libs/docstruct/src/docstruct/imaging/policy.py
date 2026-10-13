"""Decisão pura de imagem: fator de upscale e escolha de orientação.

Porta da política de ``orient_pages.py`` e do upscale do LOOP #34/#36/#38/#40
do Dr.DocBench (PR #125).

Só a **decisão** vive aqui — nenhum PIL/cv2, mantendo ``dependencies = []``. A
aplicação (Lanczos, rotação, OCR) fica no backend.

Upscale antes do OCR (LOOP #34/#36): páginas pequenas ganham muito com
ampliação Lanczos. O maior ganho isolado da linha Tele foi 2x para lado maior
< 800 px (puro 77.47 → 79.63). A faixa 800–1200 px ganha menos (1.5x).

Orientação (``orient_pages.py``): detecta 0/90/270. Se a maioria das caixas de
texto for alta (h > 1.3 w) a página é candidata a 90/270; então o OCR roda a 90
e 270 e vence o ângulo com maior ``sum(len(palavra) * score)``.
"""
from __future__ import annotations

# Limiar de lado maior abaixo do qual a página é "pequena".
SMALL_SIDE = 800

# Limiar de lado maior abaixo do qual a página é "média".
MEDIUM_SIDE = 1200

# Fatores de upscale por faixa de tamanho.
SMALL_FACTOR = 2.0
MEDIUM_FACTOR = 1.5
LARGE_FACTOR = 1.0

# Razão altura/largura acima da qual uma caixa de texto é considerada "alta".
TALL_RATIO = 1.3

# Fração mínima de caixas altas para considerar a página rotacionada.
DEFAULT_TALL_THR = 0.6

# Mínimo de caixas de texto para confiar na detecção.
MIN_BOXES = 3

# Ângulos suportados (rotação anti-horária a aplicar para a página ficar de pé).
ANGLES = (0, 90, 180, 270)


def upscale_factor(width: int, height: int) -> float:
    """Fator de upscale para uma página de ``width`` x ``height``.

    ``2.0`` para lado maior < 800 px, ``1.5`` para 800–1200 px, ``1.0`` acima.
    """
    longest = max(width, height)
    if longest < SMALL_SIDE:
        return SMALL_FACTOR
    if longest < MEDIUM_SIDE:
        return MEDIUM_FACTOR
    return LARGE_FACTOR


def _dist(p, q) -> float:
    return ((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2) ** 0.5


def tall_frac(boxes: list, ratio: float = TALL_RATIO) -> float:
    """Fração de caixas de texto "altas" (altura > ``ratio`` x largura).

    ``boxes`` é uma lista de caixas no formato ``[[x0,y0],[x1,y1],[x2,y2],[x3,y3]]``
    (cantos em ordem, como o RapidOCR devolve). Devolve ``0.0`` se não houver
    caixas.
    """
    if not boxes:
        return 0.0
    tall = 0
    for b in boxes:
        w = _dist(b[0], b[1])
        h = _dist(b[3], b[0])
        if h > ratio * w:
            tall += 1
    return tall / len(boxes)


def is_rotation_candidate(
    boxes: list,
    tall_thr: float = DEFAULT_TALL_THR,
    min_boxes: int = MIN_BOXES,
) -> bool:
    """True se a página é candidata a 90/270 (maioria de caixas altas)."""
    if len(boxes) < min_boxes:
        return False
    return tall_frac(boxes) >= tall_thr


def pick_orientation(candidates: dict[int, tuple[float, int]]) -> int:
    """Ângulo vencedor a partir de ``{ângulo: (score, n_caixas)}``.

    Vence o maior ``score`` (``sum(len(palavra) * confiança)``); empate vai para
    o menor ângulo. Devolve ``0`` quando não há candidatos.
    """
    if not candidates:
        return 0
    return max(sorted(candidates), key=lambda a: candidates[a][0])


def decide_orientation(
    boxes: list,
    scores: dict[int, tuple[float, int]] | None = None,
    tall_thr: float = DEFAULT_TALL_THR,
    min_boxes: int = MIN_BOXES,
) -> int:
    """Ângulo a aplicar a uma página.

    Devolve ``0`` quando a página não é candidata a rotação. Caso contrário
    escolhe entre os ângulos de ``scores`` (tipicamente 90 e 270) pelo maior
    ``sum(len(palavra) * confiança)``.
    """
    if not is_rotation_candidate(boxes, tall_thr, min_boxes):
        return 0
    return pick_orientation(scores or {})
