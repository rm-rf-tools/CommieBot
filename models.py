
from typing import Optional
from sqlmodel import SQLModel, Field
from sqlalchemy import UniqueConstraint, Index

class ServerConfig(SQLModel, table=True):
    __tablename__ = "server_configs"
    guild_id: str = Field(primary_key=True)
    role_id: Optional[str] = None
    crp_role_id: Optional[str] = None
    ticket_role_id: Optional[str] = None
    forms_role_id: Optional[str] = None  
    autorole_id: Optional[str] = None
    autorole_enabled: bool = Field(default=False)
    focus_role_id: Optional[str] = None 

class Aid(SQLModel, table=True):
    __tablename__ = "aids"
    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: Optional[str] = None
    channel_id: Optional[str] = None
    user_id: Optional[str] = None
    amount_requested: Optional[float] = None
    amount_received: float = Field(default=0.0)
    reason: Optional[str] = None
    status: str = Field(default="active")
    created_at: Optional[int] = None
    next_reminder_at: Optional[int] = None

class Committee(SQLModel, table=True):
    __tablename__ = "committees"
    __table_args__ = (UniqueConstraint("guild_id", "name", name="uq_committee_guild_name"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None

class CommitteeAssignment(SQLModel, table=True):
    __tablename__ = "committee_assignments"
    __table_args__ = (
        UniqueConstraint("guild_id", "user_id", "committee_id", "role_type", name="uq_committee_assignment"),
        Index("idx_unique_global_roles", "guild_id", "user_id", "role_type", unique=True, sqlite_where="committee_id IS NULL"),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: Optional[str] = None
    user_id: Optional[str] = None
    committee_id: Optional[int] = Field(default=None, foreign_key="committees.id", ondelete="CASCADE")
    role_type: Optional[str] = None

class QuoteTemplate(SQLModel, table=True):
    __tablename__ = "quote_templates"
    name: str = Field(primary_key=True)
    file_path: Optional[str] = None

class Ticket(SQLModel, table=True):
    __tablename__ = "tickets"
    ticket_id: str = Field(primary_key=True)
    guild_id: Optional[str] = None
    user_id: Optional[str] = None
    channel_id: Optional[str] = None
    status: str = Field(default="active")
    created_at: Optional[int] = None

class TicketStaffRole(SQLModel, table=True):
    __tablename__ = "ticket_staff_roles"
    guild_id: str = Field(primary_key=True)
    role_id: str = Field(primary_key=True)

class Profile(SQLModel, table=True):
    __tablename__ = "profiles"
    guild_id: str = Field(primary_key=True)
    user_id: str = Field(primary_key=True)
    bio: Optional[str] = None

class Skill(SQLModel, table=True):
    __tablename__ = "skills"
    __table_args__ = (UniqueConstraint("guild_id", "name", name="uq_skill_guild_name"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    is_wanted: int = Field(default=0)

class ProfileSkill(SQLModel, table=True):
    __tablename__ = "profile_skills"
    guild_id: str = Field(primary_key=True)
    user_id: str = Field(primary_key=True)
    skill_id: int = Field(primary_key=True, foreign_key="skills.id", ondelete="CASCADE")
    proficiency: Optional[str] = None

class Event(SQLModel, table=True):
    __tablename__ = "events"
    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: str
    name: str
    created_at: int

class EventAttendance(SQLModel, table=True):
    __tablename__ = "event_attendance"
    __table_args__ = (UniqueConstraint("event_id", "user_id", name="uq_event_user_attendance"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    event_id: int = Field(foreign_key="events.id", ondelete="CASCADE")
    user_id: str
    check_in_time: int

# Forms
class Applicant(SQLModel, table=True):
    __tablename__ = "applicants"
    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: str
    user_id: str
    username: str
    preferred_name: str
    pronouns: str

class FormTemplate(SQLModel, table=True):
    __tablename__ = "form_templates"
    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: str
    name: str
    description: str
    created_at: int
    cooldown_days: int = Field(default=0)

class FormQuestion(SQLModel, table=True):
    __tablename__ = "form_questions"
    id: Optional[int] = Field(default=None, primary_key=True)
    form_id: int = Field(foreign_key="form_templates.id", ondelete="CASCADE")
    question_text: str
    question_type: str  # 'text', 'single', 'multiple'
    options: Optional[str] = None  # Comma-separated options for multiple choice

class FormSubmission(SQLModel, table=True):
    __tablename__ = "form_submissions"
    id: Optional[int] = Field(default=None, primary_key=True)
    form_id: int = Field(foreign_key="form_templates.id", ondelete="CASCADE")
    applicant_id: int = Field(foreign_key="applicants.id", ondelete="CASCADE")
    submitted_at: int
    status: str = Field(default="pending")  # 'pending', 'confirmed', 'denied'

class FormAnswer(SQLModel, table=True):
    __tablename__ = "form_answers"
    id: Optional[int] = Field(default=None, primary_key=True)
    submission_id: int = Field(foreign_key="form_submissions.id", ondelete="CASCADE")
    question_id: int = Field(foreign_key="form_questions.id", ondelete="CASCADE")
    answer_text: str

class ModWatch(SQLModel, table=True):
    __tablename__ = "mod_watch"
    guild_id: str = Field(primary_key=True)
    user_id: str = Field(primary_key=True)
    reason: str

class ModLogConfig(SQLModel, table=True):
    __tablename__ = "modlog_configs"
    guild_id: str = Field(primary_key=True)
    log_channel_id: Optional[str] = None
    log_channel_create: bool = Field(default=False)
    log_channel_delete: bool = Field(default=False)
    log_channel_rename: bool = Field(default=False)
    tracked_words: Optional[str] = None

class FocusChannel(SQLModel, table=True):
    __tablename__ = "focus_channels"
    guild_id: str = Field(primary_key=True)
    channel_id: str = Field(primary_key=True)

class GrokReply(SQLModel, table=True):
    __tablename__ = "grok_replies"
    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: str
    reply_text: str
    category: str = Field(default="general")
    keywords: Optional[str] = Field(default=None)  
    intent: Optional[str] = Field(default="neutral") 

class UserLastSeen(SQLModel, table=True):
    __tablename__ = "user_last_seen"
    guild_id: str = Field(primary_key=True)
    user_id: str = Field(primary_key=True)
    last_seen_at: int

class Movie(SQLModel, table=True):
    __tablename__ = "movies"
    id: int = Field(primary_key=True)
    title: str = Field(index=True)
    vote_average: float = Field(default=0.0)
    vote_count: int = Field(default=0)
    status: Optional[str] = None
    release_date: Optional[str] = None
    revenue: int = Field(default=0)
    runtime: int = Field(default=0)
    adult: Optional[str] = None
    backdrop_path: Optional[str] = None
    budget: int = Field(default=0)
    homepage: Optional[str] = None
    imdb_id: Optional[str] = None
    original_language: Optional[str] = None
    original_title: Optional[str] = None
    overview: Optional[str] = None
    popularity: float = Field(default=0.0)
    poster_path: Optional[str] = None
    tagline: Optional[str] = None
    genres: Optional[str] = None
    production_companies: Optional[str] = None
    production_countries: Optional[str] = None
    spoken_languages: Optional[str] = None
    keywords: Optional[str] = None

# --- React Roles Models ---
class RolePlan(SQLModel, table=True):
    __tablename__ = "role_plans"
    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: str
    name: str

class RolePlanItem(SQLModel, table=True):
    __tablename__ = "role_plan_items"
    id: Optional[int] = Field(default=None, primary_key=True)
    plan_id: int = Field(foreign_key="role_plans.id", ondelete="CASCADE")
    role_name: str
    role_color: Optional[int] = Field(default=0)
    emoji: Optional[str] = None
    category: Optional[str] = Field(default="General")
    description: Optional[str] = None