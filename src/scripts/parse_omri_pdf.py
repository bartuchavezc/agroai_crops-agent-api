"""
One-off ETL: turns the OMRI "Lista de Productos" PDF (Spanish edition, 3 columns per page, organised by
company) into the seed CSV `src/scripts/seeds/products/omri_nop_2026.csv` read by `seed_products`.

    pdftotext must be installed (poppler). Then:
    uv run python -m src.scripts.parse_omri_pdf /path/CompleteCompany-NOP-ES.pdf

Layout the parser relies on (verified on the 2026 edition), read through `pdftotext -bbox-layout`:
  - each page has 3 columns at x ≈ 30 / 214 / 397; inside a column, blocks are sorted by y;
  - company name block, then its contact block (person, address, country, phone, email, web);
  - category headings sit at the column's base x; products and their notes are indented by ~4 pt;
  - a product ends with its OMRI code `(abc-12345)`, optionally followed by a bullet glyph (`l`, `nl o`, ...) = "has
    use conditions". The notes are boilerplate sentences repeated verbatim all over the document (same column
    width, same wrapping), while product names are unique: after a marker, lines that repeat >= NOTE_MIN_REPEATS times
    are the note, and the first line that doesn't starts the next product.
    The code can be split over two lines or lose its hyphen, and the hyphen inside fertilizer analyses (0.5-0.0-17)
    is printed as an `l` between digits.

Only business data is kept (company, country, website). Contact people, addresses, phones and emails in the PDF
are deliberately dropped.
"""
import csv
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

OUT = Path(__file__).resolve().parent / "seeds" / "products" / "omri_nop_2026.csv"
COLUMN_BASES = (30.0, 214.0, 397.0)
NOTE_MIN_REPEATS = 4  # a line repeated this many times verbatim is use-condition boilerplate, not a product name
INDENT_MIN, INDENT_MAX = 2.0, 8.0  # products/notes are indented ~4.3 pt from the column base
CODE = re.compile(r"\(\s*([a-z]{3})\s?-?\s?(\d{3,5})\s*\)")
MARKER = re.compile(r"^[\sln o@●■○•]+$")  # bullet glyphs printed as letters/symbols after the code
COUNTRIES = {
    "usa": "United States", "u.s.a.": "United States", "united states": "United States",
    "united states of america": "United States", "mexico": "Mexico", "méxico": "Mexico", "canada": "Canada",
    "brasil": "Brazil", "españa": "Spain", "alemania": "Germany", "italia": "Italy", "francia": "France",
}
FOOTER = re.compile(r"^Lista (completa de productos por empresa|de Productos OMRI)", re.IGNORECASE)
COMPANY_SUFFIX = re.compile(r"\b(inc|llc|ltd|s\.?a\.?|gmbh|corp|co|plc|ag|b\.?v\.?|s\.?r\.?l\.?)\b", re.IGNORECASE)
HEADING = re.compile(r"^Productos para ([^:]+):\s*(.*)$", re.IGNORECASE)
CONTACT_HINT = re.compile(r"(\S@\S|^www\.|^https?://|^P:\s*\+?\d)", re.IGNORECASE)
FIELDS = (
    "omri_id", "name", "scope", "category", "company", "company_country", "company_website", "restricted",
    "restriction_note",
)


@dataclass
class Line:
    x: float
    text: str


@dataclass
class Block:
    column: int
    lines: list[Line]

    @property
    def base_x(self) -> float:
        return COLUMN_BASES[self.column]

    def indented(self, line: Line) -> bool:
        return INDENT_MIN <= line.x - self.base_x <= INDENT_MAX


@dataclass
class Company:
    name: str
    country: str = ""
    website: str = ""
    blocks: list[Block] = field(default_factory=list)


def read_blocks(pdf_path: Path) -> list[Block]:
    xml = subprocess.run(
        ["pdftotext", "-bbox-layout", str(pdf_path), "-"], check=True, capture_output=True, text=True
    ).stdout
    xml = re.sub(r"<!DOCTYPE[^>]*>", "", xml).replace('xmlns="http://www.w3.org/1999/xhtml"', "")
    blocks: list[Block] = []
    for page in ET.fromstring(xml).iter("page"):
        width = float(page.get("width"))
        page_blocks = []
        for b in page.iter("block"):
            lines = [Line(float(ln.get("xMin")), " ".join(w.text or "" for w in ln.iter("word")).strip())
                     for ln in b.iter("line")]
            lines = [ln for ln in lines if ln.text and not FOOTER.match(ln.text)]
            if not lines:
                continue
            if float(b.get("xMin")) > width * 0.9 or re.fullmatch(r"\d+", lines[0].text):
                continue  # page number
            # pdftotext sometimes merges lines of two neighbouring columns into one block: split them by line x
            per_col: dict[int, list[Line]] = {}
            for ln in lines:
                per_col.setdefault(min(range(3), key=lambda i: abs(ln.x - COLUMN_BASES[i])), []).append(ln)
            for col, col_lines in per_col.items():
                page_blocks.append((col, float(b.get("yMin")), Block(col, col_lines)))
        blocks.extend(b for _, _, b in sorted(page_blocks, key=lambda t: (t[0], t[1])))
    return blocks


def normalize_country(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    return COUNTRIES.get(value.casefold(), value.title() if value.isupper() else value)


def is_contact(block: Block) -> bool:
    return any(CONTACT_HINT.search(ln.text) for ln in block.lines)


def contact_info(block: Block) -> tuple[str, str]:
    """(country, website) from a contact block: the country is the line right before the phone/email/web lines."""
    texts = [ln.text for ln in block.lines]
    first = next((i for i, t in enumerate(texts) if CONTACT_HINT.search(t)), None)
    country = texts[first - 1] if first and first > 0 else ""
    web = next((t for t in texts if re.match(r"^(https?://|www\.)", t, re.IGNORECASE)), "")
    return normalize_country(country), web.strip()


def split_glued_names(blocks: list[Block]) -> list[Block]:
    """The block right before a contact block is the company name. When it also holds the tail of the previous
    company's products (heading/indented/code lines), only its trailing flush-left lines are the name."""
    out: list[Block] = []
    for i, block in enumerate(blocks):
        nxt = blocks[i + 1] if i + 1 < len(blocks) else None
        if nxt is not None and is_contact(nxt) and not is_contact(block):
            lines = block.lines
            keep = 0
            for k, ln in enumerate(lines):
                if block.indented(ln) or CODE.search(ln.text) or HEADING.match(ln.text):
                    keep = k + 1
            if 0 < keep < len(lines):
                out.append(Block(block.column, lines[:keep]))
                out.append(Block(block.column, lines[keep:]))
                continue
        out.append(block)
    return out


def group_by_company(blocks: list[Block]) -> list[Company]:
    blocks = split_glued_names(blocks)
    """A contact block is always preceded by its company-name block; everything up to the next company's name
    block belongs to this company."""
    contact_idx = [i for i, b in enumerate(blocks) if is_contact(b)]
    companies = []
    for n, i in enumerate(contact_idx):
        name_block = blocks[i - 1]
        country, web = contact_info(blocks[i])
        end = contact_idx[n + 1] - 1 if n + 1 < len(contact_idx) else len(blocks)
        companies.append(Company(" ".join(ln.text for ln in name_block.lines), country, web, blocks[i + 1:end]))
    return companies


def clean_name(text: str) -> str:
    text = re.sub(r"(?<=\d)\s?l\s?(?=\d)", "-", text)  # analysis hyphen printed as 'l'
    return re.sub(r"\s+", " ", text).strip(" ,;")


def parse_company(company: Company, boilerplate: Counter) -> list[dict]:
    rows: list[dict] = []
    name, country, website = company.name, company.country, company.website
    scope = category = ""
    heading: list[str] = []
    buf: list[str] = []  # name lines of the product being read (can span a block/column break)
    current: dict | None = None  # product whose note we are collecting
    note: list[str] = []
    awaiting = False  # the last product had a marker but its block ended: the next block is its note

    def finish_note() -> None:
        nonlocal current, note
        if current is not None and note:
            current["restriction_note"] = re.sub(r"\s+", " ", " ".join(note)).strip()
        current, note = None, []

    last: dict | None = None  # most recent product, in case its marker lands alone in the next block
    after_heading = False  # previous block ended on a flush-left line: a heading wrapped over a column break
    for block in company.blocks:
        if last is not None and len(block.lines) == 1 and MARKER.match(block.lines[0].text):
            last["restricted"], current, note, awaiting = True, last, [], True
            last = None
            continue
        if awaiting:
            first = block.lines[0]
            text = " ".join(ln.text for ln in block.lines)
            if block.indented(first) and boilerplate[first.text] >= NOTE_MIN_REPEATS and not CODE.search(text):
                note = [text]
                finish_note()
                awaiting = False
                continue
            current, awaiting = None, False
        first = block.lines[0]
        if (
            not block.indented(first)
            and not HEADING.match(first.text)
            and not after_heading
            and not (first.text[:1].islower() and not COMPANY_SUFFIX.search(first.text))
        ):
            # A flush-left line that isn't a category heading starts a company that has no contact block
            # (name straight followed by its products): new identity, nothing inherited from the previous company.
            n = 0
            while n < len(block.lines) and not (
                block.indented(block.lines[n]) or HEADING.match(block.lines[n].text)
            ):
                n += 1
            finish_note()
            name, country, website = " ".join(ln.text for ln in block.lines[:n]), "", ""
            scope = category = ""
            heading, buf, last = [], [], None
            block = Block(block.column, block.lines[n:]) if n < len(block.lines) else None
            if block is None:
                continue
        for line in block.lines:
            if not block.indented(line):  # category heading (or its wrapped continuation)
                finish_note()
                buf = []
                m = HEADING.match(line.text)
                if m:
                    scope, heading = m.group(1).strip(), [m.group(2)]
                else:
                    heading.append(line.text)
                category = re.sub(r"\s+\d{1,3}$", "", re.sub(r"\s+", " ", " ".join(heading)).strip(" ,"))
                continue
            if current is not None:
                if not CODE.search(line.text) and (
                    boilerplate[line.text] >= NOTE_MIN_REPEATS or line.text[:1].islower()
                ):
                    note.append(line.text)  # a lowercase start is the wrapped tail of a note, never a product
                    continue
                finish_note()  # the first non-boilerplate line starts the next product
            if not buf and boilerplate[line.text] >= NOTE_MIN_REPEATS and not CODE.search(line.text):
                continue  # a stray note line whose product we did not catch: never the start of a product name
            buf.append(line.text)
            joined = " ".join(buf)
            m = CODE.search(joined)
            if not m:
                continue
            tail = joined[m.end():]
            marked = bool(tail.strip()) and bool(MARKER.match(tail))
            product = {
                "omri_id": f"{m.group(1)}-{m.group(2)}", "name": clean_name(joined[:m.start()]), "scope": scope,
                "category": category, "company": name, "company_country": country,
                "company_website": website, "restricted": marked, "restriction_note": "",
            }
            rows.append(product)
            last = None if marked else product
            buf = [] if marked or not tail.strip() else [tail.strip()]
            if marked:
                current, note = product, []
        after_heading = not block.indented(block.lines[-1])
        if current is not None:  # block ended while collecting a note
            if note:
                finish_note()
            else:
                awaiting = True
    finish_note()
    return rows


def parse(pdf_path: Path) -> list[dict]:
    blocks = read_blocks(pdf_path)
    boilerplate = Counter(ln.text for b in blocks for ln in b.lines if b.indented(ln))
    rows: list[dict] = []
    for company in group_by_company(blocks):
        rows.extend(parse_company(company, boilerplate))
    return rows


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: python -m src.scripts.parse_omri_pdf /path/to/OMRI.pdf")
    rows = parse(Path(sys.argv[1]))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"{len(rows)} products -> {OUT}")


if __name__ == "__main__":
    main()
