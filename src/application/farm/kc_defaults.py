"""
FAO-56 standard crop coefficients (Kc) by botanical family, used as a fallback when a crop in the
catalog has no Kc of its own — this is what lets get_irrigation_recommendation work for the whole
existing catalog on day one, instead of blocking on completing Kc for every crop first.

These are widely-published FAO-56 reference ranges picked for common family members, not lab-measured
values for this account's exact varieties — reviewing them is listed as a pending user action, since they
directly drive irrigation recommendations.
"""
from typing import Optional

# family -> (kc_initial, kc_mid, kc_late)
FAMILY_KC_DEFAULTS: dict[str, tuple[float, float, float]] = {
    "Solanaceae": (0.6, 1.15, 0.80),  # tomate, pimiento, berenjena, papa
    "Cucurbitaceae": (0.5, 1.00, 0.80),  # zapallo, calabacín, pepino, melón, sandía
    "Brassicaceae": (0.7, 1.05, 0.95),  # repollo, brócoli, coliflor, rúcula
    "Fabaceae": (0.5, 1.05, 0.90),  # arveja, poroto, haba
    "Apiaceae": (0.7, 1.05, 0.95),  # zanahoria, apio, perejil
    "Amaryllidaceae": (0.7, 1.05, 0.75),  # cebolla, ajo, puerro
    "Asteraceae": (0.7, 1.00, 0.95),  # lechuga, alcaucil
    "Poaceae": (0.3, 1.20, 0.35),  # maíz, choclo
    "Chenopodiaceae": (0.7, 1.00, 0.95),  # acelga, espinaca, remolacha
    "Vitaceae": (0.3, 0.85, 0.45),  # vid
    "Rosaceae": (0.45, 0.90, 0.65),  # frutales de carozo/pepita
}
GENERIC_KC: tuple[float, float, float] = (0.5, 1.0, 0.85)


def kc_for_stage(
    kc_initial: Optional[float],
    kc_mid: Optional[float],
    kc_late: Optional[float],
    family: Optional[str],
    progress_pct: float,
) -> float:
    """Kc for the cycle's current stage (0-100% through its growth period). Explicit per-crop Kc wins
    field by field; a missing one falls back to the family default, then to a generic estimate."""
    fam_i, fam_m, fam_l = FAMILY_KC_DEFAULTS.get(family, GENERIC_KC) if family else GENERIC_KC
    ki = kc_initial if kc_initial is not None else fam_i
    km = kc_mid if kc_mid is not None else fam_m
    kl = kc_late if kc_late is not None else fam_l
    if progress_pct <= 25:
        return ki
    if progress_pct <= 75:
        return km
    return kl
