"""
Platform admin metrics: aggregates and metadata only — never message content, photos or API keys.
"""
from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class Bucket(BaseModel):
    key: str
    count: int


class UsersStats(BaseModel):
    total: int
    active: int
    inactive: int
    enrolled: int
    pending_onboarding: int
    new_in_window: int
    by_role: list[Bucket]
    dau: int
    wau: int
    mau: int
    active_in_window: int
    byok_configured: int
    byok_missing: int


class AccountsStats(BaseModel):
    total: int
    new_in_window: int
    avg_users_per_account: float
    multi_user: int
    with_fields: int
    with_activity_in_window: int


class ProfilesStats(BaseModel):
    profile: list[Bucket]
    experience: list[Bucket]
    goal: list[Bucket]
    risk: list[Bucket]
    philosophy: list[Bucket]


class PhotosStats(BaseModel):
    total: int
    in_window: int
    uploads: int
    layout_photos: int
    used_in_chat: int
    users_with_photos: int
    by_type: list[Bucket]
    by_status: list[Bucket]
    diagnosis_success_rate: Optional[float]


class ConversationsStats(BaseModel):
    total: int
    in_window: int
    archived: int
    messages_total: int
    user_messages: int
    user_messages_in_window: int
    avg_messages_per_conversation: float
    median_messages_per_conversation: float
    users_with_conversations: int


class SessionsStats(BaseModel):
    """Usage sessions: a user's chat messages separated by less than `gap_minutes` belong to one session."""
    gap_minutes: int
    total: int
    users: int
    avg_minutes: float
    median_minutes: float
    p90_minutes: float
    avg_turns: float
    median_turns: float
    sessions_per_user: float
    length_buckets: list[Bucket]


class ToolUsage(BaseModel):
    name: str
    calls: int
    failed: int


class AgentStats(BaseModel):
    tool_calls: int
    tool_calls_failed: int
    turns_with_tools: int
    turns_with_search: int
    tools: list[ToolUsage]
    memories_active: int
    memories_in_window: int


class FarmStats(BaseModel):
    fields_total: int
    fields_in_window: int
    fields_with_area: int
    area_total_m2: float
    area_avg_m2: Optional[float]
    area_median_m2: Optional[float]
    area_min_m2: Optional[float]
    area_max_m2: Optional[float]
    area_buckets: list[Bucket]
    fields_with_location: int
    fields_with_boundary: int
    fields_with_layout: int
    avg_fields_per_account: float
    crop_cycles_total: int
    crop_cycles_active: int
    crop_cycles_in_window: int
    cycles_by_status: list[Bucket]
    top_crops: list[Bucket]
    events_total: int
    events_in_window: int
    events_by_type: list[Bucket]
    events_by_source: list[Bucket]


class AlertsStats(BaseModel):
    total: int
    in_window: int
    unacknowledged: int
    by_source: list[Bucket]
    by_severity: list[Bucket]


class ModuleAdoption(BaseModel):
    """How many accounts use each module (at least one live record)."""
    module: str
    accounts: int
    records: int


class SystemStats(BaseModel):
    database: str
    last_forecast_issued_at: Optional[datetime]
    last_weather_observation_at: Optional[datetime]
    last_report_at: Optional[datetime]
    last_message_at: Optional[datetime]


class Overview(BaseModel):
    generated_at: datetime
    window_days: int
    since: datetime
    users: UsersStats
    accounts: AccountsStats
    profiles: ProfilesStats
    photos: PhotosStats
    conversations: ConversationsStats
    sessions: SessionsStats
    agent: AgentStats
    farm: FarmStats
    alerts: AlertsStats
    modules: list[ModuleAdoption]
    system: SystemStats


class DailyPoint(BaseModel):
    day: date
    signups: int
    active_users: int
    user_messages: int
    conversations: int
    sessions: int
    photos: int
    events: int


class Timeseries(BaseModel):
    days: int
    timezone: str
    points: list[DailyPoint]


class AdminUserRow(BaseModel):
    id: UUID
    email: str
    first_name: Optional[str]
    last_name: Optional[str]
    account_id: UUID
    account_name: str
    role: str
    is_active: bool
    is_enrolled: bool
    profile: Optional[str]
    byok_configured: bool
    created_at: datetime
    last_active_at: Optional[datetime]
    conversations: int
    user_messages: int
    sessions: int
    chat_minutes: float
    photos: int
    events: int


class AdminAccountRow(BaseModel):
    id: UUID
    name: str
    created_at: datetime
    users: int
    active_users: int
    owners: int
    tecnicos: int
    staff: int
    fields: int
    area_m2: float
    crop_cycles: int
    crop_cycles_active: int
    photos: int
    conversations: int
    user_messages: int
    events: int
    last_active_at: Optional[datetime]
