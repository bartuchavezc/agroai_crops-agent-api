"""
Derived reading of a field's satellite time series, computed on read (nothing here is persisted: a few
hundred observations per field is trivial to recompute, and keeping it pure means tweaking a threshold
never needs a backfill).

Pipeline, all on the field's own history:
  1. clean    — drop passes with too little cloud-free surface, and isolated NDVI dips that rebound
                within days (residual cloud/haze the scene classification missed).
  2. smooth   — weighted Whittaker smoother on a daily grid (handles irregular gaps natively), fit to the
                upper envelope for greenness indices since leftover clouds only ever pull them down.
  3. normal   — for any date, the same date in each previous year (±3 days) of the smoothed curve:
                p10/p50/p90 across years = "what's normal for this week in this field".
  4. anomaly  — current value vs normal and vs last year, 15-day trend, streak of passes below p10.
  5. stages   — green-up / peak / decline on the current season's curve (the active crop cycle's
                planting date when there is one).
  6. radar    — when Sentinel-2 has a cloud gap, the Sentinel-1 cross-ratio trend over that gap as a
                qualitative continuity signal (never converted into an NDVI value).
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any, Iterable, Optional, Sequence

import numpy as np

GREENNESS = ("ndvi", "ndre", "evi")
METRICS = ("ndvi", "ndre", "ndmi", "evi", "ndwi")

DEFAULT_LAMBDA = 800.0  # daily grid; ~3-4 week effective smoothing window at Sentinel-2's ~5-day revisit
COVERAGE_DAYS = 20  # a smoothed day only counts as "observed" within this distance of a real pass
NORMAL_WINDOW_DAYS = 3
MIN_NORMAL_YEARS = 2
DIP_THRESHOLD = 0.12
DIP_MAX_GAP_DAYS = 20
MIN_SEASON_AMPLITUDE = 0.12
STALE_S2_DAYS = 15


def _num(obs: Any, attr: str) -> Optional[float]:
    value = getattr(obs, attr, None)
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _r(value: Optional[float], digits: int = 3) -> Optional[float]:
    return None if value is None else round(float(value), digits)


# ---------------------------------------------------------------- 1. clean


def clean_s2(observations: Sequence[Any], min_valid_fraction: float) -> list[Any]:
    """Keep passes with enough cloud-free surface, then drop isolated NDVI dips: a pass that sits well
    below BOTH neighbours (each within DIP_MAX_GAP_DAYS) is almost always residual cloud/haze, not a crop
    that lost and regained its canopy within two weeks."""
    kept = [
        o for o in sorted(observations, key=lambda o: o.observed_on)
        if _num(o, "ndvi_mean") is not None
        and (_num(o, "valid_fraction") is None or _num(o, "valid_fraction") >= min_valid_fraction)
    ]
    if len(kept) < 3:
        return kept
    result = [kept[0]]
    for prev, cur, nxt in zip(kept, kept[1:], kept[2:], strict=False):
        close = (cur.observed_on - prev.observed_on).days <= DIP_MAX_GAP_DAYS and (
            nxt.observed_on - cur.observed_on
        ).days <= DIP_MAX_GAP_DAYS
        v, a, b = _num(cur, "ndvi_mean"), _num(prev, "ndvi_mean"), _num(nxt, "ndvi_mean")
        if close and v < min(a, b) - DIP_THRESHOLD:
            continue
        result.append(cur)
    result.append(kept[-1])
    return result


# ---------------------------------------------------------------- 2. smooth


def _whittaker(y: np.ndarray, w: np.ndarray, lam: float) -> np.ndarray:
    """Solve (W + lam·DᵀD) z = W y with D the second-difference operator. The system is symmetric
    pentadiagonal, so a banded Cholesky keeps it O(n) for multi-year daily grids (no scipy needed)."""
    n = len(y)
    if n < 4:
        return y.copy()
    d0 = np.full(n, 6.0)
    d0[[0, -1]] = 1.0
    d0[[1, -2]] = 5.0
    d1 = np.full(n - 1, -4.0)
    d1[[0, -1]] = -2.0
    d2 = np.ones(n - 2)
    a0 = w + lam * d0 + 1e-9
    a1 = lam * d1
    a2 = lam * d2

    l0 = np.zeros(n)
    l1 = np.zeros(n)  # L[i, i-1]
    l2 = np.zeros(n)  # L[i, i-2]
    for i in range(n):
        if i >= 2:
            l2[i] = a2[i - 2] / l0[i - 2]
        if i >= 1:
            l1[i] = (a1[i - 1] - l2[i] * l1[i - 1]) / l0[i - 1]
        l0[i] = math.sqrt(max(a0[i] - l1[i] ** 2 - l2[i] ** 2, 1e-12))
    b = w * y
    z = np.zeros(n)
    for i in range(n):  # L z' = b
        acc = b[i]
        if i >= 1:
            acc -= l1[i] * z[i - 1]
        if i >= 2:
            acc -= l2[i] * z[i - 2]
        z[i] = acc / l0[i]
    x = np.zeros(n)
    for i in range(n - 1, -1, -1):  # Lᵀ x = z'
        acc = z[i]
        if i + 1 < n:
            acc -= l1[i + 1] * x[i + 1]
        if i + 2 < n:
            acc -= l2[i + 2] * x[i + 2]
        x[i] = acc / l0[i]
    return x


@dataclass
class SmoothedSeries:
    start: date
    values: np.ndarray
    covered: np.ndarray  # bool per day: within COVERAGE_DAYS of a real pass

    @property
    def end(self) -> date:
        return self.start + timedelta(days=len(self.values) - 1)

    def at(self, day: date) -> Optional[float]:
        i = (day - self.start).days
        if 0 <= i < len(self.values) and self.covered[i]:
            return float(self.values[i])
        return None

    def mean_around(self, day: date, half_window: int) -> Optional[float]:
        values = [
            v for d in range(-half_window, half_window + 1) if (v := self.at(day + timedelta(days=d))) is not None
        ]
        return float(np.mean(values)) if values else None


def smooth(
    observations: Sequence[Any], metric: str, lam: float = DEFAULT_LAMBDA, upper_envelope: Optional[bool] = None
) -> Optional[SmoothedSeries]:
    points = [(o.observed_on, _num(o, f"{metric}_mean"), _num(o, "valid_fraction")) for o in observations]
    points = [(d, v, 1.0 if f is None else max(0.2, f)) for d, v, f in points if v is not None]
    if len(points) < 3:
        return None
    start = points[0][0]
    n = (points[-1][0] - start).days + 1
    y = np.zeros(n)
    w = np.zeros(n)
    for d, v, f in points:
        i = (d - start).days
        y[i] = v
        w[i] = f
    z = _whittaker(y, w, lam)
    if upper_envelope if upper_envelope is not None else metric in GREENNESS:
        base = w.copy()
        for _ in range(2):
            w = np.where((base > 0) & (y < z), base * 0.5, base)
            z = _whittaker(y, w, lam)
    observed = np.zeros(n, dtype=bool)
    for d, _, _ in points:
        observed[(d - start).days] = True
    idx = np.flatnonzero(observed)
    nearest = np.min(np.abs(np.arange(n)[:, None] - idx[None, :]), axis=1) if n * len(idx) < 4_000_000 else None
    if nearest is None:  # very long series: walk instead of building the full distance matrix
        nearest = np.full(n, n)
        last = -n
        for i in range(n):
            if observed[i]:
                last = i
            nearest[i] = i - last
        last = 2 * n
        for i in range(n - 1, -1, -1):
            if observed[i]:
                last = i
            nearest[i] = min(nearest[i], last - i)
    return SmoothedSeries(start=start, values=z, covered=nearest <= COVERAGE_DAYS)


# ---------------------------------------------------------------- 3-4. normal & anomaly


def _same_day_years_ago(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year - years)
    except ValueError:  # Feb 29
        return day.replace(year=day.year - years, day=28)


@dataclass
class Normal:
    p10: Optional[float]
    p50: Optional[float]
    p90: Optional[float]
    n_years: int


def normal_at(series: SmoothedSeries, day: date, max_years: int = 10) -> Normal:
    """Distribution of this field's smoothed value on the same date (±3 days) in each previous year."""
    values = []
    for k in range(1, max_years + 1):
        past = _same_day_years_ago(day, k)
        if past < series.start:
            break
        v = series.mean_around(past, NORMAL_WINDOW_DAYS)
        if v is not None:
            values.append(v)
    if not values:
        return Normal(None, None, None, 0)
    arr = np.array(values)
    return Normal(
        p10=_r(np.percentile(arr, 10)), p50=_r(np.percentile(arr, 50)), p90=_r(np.percentile(arr, 90)),
        n_years=len(values),
    )


@dataclass
class MetricStatus:
    metric: str
    date: date
    value: Optional[float]  # smoothed value at the last valid pass
    raw: Optional[float]  # the pass's own mean
    trend_15d: Optional[float]
    normal_p10: Optional[float] = None
    normal_p50: Optional[float] = None
    normal_p90: Optional[float] = None
    normal_years: int = 0
    vs_normal: Optional[float] = None
    position: Optional[str] = None  # muy_por_debajo | por_debajo | normal | por_encima | muy_por_encima
    normal_trend_15d: Optional[float] = None
    last_year: Optional[float] = None
    vs_last_year: Optional[float] = None
    below_p10_streak: int = 0


def _position(value: float, normal: Normal) -> Optional[str]:
    if normal.n_years < MIN_NORMAL_YEARS or normal.p50 is None:
        return None
    if value < normal.p10:
        return "muy_por_debajo"
    if value > normal.p90:
        return "muy_por_encima"
    spread = max((normal.p90 - normal.p10) / 2, 0.02)
    if value < normal.p50 - spread / 2:
        return "por_debajo"
    if value > normal.p50 + spread / 2:
        return "por_encima"
    return "normal"


def metric_status(observations: Sequence[Any], metric: str, series: Optional[SmoothedSeries]) -> Optional[MetricStatus]:
    valid = [o for o in observations if _num(o, f"{metric}_mean") is not None]
    if not valid or series is None:
        return None
    last = valid[-1]
    day = last.observed_on
    value = series.at(day)
    before = series.at(day - timedelta(days=15))
    status = MetricStatus(
        metric=metric,
        date=day,
        value=_r(value),
        raw=_r(_num(last, f"{metric}_mean")),
        trend_15d=_r(value - before) if value is not None and before is not None else None,
    )
    if value is None:
        return status
    normal = normal_at(series, day)
    status.normal_p10, status.normal_p50, status.normal_p90 = normal.p10, normal.p50, normal.p90
    status.normal_years = normal.n_years
    if normal.n_years >= MIN_NORMAL_YEARS:
        status.vs_normal = _r(value - normal.p50)
        status.position = _position(value, normal)
        normal_before = normal_at(series, day - timedelta(days=15))
        if normal_before.p50 is not None:
            status.normal_trend_15d = _r(normal.p50 - normal_before.p50)
        streak = 0
        for obs in reversed(valid):
            v = series.at(obs.observed_on)
            n = normal_at(series, obs.observed_on)
            if v is None or n.n_years < MIN_NORMAL_YEARS or n.p10 is None or v >= n.p10:
                break
            streak += 1
        status.below_p10_streak = streak
    last_year = series.mean_around(_same_day_years_ago(day, 1), NORMAL_WINDOW_DAYS)
    if last_year is not None:
        status.last_year = _r(last_year)
        status.vs_last_year = _r(value - last_year)
    return status


# ---------------------------------------------------------------- 5. stages


@dataclass
class Phenology:
    season_from: date
    season_to: date
    season_source: str  # ciclo_de_cultivo | ventana_reciente
    stage: str  # sin_datos | sin_ciclo_marcado | pre_brote | crecimiento | pico | caida | fin_de_ciclo
    base: Optional[float] = None
    peak_value: Optional[float] = None
    peak_date: Optional[date] = None
    peak_provisional: bool = False
    green_up_date: Optional[date] = None
    decline_date: Optional[date] = None
    end_date: Optional[date] = None
    days_since_peak: Optional[int] = None
    last_year_peak_value: Optional[float] = None
    last_year_peak_date: Optional[date] = None


def _curve(series: SmoothedSeries, start: date, end: date) -> list[tuple[date, float]]:
    out = []
    day = max(start, series.start)
    while day <= min(end, series.end):
        v = series.at(day)
        if v is not None:
            out.append((day, v))
        day += timedelta(days=1)
    return out


def _peak(curve: list[tuple[date, float]]) -> Optional[tuple[date, float, float]]:
    if len(curve) < 20:
        return None
    peak_i = max(range(len(curve)), key=lambda i: curve[i][1])
    base = min(v for _, v in curve[: peak_i + 1])
    return curve[peak_i][0], curve[peak_i][1], base


def phenology(series: Optional[SmoothedSeries], start: date, end: date, source: str) -> Phenology:
    result = Phenology(season_from=start, season_to=end, season_source=source, stage="sin_datos")
    if series is None:
        return result
    curve = _curve(series, start, end)
    found = _peak(curve)
    if not found:
        return result
    peak_day, peak_value, base = found
    amplitude = peak_value - base
    result.base, result.peak_value = _r(base), _r(peak_value)
    if amplitude < MIN_SEASON_AMPLITUDE:
        result.stage = "sin_ciclo_marcado"
        return result
    low, high = base + 0.2 * amplitude, base + 0.8 * amplitude
    peak_i = next(i for i, (d, _) in enumerate(curve) if d == peak_day)
    base_i = min(range(peak_i + 1), key=lambda i: curve[i][1])
    result.green_up_date = next((d for d, v in curve[base_i: peak_i + 1] if v >= low), None)
    after = curve[peak_i + 1:]
    result.decline_date = next((d for d, v in after if v < high), None)
    result.end_date = next((d for d, v in after if v < low), None)
    last_day, last_value = curve[-1]
    rising = len(curve) > 10 and last_value - curve[-11][1] > 0.01
    if (last_day - peak_day).days <= 10 and rising:
        result.stage = "crecimiento"
        result.peak_provisional = True
    elif result.end_date:
        result.stage = "fin_de_ciclo"
    elif result.decline_date:
        result.stage = "caida"
    elif last_value >= high:
        result.stage = "pico"
    elif result.green_up_date:
        result.stage = "crecimiento"
    else:
        result.stage = "pre_brote"
    result.peak_date = peak_day
    result.days_since_peak = (last_day - peak_day).days if not result.peak_provisional else None

    last_year = _peak(_curve(series, _same_day_years_ago(start, 1), _same_day_years_ago(end, 1)))
    if last_year:
        result.last_year_peak_date, result.last_year_peak_value = last_year[0], _r(last_year[1])
    return result


# ---------------------------------------------------------------- 6. radar


@dataclass
class RadarSignal:
    last_date: date
    vh_vv_db: Optional[float]
    rvi: Optional[float]
    gap_from: Optional[date] = None  # last clear Sentinel-2 pass the radar trend is measured from
    passes_in_gap: int = 0
    vh_vv_change_db: Optional[float] = None
    trend: Optional[str] = None  # sube | estable | baja


def radar_signal(s1: Sequence[Any], last_s2: Optional[date], today: date) -> Optional[RadarSignal]:
    passes = [o for o in sorted(s1, key=lambda o: o.observed_on) if _num(o, "vh_vv_db") is not None]
    if not passes:
        return None
    last = passes[-1]
    signal = RadarSignal(
        last_date=last.observed_on, vh_vv_db=_r(_num(last, "vh_vv_db"), 2), rvi=_r(_num(last, "rvi_mean"))
    )
    if last_s2 is not None and (today - last_s2).days <= STALE_S2_DAYS:
        return signal
    signal.gap_from = last_s2
    anchor = [o for o in passes if last_s2 is None or o.observed_on <= last_s2]
    in_gap = [o for o in passes if last_s2 is None or o.observed_on > last_s2]
    signal.passes_in_gap = len(in_gap)
    reference = anchor[-1] if anchor else (in_gap[0] if len(in_gap) > 1 else None)
    if reference is not None and in_gap and reference is not in_gap[-1]:
        change = _num(in_gap[-1], "vh_vv_db") - _num(reference, "vh_vv_db")
        signal.vh_vv_change_db = _r(change, 2)
        signal.trend = "sube" if change >= 1.0 else "baja" if change <= -1.0 else "estable"
    return signal


# ---------------------------------------------------------------- full analysis


@dataclass
class SeriesAnalysis:
    as_of: date
    has_data: bool
    history_from: Optional[date] = None
    s2_passes: int = 0
    s2_clear_passes: int = 0
    last_pass: Optional[dict] = None
    days_since_last_pass: Optional[int] = None
    metrics: dict[str, dict] = field(default_factory=dict)
    phenology: Optional[dict] = None
    radar: Optional[dict] = None
    caveats: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return _jsonable(asdict(self))

    def status(self, metric: str) -> Optional[dict]:
        return self.metrics.get(metric)


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, date):
        return value.isoformat()
    return value


def analyze(
    s2: Sequence[Any],
    s1: Sequence[Any],
    today: date,
    season: Optional[tuple[date, Optional[date]]] = None,
    min_valid_fraction: float = 0.6,
) -> SeriesAnalysis:
    """season: (planting_date, harvest_date or None) of the field's active crop cycle, if any."""
    clean = clean_s2(s2, min_valid_fraction)
    result = SeriesAnalysis(as_of=today, has_data=bool(clean), s2_passes=len(s2), s2_clear_passes=len(clean))
    if s2:
        result.history_from = min(o.observed_on for o in s2)
    last_s2 = clean[-1].observed_on if clean else None
    radar = radar_signal(s1, last_s2, today)
    result.radar = asdict(radar) if radar else None
    if not clean:
        result.caveats.append("Todavía no hay pasadas de Sentinel-2 sin nubes para este campo.")
        return result

    last = clean[-1]
    result.last_pass = {
        "date": last.observed_on,
        "valid_fraction": _r(_num(last, "valid_fraction"), 2),
        "valid_pixels": getattr(last, "valid_pixels", None),
        **{f"{m}_mean": _r(_num(last, f"{m}_mean")) for m in METRICS},
        "ndvi_std": _r(_num(last, "ndvi_std")),
        "ndvi_p10": _r(_num(last, "ndvi_p10")),
        "ndvi_p90": _r(_num(last, "ndvi_p90")),
    }
    result.days_since_last_pass = (today - last.observed_on).days

    smoothed: dict[str, Optional[SmoothedSeries]] = {}
    for metric in METRICS:
        smoothed[metric] = smooth(clean, metric)
        status = metric_status(clean, metric, smoothed[metric])
        if status:
            result.metrics[metric] = asdict(status)

    if season and season[0]:
        start = season[0] - timedelta(days=15)
        end = min(season[1], today) if season[1] else today
        source = "ciclo_de_cultivo"
    else:
        start, end, source = today - timedelta(days=300), today, "ventana_reciente"
    result.phenology = asdict(phenology(smoothed["ndvi"], start, end, source))

    ndvi = result.metrics.get("ndvi") or {}
    years = ndvi.get("normal_years", 0)
    if years < MIN_NORMAL_YEARS:
        result.caveats.append(
            f"Historia corta ({years} año(s) previos con datos para esta fecha): todavía no hay un 'normal' "
            "confiable para comparar; solo vale la comparación contra pasadas recientes."
        )
    if result.days_since_last_pass > STALE_S2_DAYS:
        result.caveats.append(
            f"La última pasada de Sentinel-2 sin nubes es de hace {result.days_since_last_pass} días; "
            "lo que pasó después no se ve en el óptico" + (" (ver señal de radar)." if radar else ".")
        )
    vf = _num(last, "valid_fraction")
    if vf is not None and vf < 0.8:
        result.caveats.append(f"La última pasada vio solo el {vf:.0%} del campo libre de nubes.")
    pixels = getattr(last, "valid_pixels", None)
    if pixels is not None and pixels <= 8:
        result.caveats.append(
            f"Estimado sobre pocos píxeles Sentinel-2 ({pixels}, de 10m c/u): tomalo como orientativo."
        )
    if (ndvi.get("value") or 0) >= 0.8:
        result.caveats.append("NDVI cerca de saturación (canopeo denso): para diferencias de vigor mirá NDRE.")
    return result


# ---------------------------------------------------------------- tables for the agent / API


def weekly_table(
    s2: Sequence[Any], metric: str, since: date, today: date, min_valid_fraction: float = 0.6, max_rows: int = 60
) -> list[dict]:
    """Week-by-week view of one metric since `since`: the raw mean of that week's clear passes, the
    smoothed curve, this field's normal band and last year's value. Coarsened to at most `max_rows`."""
    clean = clean_s2(s2, min_valid_fraction)
    series = smooth(clean, metric)
    if series is None:
        return []
    start = since - timedelta(days=since.weekday())
    weeks = max(1, (today - start).days // 7 + 1)
    step = max(1, math.ceil(weeks / max_rows))
    rows = []
    week = start
    while week <= today:
        week_end = week + timedelta(days=7 * step - 1)
        raws = [
            v for o in clean if week <= o.observed_on <= week_end and (v := _num(o, f"{metric}_mean")) is not None
        ]
        mid = week + timedelta(days=(7 * step) // 2)
        smoothed = series.at(min(mid, series.end))
        normal = normal_at(series, mid)
        last_year = series.mean_around(_same_day_years_ago(mid, 1), NORMAL_WINDOW_DAYS)
        if raws or smoothed is not None:
            rows.append(
                {
                    "week": week.isoformat(),
                    "passes": len(raws),
                    "raw": _r(float(np.mean(raws))) if raws else None,
                    "smoothed": _r(smoothed),
                    "normal_p10": normal.p10 if normal.n_years >= MIN_NORMAL_YEARS else None,
                    "normal_p50": normal.p50 if normal.n_years >= MIN_NORMAL_YEARS else None,
                    "normal_p90": normal.p90 if normal.n_years >= MIN_NORMAL_YEARS else None,
                    "last_year": _r(last_year),
                }
            )
        week += timedelta(days=7 * step)
    return rows


def raw_points(observations: Iterable[Any], metrics: Sequence[str]) -> list[dict]:
    return [
        {"date": o.observed_on.isoformat(), "valid_fraction": _r(_num(o, "valid_fraction"), 2),
         **{m: _r(_num(o, m)) for m in metrics}}
        for o in observations
    ]
