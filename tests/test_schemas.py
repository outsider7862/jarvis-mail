import pytest
from pydantic import ValidationError

from app.schemas.analysis import EmailAnalysisExtraction, LeadDetail


def _base_kwargs(**overrides):
    kwargs = dict(
        category="other",
        priority="low",
        summary="A routine email.",
        action_required=None,
        deadline=None,
        is_business_lead=False,
        is_invoice=False,
        is_meeting=False,
        is_customer_support=False,
        is_newsletter=False,
        is_spam=False,
        is_phishing=False,
        confidence=0.5,
    )
    kwargs.update(overrides)
    return kwargs


def test_valid_non_lead_analysis():
    analysis = EmailAnalysisExtraction(**_base_kwargs(category="invoice", is_invoice=True))
    assert analysis.category == "invoice"
    assert analysis.lead_detail is None


def test_valid_lead_analysis_with_nested_detail():
    analysis = EmailAnalysisExtraction(
        **_base_kwargs(
            category="business_lead",
            is_business_lead=True,
            lead_detail=LeadDetail(client_name="Ahmed Raza", service_requested="Website redesign"),
        )
    )
    assert analysis.lead_detail.client_name == "Ahmed Raza"


def test_invalid_category_rejected():
    with pytest.raises(ValidationError):
        EmailAnalysisExtraction(**_base_kwargs(category="not_a_real_category"))


def test_confidence_out_of_range_rejected():
    with pytest.raises(ValidationError):
        EmailAnalysisExtraction(**_base_kwargs(confidence=1.5))


def test_invalid_priority_rejected():
    with pytest.raises(ValidationError):
        EmailAnalysisExtraction(**_base_kwargs(priority="super-urgent"))
