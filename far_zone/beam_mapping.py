from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


ALPHA_MIN = -1.5
ALPHA_MAX = 1.5
ALPHA_STEP = 0.06
ALPHA_LEVELS = 51

BETA_MIN = -15.08
BETA_MAX = 15.08
BETA_STEP = 0.26
BETA_LEVELS = 117

TOTAL_BEAMS = ALPHA_LEVELS * BETA_LEVELS


@dataclass(frozen=True, slots=True)
class BeamMapEntry:
    beam_num: int
    alpha: float
    beta: float


class BeamMap:
    def __init__(self, entries: list[BeamMapEntry]):
        self.entries = entries
        self.source_path = Path('formula://beam-grid')
        self.by_beam_num = {entry.beam_num: entry for entry in entries}

    @property
    def beam_min(self) -> int:
        return 1

    @property
    def beam_max(self) -> int:
        return TOTAL_BEAMS

    def get(self, beam_num: int) -> BeamMapEntry | None:
        return self.by_beam_num.get(beam_num)

    def find_nearest(self, alpha: float, beta: float) -> BeamMapEntry:
        alpha_index = min(max(round((alpha - ALPHA_MIN) / ALPHA_STEP), 0), ALPHA_LEVELS - 1)
        beta_index = min(max(round((beta - BETA_MIN) / BETA_STEP), 0), BETA_LEVELS - 1)
        beam_num = alpha_index * BETA_LEVELS + beta_index + 1
        return self.by_beam_num[beam_num]


def beam_to_angles(beam_num: int) -> BeamMapEntry:
    if not 1 <= beam_num <= TOTAL_BEAMS:
        raise ValueError(f'Номер луча должен быть в диапазоне 1..{TOTAL_BEAMS}')

    zero_based = beam_num - 1
    alpha_index = zero_based // BETA_LEVELS
    beta_index = zero_based % BETA_LEVELS

    alpha = round(ALPHA_MIN + alpha_index * ALPHA_STEP, 2)
    beta = round(BETA_MIN + beta_index * BETA_STEP, 2)
    return BeamMapEntry(beam_num=beam_num, alpha=alpha, beta=beta)


def angles_to_beam(alpha: float, beta: float) -> BeamMapEntry:
    if not ALPHA_MIN <= alpha <= ALPHA_MAX:
        raise ValueError(f'alpha должен быть в диапазоне {ALPHA_MIN}..{ALPHA_MAX}')
    if not BETA_MIN <= beta <= BETA_MAX:
        raise ValueError(f'beta должен быть в диапазоне {BETA_MIN}..{BETA_MAX}')

    return load_beam_map().find_nearest(alpha=alpha, beta=beta)


@lru_cache(maxsize=1)
def load_beam_map(path: str | Path | None = None) -> BeamMap:
    entries = [beam_to_angles(beam_num) for beam_num in range(1, TOTAL_BEAMS + 1)]
    return BeamMap(entries=entries)


# ------------------------------------------------- Порядок перебора лучей
# Луч задаётся парой углов: α — азимут, β — угол места. Нумерация идёт
# растром (см. beam_to_angles), поэтому «по номеру» — это уже «все углы места
# при одном азимуте»; обратная группировка — тот же индекс, но транспонированный.
BEAM_ORDER_NUMBER = 'number'
BEAM_ORDER_AZIMUTH = 'azimuth'      # все углы места при одном азимуте
BEAM_ORDER_ELEVATION = 'elevation'  # все азимуты при одном угле места


def _beam_angles_or_none(beam) -> tuple[float, float] | None:
    """(α, β) луча или None, если углы неизвестны (не номер / вне сетки)."""
    try:
        entry = beam_to_angles(int(beam))
    except (TypeError, ValueError):
        return None
    return entry.alpha, entry.beta


def group_beams(beams, order: str = BEAM_ORDER_NUMBER) -> list[tuple[float | None, list]]:
    """Разбить лучи на группы по ведущему углу.

    order:
        'number'    — без группировки, по возрастанию номера;
        'azimuth'   — все углы места при одном азимуте, затем следующий азимут;
        'elevation' — все азимуты при одном угле места, затем следующий.

    Работает по ПРОИЗВОЛЬНОМУ набору номеров: в окне лежат только измеренные
    лучи (десятки из 5967), полная решётка не предполагается.

    Лучи без углов (режим одиночного файла, номер вне сетки) собираются в
    последнюю группу с ведущим углом None — они не теряются ни при каком порядке.

    Returns: [(ведущий угол или None, [луч, ...]), ...]
    """
    leading: dict[float | None, list[tuple]] = {}
    unknown = []
    for beam in beams:
        angles = _beam_angles_or_none(beam)
        if angles is None:
            unknown.append(beam)
            continue
        alpha, beta = angles
        if order == BEAM_ORDER_AZIMUTH:
            lead, follow = alpha, beta
        elif order == BEAM_ORDER_ELEVATION:
            lead, follow = beta, alpha
        else:
            lead, follow = None, beam   # одна группа, внутри — по номеру
        leading.setdefault(lead, []).append((follow, beam))

    groups = [(lead, [beam for _, beam in sorted(items)])
              for lead, items in sorted(leading.items(), key=lambda kv: (kv[0] is None, kv[0]))]
    if unknown:
        groups.append((None, unknown))
    return groups


def order_beams(beams, order: str = BEAM_ORDER_NUMBER) -> list:
    """Плоский список лучей в выбранном порядке (см. group_beams)."""
    return [beam for _, group in group_beams(beams, order) for beam in group]
