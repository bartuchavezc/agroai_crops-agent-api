from src.application.farm.kc_defaults import GENERIC_KC, kc_for_stage


def test_explicit_kc_wins_over_family_default():
    assert kc_for_stage(0.9, None, None, "Solanaceae", progress_pct=10) == 0.9


def test_family_default_used_when_crop_has_no_explicit_kc():
    ki = kc_for_stage(None, None, None, "Solanaceae", 10)
    km = kc_for_stage(None, None, None, "Solanaceae", 50)
    kl = kc_for_stage(None, None, None, "Solanaceae", 90)
    assert (ki, km, kl) == (0.6, 1.15, 0.80)


def test_unknown_family_falls_back_to_generic():
    assert kc_for_stage(None, None, None, "Familia inexistente", 50) == GENERIC_KC[1]


def test_no_family_falls_back_to_generic():
    assert kc_for_stage(None, None, None, None, 50) == GENERIC_KC[1]


def test_stage_boundaries():
    # <=25% initial, <=75% mid, >75% late
    assert kc_for_stage(0.1, 0.5, 0.9, None, 0) == 0.1
    assert kc_for_stage(0.1, 0.5, 0.9, None, 25) == 0.1
    assert kc_for_stage(0.1, 0.5, 0.9, None, 26) == 0.5
    assert kc_for_stage(0.1, 0.5, 0.9, None, 75) == 0.5
    assert kc_for_stage(0.1, 0.5, 0.9, None, 76) == 0.9
    assert kc_for_stage(0.1, 0.5, 0.9, None, 100) == 0.9
