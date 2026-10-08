from collections import Counter

from src.scripts.parse_omri_pdf import (
    Block,
    Company,
    Line,
    clean_name,
    normalize_country,
    parse_company,
    split_glued_names,
)

BASE, IND = 30.0, 34.3
NOTE = "Se puede usar solamente si se cumplen los"
BOILERPLATE = Counter({NOTE: 10, "requisitos de la sección 205.206(e).": 10})


def block(*lines: tuple[float, str]) -> Block:
    return Block(0, [Line(x, text) for x, text in lines])


def run(*blocks: Block) -> list[dict]:
    return parse_company(Company("Acme S.A.", "Mexico", "www.acme.com", list(blocks)), BOILERPLATE)


def test_products_take_scope_category_and_company():
    rows = run(block((BASE, "Productos para cultivos: Pesticidas botánicos"), (IND, "Neem Plus (abc-1234)")))
    assert rows[0]["omri_id"] == "abc-1234"
    assert (rows[0]["scope"], rows[0]["category"]) == ("cultivos", "Pesticidas botánicos")
    assert (rows[0]["company"], rows[0]["company_country"]) == ("Acme S.A.", "Mexico")


def test_wrapped_name_and_code_split_over_two_lines():
    rows = run(block(
        (BASE, "Productos para cultivos: Algas"), (IND, "Seaweed Extract 0.5 l 0.0 l 17 (acd-"), (IND, "2743)"),
    ))
    assert rows[0]["omri_id"] == "acd-2743"
    assert rows[0]["name"] == "Seaweed Extract 0.5-0.0-17"


def test_marker_and_note_in_same_block():
    rows = run(block(
        (BASE, "Productos para cultivos: Citoquininas"), (IND, "Stimplex (acd-3508) l"), (IND, NOTE),
        (IND, "requisitos de la sección 205.206(e)."),
    ))
    assert rows[0]["restricted"] is True
    assert rows[0]["restriction_note"].startswith("Se puede usar solamente")


def test_note_in_the_next_block_when_the_code_line_closes_its_block():
    rows = run(
        block((BASE, "Productos para cultivos: Citoquininas"), (IND, "Stimplex (acd-3508) l")),
        block((IND, NOTE), (IND, "requisitos de la sección 205.206(e).")),
        block((IND, "Otro Producto (acd-3509)")),
    )
    assert [r["omri_id"] for r in rows] == ["acd-3508", "acd-3509"]
    assert rows[0]["restriction_note"].startswith("Se puede usar")
    assert rows[1]["restricted"] is False and rows[1]["restriction_note"] == ""


def test_consecutive_marked_products_without_notes_are_all_kept():
    rows = run(block(
        (BASE, "Productos para cultivos: Pescado"), (IND, "Fish Solubles 5-1-1 (due-2785) n o"),
        (IND, "Fish Solubles 4-1-1 (due-2786) n o"), (IND, "Fish Solubles 3-1-1 (due-3403)"),
    ))
    assert [r["omri_id"] for r in rows] == ["due-2785", "due-2786", "due-3403"]
    assert [r["restricted"] for r in rows] == [True, True, False]


def test_at_sign_marker_is_not_taken_for_an_email():
    # "@" after a code is a bullet glyph; the block must still be read as products
    rows = run(block((BASE, "Productos para cultivos: Dolomita"), (IND, "Ground Dolomite (agc-9965) @")))
    assert rows[0]["restricted"]


def test_company_without_contact_block_gets_its_own_identity():
    rows = run(
        block((BASE, "Productos para cultivos: Inoculantes"), (IND, "BioTango (ast-14870)")),
        block((BASE, "Active Organics")),
        block((IND, "Heat Shield (ast-16195)")),
    )
    assert (rows[0]["company"], rows[0]["company_country"]) == ("Acme S.A.", "Mexico")
    assert (rows[1]["company"], rows[1]["company_country"], rows[1]["category"]) == ("Active Organics", "", "")


def test_wrapped_heading_split_over_a_block_is_not_a_company():
    rows = run(
        block((BASE, "Productos para cultivos: Fertilizantes,")),
        block((BASE, "formulados con micronutrientes"), (IND, "Zinc Foliar (zzz-1111)")),
    )
    assert rows[0]["company"] == "Acme S.A."


def test_company_name_glued_to_the_tail_of_the_previous_products_is_split_off():
    products = block(
        (BASE, "Productos para cultivos: Minerales"), (IND, "Limestone Feed (bmm-2610)"), (BASE, "Blue Ocean"),
    )
    contact = block(
        (BASE, "Mark Anderson"), (BASE, "Fresno, CA"), (BASE, "United States"), (BASE, "www.blueocean.com"),
    )
    out = split_glued_names([products, contact])
    assert [ln.text for ln in out[1].lines] == ["Blue Ocean"]
    assert len(out[0].lines) == 2


def test_country_and_name_normalisation():
    assert {normalize_country(v) for v in ("USA", "United States", "United States of America")} == {"United States"}
    assert {normalize_country(v) for v in ("MEXICO", "México", "Mexico")} == {"Mexico"}
    assert clean_name("Powder 0.5 l 0.0 l 17") == "Powder 0.5-0.0-17"
