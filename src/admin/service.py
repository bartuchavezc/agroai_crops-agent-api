"""
Read-only business metrics for the platform admin panel (agroai_admin).

Plain SQL aggregates over every account: counts, sizes, durations and distributions. Nothing here returns
message text, photos, memories or API keys — only metadata (who, when, how much).

Definitions:
- Activity: a user is active on a day when they send a chat message, upload a photo (a report) or log a
  field event by hand. DAU/WAU/MAU count distinct active users in the last 1/7/30 days.
- Session: a user's chat messages (theirs and the agent's replies) with less than SESSION_GAP_MINUTES
  between consecutive ones. Its length runs from the first message to the last reply.
- Photo: every uploaded photo creates a report (`POST /upload/image`); field layout photos are stored on
  the field instead. Satellite images are generated, not uploaded, and are not counted.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.farm.models import ACTIVE_CROP_CYCLE_STATUSES

from .schemas import (
    AccountsStats,
    AdminAccountRow,
    AdminUserRow,
    AgentStats,
    AlertsStats,
    Bucket,
    ConversationsStats,
    DailyPoint,
    FarmStats,
    ModuleAdoption,
    Overview,
    PhotosStats,
    ProfilesStats,
    SessionsStats,
    SystemStats,
    Timeseries,
    ToolUsage,
    UsersStats,
)

SESSION_GAP_MINUTES = 30

# (user_id, at) for every user-initiated action.
ACTIVITY_SQL = """
    SELECT c.user_id AS user_id, m.created_at AS at
      FROM conversation_messages m JOIN conversations c ON c.id = m.conversation_id
     WHERE m.role = 'user'
    UNION ALL
    SELECT r.created_by, r.created_at FROM reports r WHERE r.created_by IS NOT NULL AND r.image_identifier IS NOT NULL
    UNION ALL
    SELECT e.author_user_id, e.created_at FROM field_events e
     WHERE e.author_user_id IS NOT NULL AND e.source = 'user'
"""

# One row per usage session: (user_id, started_at, ended_at, turns). Bind :since and :gap.
SESSIONS_SQL = """
    WITH msgs AS (
        SELECT c.user_id, m.created_at, (m.role = 'user')::int AS is_user
          FROM conversation_messages m JOIN conversations c ON c.id = m.conversation_id
         WHERE m.created_at >= :since
    ), marked AS (
        SELECT user_id, created_at, is_user,
               CASE WHEN created_at - lag(created_at) OVER w <= make_interval(mins => :gap) THEN 0 ELSE 1 END AS starts
          FROM msgs
        WINDOW w AS (PARTITION BY user_id ORDER BY created_at)
    ), numbered AS (
        SELECT user_id, created_at, is_user,
               sum(starts) OVER (PARTITION BY user_id ORDER BY created_at ROWS UNBOUNDED PRECEDING) AS sid
          FROM marked
    )
    SELECT user_id, min(created_at) AS started_at, max(created_at) AS ended_at, sum(is_user) AS turns
      FROM numbered
     GROUP BY user_id, sid
"""

PHOTO_REPORTS = "reports.image_identifier IS NOT NULL"

AREA_BUCKETS = [  # (label, upper bound in m², exclusive)
    ("< 10 m²", 10),
    ("10–50 m²", 50),
    ("50–200 m²", 200),
    ("200–1.000 m²", 1000),
    ("1.000–10.000 m²", 10000),
    ("≥ 1 ha", None),
]

SESSION_BUCKETS = [  # (label, upper bound in minutes, exclusive)
    ("< 1 min", 1),
    ("1–5 min", 5),
    ("5–15 min", 15),
    ("15–30 min", 30),
    ("30–60 min", 60),
    ("≥ 60 min", None),
]


def _buckets(rows) -> list[Bucket]:
    return [Bucket(key=str(k) if k is not None else "sin dato", count=int(c)) for k, c in rows]


def _f(value, digits: int = 2) -> float:
    return round(float(value), digits) if value is not None else 0.0


def _opt(value, digits: int = 2):
    return round(float(value), digits) if value is not None else None


def _range_case(expr: str, buckets) -> str:
    """SQL CASE mapping `expr` to the label of its bucket, in bucket order."""
    parts = [f"WHEN {expr} < {upper} THEN '{label}'" for label, upper in buckets if upper is not None]
    return f"CASE {' '.join(parts)} ELSE '{buckets[-1][0]}' END"


class AdminMetricsService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], timezone_name: str):
        self.session_factory = session_factory
        self.timezone = timezone_name

    async def overview(self, days: int) -> Overview:
        now = datetime.now(timezone.utc)
        since = now - timedelta(days=days)
        params = {
            "since": since,
            "day_ago": now - timedelta(days=1),
            "week_ago": now - timedelta(days=7),
            "month_ago": now - timedelta(days=30),
            "gap": SESSION_GAP_MINUTES,
        }
        async with self.session_factory() as session:
            run = _Runner(session, params)
            return Overview(
                generated_at=now,
                window_days=days,
                since=since,
                users=await self._users(run),
                accounts=await self._accounts(run),
                profiles=await self._profiles(run),
                photos=await self._photos(run),
                conversations=await self._conversations(run),
                sessions=await self._sessions(run),
                agent=await self._agent(run),
                farm=await self._farm(run),
                alerts=await self._alerts(run),
                modules=await self._modules(run),
                system=await self._system(run),
            )

    # ---------- sections ----------

    async def _users(self, run: "_Runner") -> UsersStats:
        row = await run.one(
            """
            SELECT count(*),
                   count(*) FILTER (WHERE is_active),
                   count(*) FILTER (WHERE is_enrolled),
                   count(*) FILTER (WHERE created_at >= :since),
                   count(*) FILTER (WHERE EXISTS (
                       SELECT 1 FROM provider_credentials p WHERE p.user_id = users.id AND p.provider = 'gemini'))
              FROM users
            """
        )
        total, active, enrolled, new, byok = (int(v) for v in row)
        roles = await run.all("SELECT role, count(*) FROM users GROUP BY role ORDER BY count(*) DESC")
        activity = await run.one(
            f"""
            WITH a AS ({ACTIVITY_SQL})
            SELECT count(DISTINCT user_id) FILTER (WHERE at >= :day_ago),
                   count(DISTINCT user_id) FILTER (WHERE at >= :week_ago),
                   count(DISTINCT user_id) FILTER (WHERE at >= :month_ago),
                   count(DISTINCT user_id) FILTER (WHERE at >= :since)
              FROM a
            """
        )
        dau, wau, mau, active_window = (int(v) for v in activity)
        return UsersStats(
            total=total,
            active=active,
            inactive=total - active,
            enrolled=enrolled,
            pending_onboarding=total - enrolled,
            new_in_window=new,
            by_role=_buckets(roles),
            dau=dau,
            wau=wau,
            mau=mau,
            active_in_window=active_window,
            byok_configured=byok,
            byok_missing=total - byok,
        )

    async def _accounts(self, run: "_Runner") -> AccountsStats:
        row = await run.one(
            f"""
            WITH per AS (SELECT account_id, count(*) AS n FROM users GROUP BY account_id),
                 active AS (
                     SELECT DISTINCT u.account_id FROM ({ACTIVITY_SQL}) a JOIN users u ON u.id = a.user_id
                      WHERE a.at >= :since)
            SELECT (SELECT count(*) FROM accounts),
                   (SELECT count(*) FROM accounts WHERE created_at >= :since),
                   (SELECT avg(n) FROM per),
                   (SELECT count(*) FROM per WHERE n > 1),
                   (SELECT count(DISTINCT account_id) FROM fields WHERE deleted_at IS NULL),
                   (SELECT count(*) FROM active)
            """
        )
        return AccountsStats(
            total=int(row[0]),
            new_in_window=int(row[1]),
            avg_users_per_account=_f(row[2]),
            multi_user=int(row[3]),
            with_fields=int(row[4]),
            with_activity_in_window=int(row[5]),
        )

    async def _profiles(self, run: "_Runner") -> ProfilesStats:
        result = {}
        for column in ("profile", "experience", "goal", "risk", "philosophy"):
            result[column] = _buckets(
                await run.all(f"SELECT {column}, count(*) FROM user_profiles GROUP BY 1 ORDER BY 2 DESC")
            )
        return ProfilesStats(**result)

    async def _photos(self, run: "_Runner") -> PhotosStats:
        row = await run.one(
            f"""
            SELECT count(*), count(*) FILTER (WHERE created_at >= :since), count(DISTINCT created_by)
              FROM reports WHERE {PHOTO_REPORTS}
            """
        )
        uploads, in_window, users = (int(v) for v in row)
        layout = await run.scalar(
            "SELECT coalesce(sum(jsonb_array_length(layout_photos)), 0) FROM fields WHERE deleted_at IS NULL"
        )
        in_chat = await run.scalar(
            "SELECT count(DISTINCT image_identifier) FROM conversation_messages "
            "WHERE role = 'user' AND image_identifier IS NOT NULL"
        )
        by_type = await run.all(
            f"SELECT report_type, count(*) FROM reports WHERE {PHOTO_REPORTS} GROUP BY 1 ORDER BY 2 DESC"
        )
        by_status = await run.all(
            f"SELECT status, count(*) FROM reports WHERE {PHOTO_REPORTS} GROUP BY 1 ORDER BY 2 DESC"
        )
        statuses = dict((k, int(c)) for k, c in by_status)
        done, failed = statuses.get("ANALYSIS_COMPLETED", 0), statuses.get("ANALYSIS_FAILED", 0)
        return PhotosStats(
            total=uploads + int(layout),
            in_window=in_window,
            uploads=uploads,
            layout_photos=int(layout),
            used_in_chat=int(in_chat),
            users_with_photos=users,
            by_type=_buckets(by_type),
            by_status=_buckets(by_status),
            diagnosis_success_rate=round(done / (done + failed), 4) if done + failed else None,
        )

    async def _conversations(self, run: "_Runner") -> ConversationsStats:
        row = await run.one(
            """
            WITH per AS (
                SELECT c.id, count(m.id) AS n
                  FROM conversations c LEFT JOIN conversation_messages m ON m.conversation_id = c.id
                 GROUP BY c.id)
            SELECT (SELECT count(*) FROM conversations),
                   (SELECT count(*) FROM conversations WHERE created_at >= :since),
                   (SELECT count(*) FROM conversations WHERE archived_at IS NOT NULL),
                   (SELECT count(*) FROM conversation_messages),
                   (SELECT count(*) FROM conversation_messages WHERE role = 'user'),
                   (SELECT count(*) FROM conversation_messages WHERE role = 'user' AND created_at >= :since),
                   (SELECT avg(n) FROM per WHERE n > 0),
                   (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY n) FROM per WHERE n > 0),
                   (SELECT count(DISTINCT user_id) FROM conversations)
            """
        )
        return ConversationsStats(
            total=int(row[0]),
            in_window=int(row[1]),
            archived=int(row[2]),
            messages_total=int(row[3]),
            user_messages=int(row[4]),
            user_messages_in_window=int(row[5]),
            avg_messages_per_conversation=_f(row[6]),
            median_messages_per_conversation=_f(row[7]),
            users_with_conversations=int(row[8]),
        )

    async def _sessions(self, run: "_Runner") -> SessionsStats:
        minutes = "extract(epoch FROM ended_at - started_at) / 60.0"
        row = await run.one(
            f"""
            WITH s AS ({SESSIONS_SQL}), d AS (SELECT user_id, turns, {minutes} AS minutes FROM s)
            SELECT count(*), count(DISTINCT user_id), avg(minutes),
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY minutes),
                   percentile_cont(0.9) WITHIN GROUP (ORDER BY minutes),
                   avg(turns), percentile_cont(0.5) WITHIN GROUP (ORDER BY turns)
              FROM d
            """
        )
        counts = dict(
            await run.all(
                f"""
                WITH s AS ({SESSIONS_SQL})
                SELECT {_range_case(minutes, SESSION_BUCKETS)}, count(*) FROM s GROUP BY 1
                """
            )
        )
        total, users = int(row[0]), int(row[1])
        return SessionsStats(
            gap_minutes=SESSION_GAP_MINUTES,
            total=total,
            users=users,
            avg_minutes=_f(row[2], 1),
            median_minutes=_f(row[3], 1),
            p90_minutes=_f(row[4], 1),
            avg_turns=_f(row[5], 1),
            median_turns=_f(row[6], 1),
            sessions_per_user=round(total / users, 2) if users else 0.0,
            length_buckets=[Bucket(key=label, count=int(counts.get(label, 0))) for label, _ in SESSION_BUCKETS],
        )

    async def _agent(self, run: "_Runner") -> AgentStats:
        tools = await run.all(
            """
            SELECT t->>'name', count(*), count(*) FILTER (WHERE (t->>'ok')::boolean IS FALSE)
              FROM conversation_messages m, jsonb_array_elements(m.tool_calls) t
             WHERE m.role = 'assistant' AND m.created_at >= :since
             GROUP BY 1 ORDER BY 2 DESC
            """
        )
        turns = await run.one(
            """
            SELECT count(*) FILTER (WHERE jsonb_array_length(tool_calls) > 0),
                   count(*) FILTER (WHERE tool_calls @> '[{"name": "web_search"}]')
              FROM conversation_messages WHERE role = 'assistant' AND created_at >= :since
            """
        )
        memories = await run.one(
            "SELECT count(*) FILTER (WHERE superseded_at IS NULL), count(*) FILTER (WHERE created_at >= :since) "
            "FROM agent_memories"
        )
        usage = [ToolUsage(name=n or "?", calls=int(c), failed=int(f)) for n, c, f in tools]
        return AgentStats(
            tool_calls=sum(t.calls for t in usage),
            tool_calls_failed=sum(t.failed for t in usage),
            turns_with_tools=int(turns[0]),
            turns_with_search=int(turns[1]),
            tools=usage,
            memories_active=int(memories[0]),
            memories_in_window=int(memories[1]),
        )

    async def _farm(self, run: "_Runner") -> FarmStats:
        live = "deleted_at IS NULL"
        fields = await run.one(
            f"""
            SELECT count(*),
                   count(*) FILTER (WHERE created_at >= :since),
                   count(area_m2) FILTER (WHERE area_m2 > 0),
                   coalesce(sum(area_m2) FILTER (WHERE area_m2 > 0), 0),
                   avg(area_m2) FILTER (WHERE area_m2 > 0),
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY area_m2) FILTER (WHERE area_m2 > 0),
                   min(area_m2) FILTER (WHERE area_m2 > 0),
                   max(area_m2) FILTER (WHERE area_m2 > 0),
                   count(*) FILTER (WHERE latitude IS NOT NULL AND longitude IS NOT NULL),
                   count(*) FILTER (WHERE boundary IS NOT NULL AND jsonb_typeof(boundary) = 'array'
                                      AND jsonb_array_length(boundary) >= 3),
                   count(*) FILTER (WHERE jsonb_array_length(layout_objects) > 0),
                   count(DISTINCT account_id)
              FROM fields WHERE {live}
            """
        )
        area_counts = dict(
            await run.all(
                f"SELECT {_range_case('area_m2', AREA_BUCKETS)}, count(*) FROM fields "
                f"WHERE {live} AND area_m2 > 0 GROUP BY 1"
            )
        )
        cycles = await run.one(
            f"""
            SELECT count(*), count(*) FILTER (WHERE status = ANY(:active)), count(*) FILTER (WHERE created_at >= :since)
              FROM crop_cycles WHERE {live}
            """,
            active=list(ACTIVE_CROP_CYCLE_STATUSES),
        )
        by_status = await run.all(f"SELECT status, count(*) FROM crop_cycles WHERE {live} GROUP BY 1 ORDER BY 2 DESC")
        top_crops = await run.all(
            f"""
            SELECT initcap(lower(cm.name)), count(*)
              FROM crop_cycles cc JOIN crop_masters cm ON cm.id = cc.crop_master_id
             WHERE cc.{live} GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 15
            """
        )
        events = await run.one("SELECT count(*), count(*) FILTER (WHERE created_at >= :since) FROM field_events")
        by_type = await run.all("SELECT type, count(*) FROM field_events GROUP BY 1 ORDER BY 2 DESC")
        by_source = await run.all("SELECT source, count(*) FROM field_events GROUP BY 1 ORDER BY 2 DESC")
        accounts_with_fields = int(fields[11])
        return FarmStats(
            fields_total=int(fields[0]),
            fields_in_window=int(fields[1]),
            fields_with_area=int(fields[2]),
            area_total_m2=_f(fields[3]),
            area_avg_m2=_opt(fields[4]),
            area_median_m2=_opt(fields[5]),
            area_min_m2=_opt(fields[6]),
            area_max_m2=_opt(fields[7]),
            area_buckets=[Bucket(key=label, count=int(area_counts.get(label, 0))) for label, _ in AREA_BUCKETS],
            fields_with_location=int(fields[8]),
            fields_with_boundary=int(fields[9]),
            fields_with_layout=int(fields[10]),
            avg_fields_per_account=round(int(fields[0]) / accounts_with_fields, 2) if accounts_with_fields else 0.0,
            crop_cycles_total=int(cycles[0]),
            crop_cycles_active=int(cycles[1]),
            crop_cycles_in_window=int(cycles[2]),
            cycles_by_status=_buckets(by_status),
            top_crops=_buckets(top_crops),
            events_total=int(events[0]),
            events_in_window=int(events[1]),
            events_by_type=_buckets(by_type),
            events_by_source=_buckets(by_source),
        )

    async def _alerts(self, run: "_Runner") -> AlertsStats:
        row = await run.one(
            "SELECT count(*), count(*) FILTER (WHERE created_at >= :since), "
            "count(*) FILTER (WHERE acknowledged_at IS NULL) FROM alerts"
        )
        return AlertsStats(
            total=int(row[0]),
            in_window=int(row[1]),
            unacknowledged=int(row[2]),
            by_source=_buckets(await run.all("SELECT source, count(*) FROM alerts GROUP BY 1 ORDER BY 2 DESC")),
            by_severity=_buckets(await run.all("SELECT severity, count(*) FROM alerts GROUP BY 1 ORDER BY 2 DESC")),
        )

    async def _modules(self, run: "_Runner") -> list[ModuleAdoption]:
        tables = [
            ("Chat con el agente", "conversations", None),
            ("Diagnóstico por foto", "reports", PHOTO_REPORTS),
            ("Campos", "fields", "deleted_at IS NULL"),
            ("Ciclos de cultivo", "crop_cycles", "deleted_at IS NULL"),
            ("Registro de eventos", "field_events", "source = 'user'"),
            ("Memoria del agente", "agent_memories", "superseded_at IS NULL"),
            ("Inventario de semillas", "seed_lots", "deleted_at IS NULL"),
            ("Lista de compras", "shopping_list_items", "deleted_at IS NULL"),
            ("Presupuesto", "budget_entries", "deleted_at IS NULL"),
            ("Hoja de ruta", "roadmap_items", "deleted_at IS NULL"),
            ("Satélite (NDVI)", "zone_satellite_readings", None),
        ]
        result = []
        for label, table, where in tables:
            row = await run.one(
                f"SELECT count(DISTINCT account_id), count(*) FROM {table}" + (f" WHERE {where}" if where else "")
            )
            result.append(ModuleAdoption(module=label, accounts=int(row[0]), records=int(row[1])))
        return result

    async def _system(self, run: "_Runner") -> SystemStats:
        row = await run.one(
            """
            SELECT (SELECT max(issued_at) FROM weather_forecasts),
                   (SELECT max(time) FROM weather_observations),
                   (SELECT max(created_at) FROM reports),
                   (SELECT max(created_at) FROM conversation_messages)
            """
        )
        return SystemStats(
            database="ok",
            last_forecast_issued_at=row[0],
            last_weather_observation_at=row[1],
            last_report_at=row[2],
            last_message_at=row[3],
        )

    # ---------- time series and listings ----------

    async def timeseries(self, days: int) -> Timeseries:
        now = datetime.now(timezone.utc)
        since = now - timedelta(days=days + 1)
        last_day = now.astimezone(ZoneInfo(self.timezone)).date()
        params = {
            "since": since,
            "gap": SESSION_GAP_MINUTES,
            "tz": self.timezone,
            "first_day": last_day - timedelta(days=days - 1),
            "last_day": last_day,
        }

        def local_day(column: str) -> str:
            return f"({column} AT TIME ZONE :tz)::date"

        async with self.session_factory() as session:
            run = _Runner(session, params)
            rows = await run.all(
                f"""
                WITH days AS (
                    SELECT generate_series(CAST(:first_day AS date), CAST(:last_day AS date), interval '1 day')::date
                           AS day
                ),
                signups AS (SELECT {local_day('created_at')} AS day, count(*) AS n FROM users
                             WHERE created_at >= :since GROUP BY 1),
                active AS (SELECT {local_day('at')} AS day, count(DISTINCT user_id) AS n FROM ({ACTIVITY_SQL}) a
                            WHERE at >= :since GROUP BY 1),
                msgs AS (SELECT {local_day('created_at')} AS day, count(*) AS n FROM conversation_messages
                          WHERE role = 'user' AND created_at >= :since GROUP BY 1),
                convs AS (SELECT {local_day('created_at')} AS day, count(*) AS n FROM conversations
                           WHERE created_at >= :since GROUP BY 1),
                sess AS (SELECT {local_day('started_at')} AS day, count(*) AS n FROM ({SESSIONS_SQL}) s GROUP BY 1),
                photos AS (SELECT {local_day('created_at')} AS day, count(*) AS n FROM reports
                            WHERE {PHOTO_REPORTS} AND created_at >= :since GROUP BY 1),
                events AS (SELECT {local_day('created_at')} AS day, count(*) AS n FROM field_events
                            WHERE created_at >= :since GROUP BY 1)
                SELECT d.day, coalesce(signups.n, 0), coalesce(active.n, 0), coalesce(msgs.n, 0),
                       coalesce(convs.n, 0), coalesce(sess.n, 0), coalesce(photos.n, 0), coalesce(events.n, 0)
                  FROM days d
                  LEFT JOIN signups USING (day) LEFT JOIN active USING (day) LEFT JOIN msgs USING (day)
                  LEFT JOIN convs USING (day) LEFT JOIN sess USING (day) LEFT JOIN photos USING (day)
                  LEFT JOIN events USING (day)
                 ORDER BY d.day
                """
            )
        keys = ("signups", "active_users", "user_messages", "conversations", "sessions", "photos", "events")
        points = [DailyPoint(day=r[0], **{k: int(v) for k, v in zip(keys, r[1:], strict=True)}) for r in rows]
        return Timeseries(days=days, timezone=self.timezone, points=points)

    async def users(self) -> list[AdminUserRow]:
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        async with self.session_factory() as session:
            run = _Runner(session, {"since": epoch, "gap": SESSION_GAP_MINUTES})
            rows = await run.mappings(
                f"""
                WITH last_active AS (SELECT user_id, max(at) AS at FROM ({ACTIVITY_SQL}) a GROUP BY user_id),
                     convs AS (SELECT user_id, count(*) AS n FROM conversations GROUP BY user_id),
                     msgs AS (SELECT c.user_id, count(*) AS n FROM conversation_messages m
                                JOIN conversations c ON c.id = m.conversation_id
                               WHERE m.role = 'user' GROUP BY c.user_id),
                     sess AS (SELECT user_id, count(*) AS n,
                                     sum(extract(epoch FROM ended_at - started_at)) / 60.0 AS minutes
                                FROM ({SESSIONS_SQL}) s GROUP BY user_id),
                     photos AS (SELECT created_by AS user_id, count(*) AS n FROM reports
                                 WHERE {PHOTO_REPORTS} AND created_by IS NOT NULL GROUP BY 1),
                     events AS (SELECT author_user_id AS user_id, count(*) AS n FROM field_events
                                 WHERE author_user_id IS NOT NULL GROUP BY 1)
                SELECT u.id, u.email, u.first_name, u.last_name, u.account_id, a.name AS account_name, u.role,
                       u.is_active, u.is_enrolled, p.profile, u.created_at,
                       EXISTS (SELECT 1 FROM provider_credentials pc
                                WHERE pc.user_id = u.id AND pc.provider = 'gemini') AS byok_configured,
                       la.at AS last_active_at,
                       coalesce(convs.n, 0) AS conversations, coalesce(msgs.n, 0) AS user_messages,
                       coalesce(sess.n, 0) AS sessions, coalesce(sess.minutes, 0) AS chat_minutes,
                       coalesce(photos.n, 0) AS photos, coalesce(events.n, 0) AS events
                  FROM users u
                  JOIN accounts a ON a.id = u.account_id
                  LEFT JOIN user_profiles p ON p.user_id = u.id
                  LEFT JOIN last_active la ON la.user_id = u.id
                  LEFT JOIN convs ON convs.user_id = u.id
                  LEFT JOIN msgs ON msgs.user_id = u.id
                  LEFT JOIN sess ON sess.user_id = u.id
                  LEFT JOIN photos ON photos.user_id = u.id
                  LEFT JOIN events ON events.user_id = u.id
                 ORDER BY la.at DESC NULLS LAST, u.created_at DESC
                """
            )
        return [AdminUserRow(**{**r, "chat_minutes": _f(r["chat_minutes"], 1)}) for r in rows]

    async def accounts(self) -> list[AdminAccountRow]:
        async with self.session_factory() as session:
            run = _Runner(session, {})
            rows = await run.mappings(
                f"""
                WITH members AS (
                         SELECT account_id, count(*) AS users, count(*) FILTER (WHERE is_active) AS active_users,
                                count(*) FILTER (WHERE role = 'owner') AS owners,
                                count(*) FILTER (WHERE role = 'tecnico') AS tecnicos,
                                count(*) FILTER (WHERE role = 'staff') AS staff
                           FROM users GROUP BY account_id),
                     f AS (SELECT account_id, count(*) AS n,
                                  coalesce(sum(area_m2) FILTER (WHERE area_m2 > 0), 0) AS area
                             FROM fields WHERE deleted_at IS NULL GROUP BY account_id),
                     cc AS (SELECT account_id, count(*) AS n, count(*) FILTER (WHERE status = ANY(:active)) AS active
                              FROM crop_cycles WHERE deleted_at IS NULL GROUP BY account_id),
                     photos AS (SELECT account_id, count(*) AS n FROM reports WHERE {PHOTO_REPORTS} GROUP BY 1),
                     convs AS (SELECT account_id, count(*) AS n FROM conversations GROUP BY 1),
                     msgs AS (SELECT c.account_id, count(*) AS n FROM conversation_messages m
                                JOIN conversations c ON c.id = m.conversation_id WHERE m.role = 'user' GROUP BY 1),
                     events AS (SELECT account_id, count(*) AS n FROM field_events GROUP BY 1),
                     last_active AS (SELECT u.account_id, max(a.at) AS at FROM ({ACTIVITY_SQL}) a
                                       JOIN users u ON u.id = a.user_id GROUP BY 1)
                SELECT a.id, a.name, a.created_at,
                       coalesce(members.users, 0) AS users, coalesce(members.active_users, 0) AS active_users,
                       coalesce(members.owners, 0) AS owners, coalesce(members.tecnicos, 0) AS tecnicos,
                       coalesce(members.staff, 0) AS staff,
                       coalesce(f.n, 0) AS fields, coalesce(f.area, 0) AS area_m2,
                       coalesce(cc.n, 0) AS crop_cycles, coalesce(cc.active, 0) AS crop_cycles_active,
                       coalesce(photos.n, 0) AS photos, coalesce(convs.n, 0) AS conversations,
                       coalesce(msgs.n, 0) AS user_messages, coalesce(events.n, 0) AS events,
                       last_active.at AS last_active_at
                  FROM accounts a
                  LEFT JOIN members ON members.account_id = a.id
                  LEFT JOIN f ON f.account_id = a.id
                  LEFT JOIN cc ON cc.account_id = a.id
                  LEFT JOIN photos ON photos.account_id = a.id
                  LEFT JOIN convs ON convs.account_id = a.id
                  LEFT JOIN msgs ON msgs.account_id = a.id
                  LEFT JOIN events ON events.account_id = a.id
                  LEFT JOIN last_active ON last_active.account_id = a.id
                 ORDER BY last_active.at DESC NULLS LAST, a.created_at DESC
                """,
                active=list(ACTIVE_CROP_CYCLE_STATUSES),
            )
        return [AdminAccountRow(**{**r, "area_m2": _f(r["area_m2"])}) for r in rows]


class _Runner:
    """Executes SQL in one session with the shared bind parameters (window start, now, session gap...)."""

    def __init__(self, session: AsyncSession, params: dict):
        self.session = session
        self.params = params

    async def _execute(self, sql: str, extra: dict):
        return await self.session.execute(text(sql), {**self.params, **extra})

    async def one(self, sql: str, **extra):
        return (await self._execute(sql, extra)).one()

    async def all(self, sql: str, **extra):
        return (await self._execute(sql, extra)).all()

    async def scalar(self, sql: str, **extra):
        return (await self._execute(sql, extra)).scalar()

    async def mappings(self, sql: str, **extra):
        return [dict(r) for r in (await self._execute(sql, extra)).mappings().all()]
