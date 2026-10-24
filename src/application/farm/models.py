"""
Farm domain: fields (plots / garden beds), zones, crop catalog, crop lots and field events.
Everything hangs from an account; crop_masters with account_id NULL are the global catalog.
"""
import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from src.shared.database import Base
from src.shared.domain.base import utcnow

# A lot (lote) is one batch of a crop sown together: "T26/27 · Cantero 2 · Lote 2". seedbed = still in the almácigo.
LOT_STATUSES = ("planned", "seedbed", "planted", "growing", "harvesting", "harvested", "failed")
ACTIVE_LOT_STATUSES = ("planned", "seedbed", "planted", "growing", "harvesting")
GROWING_LOT_STATUSES = ("seedbed", "planted", "growing", "harvesting")  # in the ground: what a zone event reaches
# The bitácora: everything done or seen, on a zone (and so on every lot in it) or on specific lots. Products and
# doses are free text (notes / quantity / unit); the agent reads them.
EVENT_TYPES = (
    "irrigation",
    "fertilization",
    "pest_control",  # any phyto / organic treatment against pests or diseases
    "sowing",
    "transplant",
    "harvest",
    "inspection",  # a check-up: pest or disease seen, growth, state ("revisión")
    "observation",
    "soil_prep",
    "amendment",  # compost, substrate, lime... added to the soil
    "pruning",
    "weeding",
    "photo",
    "loss",  # plants or seeds lost (didn't germinate, pest, frost...): lowers a lot's live count, never its sown one
    "rain",  # rain measured at the field (source "system", from the weather data): what a skipped watering cites
)
# What happened to an entry: done, or deliberately skipped with a reason ("no regué: llovió 18 mm"). A skipped
# entry is a fact too — without it the log can't tell "not watered" from "nobody said".
EVENT_OUTCOMES = ("done", "skipped")
# A follow-up (seguimiento) is a problem being watched — "pulgón en tomate" — that groups the bitácora entries about
# it: detected, treated, better, resolved. It holds no history of its own: its timeline is those entries
# (field_events.followup_id), each with its evidence (photos, the analysis that saw it).
FOLLOWUP_KINDS = ("pest", "disease", "deficiency", "other")
FOLLOWUP_STATUSES = ("abierto", "resuelto", "descartado")
FOLLOWUP_SEVERITIES = ("low", "medium", "high", "critical")
LOSS_CAUSES = ("no_germination", "pest", "disease", "frost", "heat", "waterlogging", "drought", "animals", "other")
EVENT_SOURCES = ("user", "agent", "system")  # system: written by a job (rain from the weather data)
# A zone groups the crops of a field that are grown (and tracked/photographed) together: "Cantero 3".
ZONE_TYPES = ("cajon", "cantero", "invernadero", "hidroponia")
ZONE_TYPE_LABELS = {"cajon": "Cajón", "cantero": "Cantero", "invernadero": "Invernadero", "hidroponia": "Hidroponía"}


class Field(Base):
    __tablename__ = "fields"
    __table_args__ = (
        # Partial index: the name can be reused once the old field is soft-deleted.
        Index(
            "uq_fields_account_name_active",
            "account_id",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    city = Column(String(255))
    latitude = Column(Float)
    longitude = Column(Float)
    layout_view_bearing = Column(Float)  # compass bearing drawn upward on the plan; null = automatic
    boundary = Column(JSONB)  # list[[lat, lon], ...] — the field's own drawn boundary, not the ~500m zone
    description = Column(Text)
    soil_type = Column(String(100))
    area_m2 = Column(Float)
    length_m = Column(Float)
    width_m = Column(Float)
    layout_objects = Column(JSONB, nullable=False, default=list, server_default="[]")
    layout_photos = Column(JSONB, nullable=False, default=list, server_default="[]")
    soil_context = Column(JSONB)  # cached INTA soil lookup (src/application/soil_data); None until computed
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    deleted_at = Column(DateTime(timezone=True))


class FieldZone(Base):
    """A numbered growing unit inside a field (cajón, cantero, invernadero, hidroponía). Lots, events and
    tracking reports belong to one; the daily tracking photo is taken per zone. The number is the user's own and
    can be changed; renumbering several zones at once is checked as a whole by the service, not by an index."""
    __tablename__ = "field_zones"
    __table_args__ = (
        CheckConstraint(f"type IN {ZONE_TYPES}", name="zone_type_valid"),
        CheckConstraint("number >= 1", name="zone_number_positive"),
        Index("ix_field_zones_field_type_number", "field_id", "type", "number"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    field_id = Column(UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(String(20), nullable=False)
    number = Column(Integer, nullable=False)
    name = Column(String(255))  # optional nickname ("el de las aromáticas")
    notes = Column(Text)
    layout_object_id = Column(String(64))  # the drawn cantero on the field plan, if linked
    length_m = Column(Float)
    width_m = Column(Float)
    # The zone's own soil where it differs from the field's (substrate or compost added):
    # {nitrogen, potassium, carbon, ph, notes, updated_at}; missing keys fall back to the field's soil context.
    soil = Column(JSONB, nullable=False, default=dict, server_default="{}")
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    deleted_at = Column(DateTime(timezone=True))


class CropMaster(Base):
    __tablename__ = "crop_masters"
    __table_args__ = (
        Index("ix_crop_masters_account_name", "account_id", "name"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=True)
    name = Column(String(255), nullable=False)
    variety = Column(String(255))
    scientific_name = Column(String(255))
    family = Column(String(255))
    description = Column(Text)
    growth_period_days = Column(Integer)
    planting_season = Column(String(255))
    harvest_season = Column(String(255))
    kc_initial = Column(Float)
    kc_mid = Column(Float)
    kc_late = Column(Float)
    thousand_seed_weight_g = Column(Float)  # typical grams per 1000 seeds; seed lots fall back to it
    # Names by locale ({"es-MX": "Jitomate"}); `name`/`variety` stay the neutral value and the fallback.
    i18n = Column(JSONB, nullable=False, default=dict, server_default="{}")
    variety_i18n = Column(JSONB, nullable=False, default=dict, server_default="{}")
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class Lot(Base):
    """One batch of a crop sown together (lote). `season` ("26/27") and `number` are the user's own labels,
    free to set and to fix; a lot sown the same day in several zones lists them all in lot_zones."""
    __tablename__ = "lots"
    __table_args__ = (
        CheckConstraint(f"status IN {LOT_STATUSES}", name="status_valid"),
        CheckConstraint("number IS NULL OR number >= 1", name="number_positive"),
        Index("ix_lots_account_status", "account_id", "status"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    field_id = Column(UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False, index=True)
    crop_master_id = Column(UUID(as_uuid=True), ForeignKey("crop_masters.id", ondelete="RESTRICT"), nullable=False)
    season = Column(String(10))
    number = Column(Integer)
    planting_date = Column(Date)  # sown, or planted out for bought plantines
    transplant_date = Column(Date)
    expected_harvest_date = Column(Date)
    actual_harvest_date = Column(Date)
    quantity = Column(Float)
    unit = Column(String(30))  # plantas | semillas | gramos | m2 ...
    expected_yield_kg = Column(Float)
    expected_price = Column(Float)  # per kg, in the account's currency
    status = Column(String(20), nullable=False, default="planned")
    notes = Column(Text)
    plan_id = Column(UUID(as_uuid=True), ForeignKey("crop_plans.id", ondelete="SET NULL", use_alter=True), index=True)
    origin_lot_id = Column(UUID(as_uuid=True), ForeignKey("lots.id", ondelete="SET NULL"))  # its almácigo
    # A resowing: this lot replaces (part of) that one, whose losses are logged as `loss` events.
    replaces_lot_id = Column(UUID(as_uuid=True), ForeignKey("lots.id", ondelete="SET NULL"))
    # No harvest before this day: the longest withholding period (carencia) of the applications in force on it.
    harvest_blocked_until = Column(Date)
    plan_crop_id = Column(UUID(as_uuid=True), ForeignKey("plan_crops.id", ondelete="SET NULL"))  # planned by
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    deleted_at = Column(DateTime(timezone=True))


class LotZone(Base):
    """The zones a lot occupies (usually one; the first names it)."""
    __tablename__ = "lot_zones"

    lot_id = Column(UUID(as_uuid=True), ForeignKey("lots.id", ondelete="CASCADE"), primary_key=True)
    zone_id = Column(UUID(as_uuid=True), ForeignKey("field_zones.id", ondelete="CASCADE"), primary_key=True, index=True)
    position = Column(Integer, nullable=False, default=0)


class FieldEvent(Base):
    __tablename__ = "field_events"
    __table_args__ = (
        CheckConstraint(f"type IN {EVENT_TYPES}", name="type_valid"),
        CheckConstraint(f"source IN {EVENT_SOURCES}", name="source_valid"),
        CheckConstraint(f"outcome IN {EVENT_OUTCOMES}", name="outcome_valid"),
        Index("ix_field_events_account_occurred", "account_id", "occurred_at"),
        Index("ix_field_events_field_occurred", "field_id", "occurred_at"),
        Index("ix_field_events_zone_occurred", "zone_id", "occurred_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    field_id = Column(UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False)
    zone_id = Column(UUID(as_uuid=True), ForeignKey("field_zones.id", ondelete="SET NULL"))  # null: the whole field
    author_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    type = Column(String(30), nullable=False)
    occurred_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    quantity = Column(Float)
    unit = Column(String(30))
    notes = Column(Text)
    data = Column(JSONB, nullable=False, default=dict)
    image_identifier = Column(String(255))
    source = Column(String(10), nullable=False, default="user")
    outcome = Column(String(10), nullable=False, default="done", server_default="done")
    reason = Column(Text)  # why it was skipped; a loss's cause in words
    # The problem this entry is about (seen, treated, better...), and what backs it: [{kind, identifier, note}],
    # kind photo / report / audio / document — e.g. the photo and the analysis that saw the pest.
    followup_id = Column(UUID(as_uuid=True), ForeignKey("followups.id", ondelete="SET NULL"), index=True)
    evidence = Column(JSONB, nullable=False, default=list, server_default="[]")
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class FollowUp(Base):
    """A problem being watched in a zone or on some lots. Opened by the zone analysis (or a person) when something is
    seen, closed by a person — the analysis only proposes it. Its history is in the bitácora (FieldEvent.followup_id).
    """
    __tablename__ = "followups"
    __table_args__ = (
        CheckConstraint(f"kind IN {FOLLOWUP_KINDS}", name="kind_valid"),
        CheckConstraint(f"status IN {FOLLOWUP_STATUSES}", name="status_valid"),
        CheckConstraint(f"severity IN {FOLLOWUP_SEVERITIES}", name="severity_valid"),
        CheckConstraint(f"source IN {EVENT_SOURCES}", name="source_valid"),
        Index("ix_followups_field_status", "field_id", "status"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    field_id = Column(UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False)
    zone_id = Column(UUID(as_uuid=True), ForeignKey("field_zones.id", ondelete="SET NULL"))
    lot_ids = Column(JSONB, nullable=False, default=list, server_default="[]")  # the lots affected
    title = Column(String(255), nullable=False)  # "Pulgón en tomate"
    kind = Column(String(20), nullable=False, default="other")
    severity = Column(String(10), nullable=False, default="medium")
    photo_hint = Column(Text)  # what to photograph to follow it: "envés de las hojas de arriba"
    status = Column(String(12), nullable=False, default="abierto")
    source = Column(String(10), nullable=False, default="user")
    origin_report_id = Column(UUID(as_uuid=True), ForeignKey("reports.id", ondelete="SET NULL"))
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    closed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class EventLot(Base):
    """The lots an event reached, fixed when it was logged: a watering of Cantero 2 lists the lots growing there
    that day, so each lot's bitácora keeps it even after the lot is harvested or moved."""
    __tablename__ = "event_lots"

    event_id = Column(UUID(as_uuid=True), ForeignKey("field_events.id", ondelete="CASCADE"), primary_key=True)
    lot_id = Column(UUID(as_uuid=True), ForeignKey("lots.id", ondelete="CASCADE"), primary_key=True, index=True)
