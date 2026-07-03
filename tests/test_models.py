from sqlalchemy.orm import configure_mappers

from app.db.models import Base, ConnectedAccount, EmailAnalysis, Lead, RawEmail, User


def test_all_mappers_configure_without_error():
    """
    Catches broken relationships/FKs at test time instead of at first request —
    this is the kind of bug that's easy to introduce during a schema refactor
    (like the LeadPilot -> Jarvis Mail merge) and easy to miss without a test.
    """
    configure_mappers()


def test_expected_tables_exist():
    expected = {"users", "connected_accounts", "raw_emails", "email_analyses", "leads"}
    assert expected.issubset(set(Base.metadata.tables.keys()))


def test_lead_links_to_email_analysis_not_raw_email():
    """Regression test for the merge: Lead moved from raw_email_id to email_analysis_id."""
    lead_columns = {col.name for col in Lead.__table__.columns}
    assert "email_analysis_id" in lead_columns
    assert "raw_email_id" not in lead_columns
