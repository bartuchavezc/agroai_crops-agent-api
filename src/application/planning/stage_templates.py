"""
Typical stage timeline of each crop of the catalog, in days after sowing (Argentine home/market garden
practice, indicative): when it emerges, when the seedling is transplanted (None = direct sowing) and the
milestones worth a reminder. Harvest comes from the cycle's expected_harvest_date / growth_period_days.
Crops not listed fall back to proportions of their growth period. Everything generated from a template is
an editable proposal (plan stages + reminders), not a rule.
"""
import unicodedata
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Milestone:
    day: int
    stage: str  # one of models.STAGE_TYPES
    name: str
    reminder: str  # what to check/do that day


@dataclass(frozen=True)
class StageTemplate:
    emergence_days: int
    transplant_day: Optional[int] = None
    milestones: tuple[Milestone, ...] = field(default_factory=tuple)


def _m(day: int, stage: str, name: str, reminder: str) -> Milestone:
    return Milestone(day, stage, name, reminder)


_FLOWER = "floracion"
_FRUIT = "fructificacion"
_VEG = "vegetativo"

TEMPLATES: dict[str, StageTemplate] = {
    "tomate": StageTemplate(7, 35, (
        _m(50, _VEG, "Tutorado y desbrote", "Colocar tutores y empezar a desbrotar"),
        _m(60, _FLOWER, "Floración", "Revisar floración y cuaje; regar parejo"),
        _m(75, _FRUIT, "Fructificación", "Controlar frutos, riego y fertilización potásica"),
    )),
    "pimiento": StageTemplate(12, 50, (
        _m(80, _FLOWER, "Floración", "Revisar floración; evitar estrés hídrico"),
        _m(95, _FRUIT, "Fructificación", "Controlar cuaje y tutorar si cargan mucho"),
    )),
    "berenjena": StageTemplate(10, 45, (
        _m(75, _FLOWER, "Floración", "Revisar floración"),
        _m(90, _FRUIT, "Fructificación", "Controlar frutos y tutorar"),
    )),
    "lechuga": StageTemplate(5, 25, (_m(40, _VEG, "Formación de cabeza", "Revisar desarrollo y riego"),)),
    "acelga": StageTemplate(8, 30, (_m(45, _VEG, "Primeros cortes", "Ver si ya se pueden cortar hojas externas"),)),
    "espinaca": StageTemplate(8, None, (_m(25, _VEG, "Raleo", "Ralear dejando 10 cm entre plantas"),)),
    "rucula": StageTemplate(4, None, (_m(15, _VEG, "Raleo", "Ralear si está muy densa"),)),
    "rabanito": StageTemplate(4, None, (_m(10, _VEG, "Raleo", "Ralear dejando 3-4 cm entre plantas"),)),
    "zanahoria": StageTemplate(14, None, (
        _m(30, _VEG, "Raleo", "Ralear dejando 5 cm entre plantas"),
        _m(60, _VEG, "Engrose de raíz", "Aporcar si asoman los hombros"),
    )),
    "remolacha": StageTemplate(8, None, (_m(25, _VEG, "Raleo", "Ralear dejando 8-10 cm entre plantas"),)),
    "cebolla": StageTemplate(12, 60, (_m(120, _VEG, "Bulbificación", "Reducir riego cuando se vuelque el follaje"),)),
    "puerro": StageTemplate(12, 60, (_m(100, _VEG, "Aporque", "Aporcar para blanquear el fuste"),)),
    "ajo": StageTemplate(20, None, (_m(150, _VEG, "Bulbificación", "Cortar riego cuando amarillee el follaje"),)),
    "papa": StageTemplate(20, None, (
        _m(35, _VEG, "Aporque", "Aporcar las plantas"),
        _m(60, _FLOWER, "Floración", "Revisar floración y tizón"),
    )),
    "arveja": StageTemplate(8, None, (
        _m(25, _VEG, "Tutorado", "Poner red o tutores"),
        _m(55, _FLOWER, "Floración", "Revisar floración"),
    )),
    "haba": StageTemplate(10, None, (_m(70, _FLOWER, "Floración", "Revisar floración y pulgón"),)),
    "chaucha": StageTemplate(7, None, (_m(40, _FLOWER, "Floración", "Revisar floración"),)),
    "maiz": StageTemplate(7, None, (
        _m(30, _VEG, "Aporque", "Aporcar y fertilizar con nitrógeno"),
        _m(55, _FLOWER, "Panojamiento", "Revisar polinización; no faltar riego"),
    )),
    "zapallito": StageTemplate(6, None, (_m(35, _FLOWER, "Floración", "Revisar floración y oídio"),)),
    "zapallo": StageTemplate(7, None, (_m(55, _FLOWER, "Floración", "Revisar floración y cuaje"),)),
    "pepino": StageTemplate(6, None, (
        _m(20, _VEG, "Tutorado", "Guiar en espaldera"),
        _m(35, _FLOWER, "Floración", "Revisar floración"),
    )),
    "melon": StageTemplate(7, None, (_m(45, _FLOWER, "Floración", "Revisar floración; despuntar guías"),)),
    "sandia": StageTemplate(7, None, (_m(45, _FLOWER, "Floración", "Revisar floración y cuaje"),)),
    "brocoli": StageTemplate(6, 30, (_m(60, _VEG, "Formación de pella", "Revisar pella y orugas"),)),
    "coliflor": StageTemplate(6, 30, (_m(70, _VEG, "Formación de pella", "Cubrir la pella con hojas"),)),
    "repollo": StageTemplate(6, 30, (_m(65, _VEG, "Acogollado", "Revisar orugas y riego"),)),
    "albahaca": StageTemplate(7, 30, (_m(45, _VEG, "Despunte", "Despuntar para ramificar y frenar la flor"),)),
    "perejil": StageTemplate(20, None, (_m(50, _VEG, "Primeros cortes", "Cortar hojas externas"),)),
    "frutilla": StageTemplate(15, None, (
        _m(60, _FLOWER, "Floración", "Revisar flores y poner mulch"),
        _m(90, _FRUIT, "Fructificación", "Cosechar seguido y sacar estolones"),
    )),
}


def _plain(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn").strip()


def template_for(crop_name: str, growth_period_days: Optional[int]) -> StageTemplate:
    """The crop's template, or a generic one from its growth period (direct sowing, one mid-cycle check)."""
    found = TEMPLATES.get(_plain(crop_name))
    if found:
        return found
    period = growth_period_days or 90
    return StageTemplate(
        emergence_days=max(5, min(14, round(period * 0.1))),
        milestones=(_m(round(period * 0.5), _VEG, "Mitad del ciclo", "Revisar estado general, riego y plagas"),),
    )


def harvest_window_days(growth_period_days: Optional[int]) -> int:
    """How long before the expected harvest date the "posible cosecha" check goes."""
    return max(7, round((growth_period_days or 90) * 0.1))
