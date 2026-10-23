"""The cuaderno de aplicaciones of a field and period, as CSV (one row per product) or a printable PDF: what an
inspection or a buyer asks to see. Only records in force; a corrected record shows its last version and says how
many it had, a voided one is listed as such."""
import csv
import io
from datetime import date, datetime
from typing import Optional
from zoneinfo import ZoneInfo

from fpdf import FPDF

from .schemas import ApplicationRead
from .service import product_line

CSV_COLUMNS = (
    "registro", "version", "estado", "fecha", "hora", "campo", "lotes", "motivo", "producto", "nro_registro",
    "verificado_en_registro", "principios_activos", "dosis", "unidad_dosis", "cantidad_usada", "unidad_cantidad",
    "carencia_dias", "reingreso_horas", "cosecha_desde", "metodo", "equipo", "superficie_m2", "caldo_l", "aplico",
    "indico", "receta", "temperatura_c", "humedad_pct", "viento_ms", "notas", "motivo_correccion",
)


def _local(value: Optional[datetime], tz: Optional[ZoneInfo]) -> Optional[datetime]:
    if value is None:
        return None
    return value.astimezone(tz) if tz else value


def _num(value) -> str:
    return "" if value is None else f"{value:g}"


def to_csv(apps: list[ApplicationRead], field_names: dict, people: dict, tz: Optional[ZoneInfo]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(CSV_COLUMNS)
    for app in apps:
        when = _local(app.applied_at, tz)
        weather = app.weather or {}
        base = [
            str(app.record_id), app.version, app.status, when.date().isoformat() if when else "",
            when.strftime("%H:%M") if when else "", field_names.get(app.field_id, ""), " + ".join(app.lot_labels),
            app.target or "",
        ]
        tail = [
            app.harvest_release_date.isoformat() if app.harvest_release_date else "", app.method or "",
            app.equipment or "", _num(app.area_m2), _num(app.water_volume_l),
            app.operator_name or people.get(app.operator_user_id, ""), app.prescribed_by or "",
            app.prescription_number or "", _num(weather.get("temperature_c")), _num(weather.get("humidity_pct")),
            _num(weather.get("wind_speed_ms")), app.notes or "", app.correction_reason or "",
        ]
        for p in app.products or [None]:
            product = ["", "", "", "", "", "", "", "", "", ""] if p is None else [
                p.name, p.registry_number or "", "si" if p.registry_verified else "no", p.active_ingredients or "",
                _num(p.dose), p.dose_unit or "", _num(p.total_quantity), p.total_unit or "",
                _num(p.preharvest_interval_days), _num(p.reentry_interval_hours),
            ]
            writer.writerow([*base, *product, *tail])
    return out.getvalue()


def _latin1(text: str) -> str:
    """The PDF's core fonts are Latin-1: Spanish text fits; anything else is replaced, never dropped silently."""
    return (text or "").replace("—", "-").replace("–", "-").replace("“", '"').replace("”", '"').encode(
        "latin-1", "replace"
    ).decode("latin-1")


def to_pdf(
    apps: list[ApplicationRead], field_names: dict, people: dict, tz: Optional[ZoneInfo], title: str,
    period: tuple[Optional[date], Optional[date]],
) -> bytes:
    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 8, _latin1(title), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=9)
    since, until = period
    span = f"{since:%d/%m/%Y}" if since else "inicio"
    span += f" al {until:%d/%m/%Y}" if until else " a hoy"
    pdf.cell(0, 5, _latin1(f"Período: {span} · {len(apps)} registros · generado {datetime.now(tz):%d/%m/%Y %H:%M}"),
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    headers = ("Fecha", "Campo / lotes", "Motivo", "Producto · registro · activos", "Dosis / cantidad",
               "Carencia", "Aplicó / indicó", "Clima")
    widths = (22, 42, 32, 70, 32, 22, 32, 25)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(235, 235, 235)
    for header, width in zip(headers, widths, strict=True):
        pdf.cell(width, 6, _latin1(header), border=1, fill=True)
    pdf.ln()
    pdf.set_font("Helvetica", size=7.5)
    for app in apps:
        when = _local(app.applied_at, tz)
        weather = app.weather or {}
        clima = " · ".join(x for x in (
            f"{weather['temperature_c']:.0f}°C" if weather.get("temperature_c") is not None else "",
            f"HR {weather['humidity_pct']:.0f}%" if weather.get("humidity_pct") is not None else "",
            f"{weather['wind_speed_ms']:.1f} m/s" if weather.get("wind_speed_ms") is not None else "",
        ) if x)
        products = "\n".join(
            f"{p.name}" + (f" · Reg. {p.registry_number}" if p.registry_number else "")
            + ("" if p.registry_verified else " · NO VERIFICADO")
            + (f"\n  {p.active_ingredients}" if p.active_ingredients else "")
            for p in app.products
        )
        doses = "\n".join(product_line(p)[len(p.name):].strip() or "-" for p in app.products)
        carencia = "\n".join(
            f"{p.preharvest_interval_days} d" if p.preharvest_interval_days is not None else "sin dato"
            for p in app.products
        )
        if app.harvest_release_date:
            carencia += f"\ncosecha desde {app.harvest_release_date:%d/%m}"
        status = "" if app.status == "confirmed" else " ANULADA"
        if app.version > 1:
            status += f" (v{app.version}: {app.correction_reason or ''})"
        cells = (
            (f"{when:%d/%m/%Y %H:%M}" if when else "-") + status,
            f"{field_names.get(app.field_id, '')}\n" + " + ".join(app.lot_labels),
            app.target or "-",
            products or "-",
            doses or "-",
            carencia or "-",
            (app.operator_name or people.get(app.operator_user_id, "-"))
            + (f"\nIndicó: {app.prescribed_by}" if app.prescribed_by else "")
            + (f"\nReceta {app.prescription_number}" if app.prescription_number else ""),
            clima or "-",
        )
        lines = max(len(pdf.multi_cell(w, 4, _latin1(c), dry_run=True, output="LINES")) for c, w in zip(
            cells, widths, strict=True
        ))
        height = 4 * lines + 1
        if pdf.get_y() + height > pdf.h - 12:
            pdf.add_page()
        y, x = pdf.get_y(), pdf.l_margin
        for cell, width in zip(cells, widths, strict=True):
            pdf.rect(x, y, width, height)
            pdf.set_xy(x, y + 0.5)
            pdf.multi_cell(width, 4, _latin1(cell), border=0)
            x += width
        pdf.set_xy(pdf.l_margin, y + height)
    pdf.ln(4)
    pdf.set_font("Helvetica", "I", 7)
    pdf.multi_cell(0, 4, _latin1(
        "Registro generado por AgroAI. Cada aplicación confirmada no se edita: las correcciones son versiones nuevas "
        "con su motivo. 'NO VERIFICADO': el producto no coincide con un registro oficial del país al cargarlo. La "
        "carencia sale de la etiqueta del producto. Clima: estimación del modelo meteorológico para ese punto y hora."
    ))
    return bytes(pdf.output())
