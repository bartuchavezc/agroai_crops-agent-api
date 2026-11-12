"""Weather-driven disease risk, from published decision-support models. Leaf wetness is approximated by hours with
relative humidity ≥ 90 % (no leaf-wetness sensor): a known, conservative proxy.

- TOM-CAST (Pitblado 1988; tizón temprano / Alternaria, septoriosis y antracnosis del tomate): daily severity values
  (DSV 0–4) from wet hours and their mean temperature; accumulated DSV ≥ 15–20 calls for protection.
- BLITECAST / Wallin (tizón tardío, Phytophthora infestans, tomate y papa): severity values from consecutive hours of
  RH ≥ 90 % and their mean temperature; 7-day sums ≥ 3 are a warning, ≥ 5 a high risk.
- Oídio (Gubler-Thomas index, UC Davis): +20 for each day with ≥ 6 consecutive hours between 21 and 30 °C, −10
  otherwise; ≥ 60 is high pressure.
- Fulvia (moho foliar del tomate, Passalora fulva): hours with RH ≥ 85 % at 18–26 °C; ≥ 10 h a day on 2+ days is high.
- Mildiu (downy mildews): ≥ 6 wet hours with a mean of 15–24 °C on 2+ consecutive days is high.

Outputs are indices with their inputs, never a diagnosis: the agent decides what to check."""
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Literal, Optional

Level = Literal["bajo", "medio", "alto"]


@dataclass
class Hour:
    time: str  # ISO local time
    temperature: Optional[float]
    humidity: Optional[float]

    @property
    def day(self) -> str:
        return self.time[:10]


@dataclass
class Risk:
    disease: str
    model: str
    level: Level
    index: float
    detail: str
    daily: list[dict] = field(default_factory=list)


def _by_day(hours: list[Hour]) -> dict[str, list[Hour]]:
    out: dict[str, list[Hour]] = defaultdict(list)
    for h in hours:
        out[h.day].append(h)
    return dict(sorted(out.items()))


def _wet(h: Hour, rh: float = 90) -> bool:
    return h.humidity is not None and h.temperature is not None and h.humidity >= rh


def tomcast_dsv(wet_hours: int, mean_t: float) -> int:
    rows = [
        (13, 17, [(6, 0), (15, 1), (20, 2), (999, 3)]),
        (18, 20, [(3, 0), (8, 1), (15, 2), (22, 3), (999, 4)]),
        (21, 25, [(2, 0), (5, 1), (12, 2), (20, 3), (999, 4)]),
        (26, 29, [(3, 0), (8, 1), (15, 2), (22, 3), (999, 4)]),
    ]
    for lo, hi, steps in rows:
        if lo <= mean_t < hi + 1:
            for limit, value in steps:
                if wet_hours <= limit:
                    return value
    return 0


def tomcast(hours: list[Hour]) -> Risk:
    daily, total = [], 0
    for day, hs in _by_day(hours).items():
        wet = [h for h in hs if _wet(h)]
        mean_t = sum(h.temperature for h in wet) / len(wet) if wet else 0.0
        dsv = tomcast_dsv(len(wet), mean_t) if wet else 0
        total += dsv
        daily.append({"date": day, "wet_hours": len(wet), "mean_t_wet": round(mean_t, 1), "dsv": dsv})
    level: Level = "alto" if total >= 20 else "medio" if total >= 15 else "bajo"
    return Risk("tizón temprano / septoriosis (tomate)", "TOM-CAST", level, total,
                f"DSV acumulado {total} en {len(daily)} días (umbral 15-20)", daily)


def wallin_sv(hours_wet: int, mean_t: float) -> int:
    if 7.2 <= mean_t <= 11.6:
        steps = [(15, 0), (18, 1), (21, 2), (24, 3)]
    elif 11.6 < mean_t <= 15.0:
        steps = [(12, 0), (15, 1), (18, 2), (21, 3)]
    elif 15.0 < mean_t <= 26.6:
        steps = [(9, 0), (12, 1), (15, 2), (18, 3)]
    else:
        return 0
    for limit, value in steps:
        if hours_wet < limit:
            return value
    return 4


def blitecast(hours: list[Hour], window_days: int = 7) -> Risk:
    """Severity values per run of consecutive RH ≥ 90 % hours, credited to the day the run ends."""
    by_day: dict[str, int] = defaultdict(int)
    run: list[Hour] = []
    for h in [*hours, Hour("9999-99-99T00:00", None, None)]:
        if _wet(h):
            run.append(h)
            continue
        if run:
            mean_t = sum(x.temperature for x in run) / len(run)
            by_day[run[-1].day] += wallin_sv(len(run), mean_t)
            run = []
    days = sorted({h.day for h in hours})
    recent = days[-window_days:]
    total = sum(by_day.get(d, 0) for d in recent)
    level: Level = "alto" if total >= 5 else "medio" if total >= 3 else "bajo"
    return Risk("tizón tardío (tomate, papa)", "BLITECAST (Wallin)", level, total,
                f"Valores de severidad en {len(recent)} días: {total} (alerta ≥ 3, alto ≥ 5)",
                [{"date": d, "sv": by_day.get(d, 0)} for d in recent])


def powdery_mildew(hours: list[Hour]) -> Risk:
    index, daily = 0, []
    for day, hs in _by_day(hours).items():
        best = streak = 0
        for h in hs:
            streak = streak + 1 if h.temperature is not None and 21 <= h.temperature <= 30 else 0
            best = max(best, streak)
        index = min(100, index + 20) if best >= 6 else max(0, index - 10)
        daily.append({"date": day, "hours_21_30": best, "index": index})
    level: Level = "alto" if index >= 60 else "medio" if index >= 40 else "bajo"
    return Risk("oídio", "Gubler-Thomas", level, index, f"Índice {index}/100 (alto ≥ 60)", daily)


def leaf_mold(hours: list[Hour]) -> Risk:
    daily, favorable = [], 0
    for day, hs in _by_day(hours).items():
        n = sum(1 for h in hs if _wet(h, 85) and 18 <= h.temperature <= 26)
        daily.append({"date": day, "hours": n})
        favorable += n >= 10
    recent = daily[-7:]
    count = sum(1 for d in recent if d["hours"] >= 10)
    level: Level = "alto" if count >= 2 else "medio" if count == 1 else "bajo"
    return Risk("moho foliar (Fulvia, tomate)", "HR ≥ 85 % a 18-26 °C", level, count,
                f"{count} días favorables en los últimos {len(recent)} (alto con 2)", recent)


def downy_mildew(hours: list[Hour]) -> Risk:
    daily, streak, best = [], 0, 0
    for day, hs in _by_day(hours).items():
        wet = [h for h in hs if _wet(h)]
        mean_t = sum(h.temperature for h in wet) / len(wet) if wet else 0
        ok = len(wet) >= 6 and 15 <= mean_t <= 24
        streak = streak + 1 if ok else 0
        best = max(best, streak)
        daily.append({"date": day, "wet_hours": len(wet), "mean_t_wet": round(mean_t, 1), "favorable": ok})
    level: Level = "alto" if best >= 2 else "medio" if best == 1 else "bajo"
    return Risk("mildiu", "humedad ≥ 90 % ≥ 6 h a 15-24 °C", level, best,
                f"{best} días seguidos favorables (alto con 2)", daily[-7:])


MODELS = {"tomcast": tomcast, "blitecast": blitecast, "oidio": powdery_mildew, "fulvia": leaf_mold,
          "mildiu": downy_mildew}
# Which models are worth running for a crop.
BY_CROP = {
    "tomate": ("tomcast", "blitecast", "oidio", "fulvia"), "papa": ("blitecast", "tomcast"),
    "pimiento": ("oidio", "tomcast"), "morron": ("oidio", "tomcast"), "berenjena": ("oidio",),
    "zapallo": ("oidio", "mildiu"), "zapallito": ("oidio", "mildiu"), "pepino": ("oidio", "mildiu"),
    "melon": ("oidio", "mildiu"), "sandia": ("oidio", "mildiu"), "lechuga": ("mildiu",), "cebolla": ("mildiu",),
    "espinaca": ("mildiu",), "albahaca": ("mildiu",), "vid": ("mildiu", "oidio"), "frutilla": ("oidio",),
    "arveja": ("oidio", "mildiu"),
}


def run(hours: list[Hour], models: list[str]) -> list[Risk]:
    return [MODELS[m](hours) for m in models if m in MODELS]
