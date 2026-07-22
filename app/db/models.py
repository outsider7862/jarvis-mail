import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Text, Boolean, Float, ForeignKey, JSON, DateTime, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    """A business owner using Jarvis Mail (not the same as their end clients)."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    supabase_user_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    business_name: Mapped[str | None] = mapped_column(String, nullable=True)
    profession: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # e.g. "agency", "contractor", "consultant" — drives dashboard framing later
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    connected_accounts: Mapped[list["ConnectedAccount"]] = relationship(back_populates="user")
    analyses: Mapped[list["EmailAnalysis"]] = relationship(back_populates="user")


class ConnectedAccount(Base):
    """One inbox (Gmail or Outlook) a user has connected via Composio."""

    __tablename__ = "connected_accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String, nullable=False)  # "gmail" | "outlook"
    email_address: Mapped[str] = mapped_column(String, nullable=False)
    composio_connected_account_id: Mapped[str] = mapped_column(String, nullable=False)
    composio_trigger_id: Mapped[str | None] = mapped_column(String, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped["User"] = relationship(back_populates="connected_accounts")
    raw_emails: Mapped[list["RawEmail"]] = relationship(back_populates="connected_account")


class RawEmail(Base):
    """
    Log of every inbound email event we received from Composio, before/after processing.
    Keeping this lets you re-run classification later with a better prompt without
    needing to re-fetch from Gmail/Outlook.
    """

    __tablename__ = "raw_emails"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    connected_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("connected_accounts.id"), nullable=False)
    composio_message_id: Mapped[str | None] = mapped_column(String, nullable=True)
    sender: Mapped[str | None] = mapped_column(String, nullable=True)
    subject: Mapped[str | None] = mapped_column(String, nullable=True)
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict)

    was_filtered: Mapped[bool] = mapped_column(Boolean, default=False)  # true if prefilter dropped it
    processed: Mapped[bool] = mapped_column(Boolean, default=False)  # true once classification ran
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    connected_account: Mapped["ConnectedAccount"] = relationship(back_populates="raw_emails")
    analysis: Mapped["EmailAnalysis | None"] = relationship(back_populates="raw_email", uselist=False)


class EmailAnalysis(Base):
    """
    The classification result for EVERY email that reaches the LLM step — this is
    the core Jarvis Mail record. category/priority/summary/action/deadline apply to
    everything; the is_* boolean flags let the dashboard and morning brief count
    things without re-parsing category strings.

    Category-specific extra detail (currently just business leads) lives in its own
    linked table (see Lead below) rather than as nullable columns here, so this
    table doesn't grow a wide, mostly-empty schema as more categories get detail
    fields later (e.g. invoice amount/due date, meeting time/attendees).
    """

    __tablename__ = "email_analyses"
    __table_args__ = (
        # Every list/filter query is scoped to user_id and ordered by created_at.
        Index("ix_email_analyses_user_created", "user_id", "created_at"),
        # Matches the pending-notifications query (user_id + should_notify + notified_at IS NULL).
        Index("ix_email_analyses_user_notify", "user_id", "should_notify", "notified_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    raw_email_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("raw_emails.id"), nullable=False, unique=True)

    category: Mapped[str] = mapped_column(String, nullable=False)
    priority: Mapped[str] = mapped_column(String, nullable=False)  # "low" | "medium" | "high" | "urgent"
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    action_required: Mapped[str | None] = mapped_column(Text, nullable=True)
    deadline: Mapped[str | None] = mapped_column(String, nullable=True)

    is_business_lead: Mapped[bool] = mapped_column(Boolean, default=False)
    is_invoice: Mapped[bool] = mapped_column(Boolean, default=False)
    is_meeting: Mapped[bool] = mapped_column(Boolean, default=False)
    is_customer_support: Mapped[bool] = mapped_column(Boolean, default=False)
    is_newsletter: Mapped[bool] = mapped_column(Boolean, default=False)
    is_spam: Mapped[bool] = mapped_column(Boolean, default=False)
    is_phishing: Mapped[bool] = mapped_column(Boolean, default=False)
    is_order: Mapped[bool] = mapped_column(Boolean, default=False)
    is_otp: Mapped[bool] = mapped_column(Boolean, default=False)
    is_security_alert: Mapped[bool] = mapped_column(Boolean, default=False)

    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    confidence_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)

    # "new" -> shown as unread in dashboard; "read"; "actioned"; "dismissed"
    status: Mapped[str] = mapped_column(String, default="new")

    should_notify: Mapped[bool] = mapped_column(Boolean, default=False)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped["User"] = relationship(back_populates="analyses")
    raw_email: Mapped["RawEmail"] = relationship(back_populates="analysis")
    lead: Mapped["Lead | None"] = relationship(back_populates="analysis", uselist=False)


class Lead(Base):
    """
    Extended detail for emails classified as a business lead. Always starts as
    'pending' — the dashboard/app is where a human confirms or rejects it. Do not
    wire anything downstream to a lead that hasn't been confirmed.
    """

    __tablename__ = "leads"
    __table_args__ = (
        Index("ix_leads_user_created", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    email_analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("email_analyses.id"), nullable=False, unique=True
    )

    client_name: Mapped[str | None] = mapped_column(String, nullable=True)
    client_company: Mapped[str | None] = mapped_column(String, nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String, nullable=True)
    service_requested: Mapped[str | None] = mapped_column(Text, nullable=True)
    budget_mentioned: Mapped[str | None] = mapped_column(String, nullable=True)

    status: Mapped[str] = mapped_column(String, default="pending")  # "pending" | "confirmed" | "rejected"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped["User"] = relationship()
    analysis: Mapped["EmailAnalysis"] = relationship(back_populates="lead")


class ReplyFeedback(Base):
    """
    The before/after of a JARVIS draft: what it wrote vs. what the user actually
    kept. This is the learning signal — recent rows get fed back into the draft
    prompt as style examples. The sent email itself is never stored, only the
    draft diff.
    """

    __tablename__ = "reply_feedback"
    __table_args__ = (
        # _get_user_style_context reads the newest rows for one user.
        Index("ix_reply_feedback_user_created", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    analysis_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("email_analyses.id"), nullable=False)
    original_draft: Mapped[str] = mapped_column(Text, nullable=False)
    edited_draft: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped["User"] = relationship()


class UserProfile(Base):
    """
    Personalization captured during onboarding — feeds the classifier's system
    prompt for better summaries (and later, reply drafts). onboarding_complete
    doubles as the "has seen the privacy notice + finished setup" gate the
    dashboard checks before letting a user in.
    """

    __tablename__ = "user_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, unique=True)
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    work_type: Mapped[str | None] = mapped_column(String, nullable=True)       # e.g. "agency", "freelancer", "contractor"
    email_use: Mapped[str | None] = mapped_column(String, nullable=True)       # e.g. "client communication", "sales"
    preferred_tone: Mapped[str | None] = mapped_column(String, nullable=True)  # "formal", "friendly", "concise"
    custom_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    onboarding_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user: Mapped["User"] = relationship()
