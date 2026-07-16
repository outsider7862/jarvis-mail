from unittest.mock import AsyncMock, patch

import pytest

from app.schemas.analysis import EmailAnalysisExtraction
from app.services.extraction import analyze_email, compute_should_notify


@pytest.mark.asyncio
async def test_analyze_email_calls_responses_parse_with_correct_shape():
    fake_result = EmailAnalysisExtraction(
        category="business_lead",
        priority="high",
        summary="Client asking for a quote.",
        action_required="Reply with pricing",
        deadline=None,
        is_business_lead=True,
        is_invoice=False,
        is_meeting=False,
        is_customer_support=False,
        is_newsletter=False,
        is_spam=False,
        is_phishing=False,
        confidence=0.9,
    )

    mock_response = AsyncMock()
    mock_response.output_parsed = fake_result

    # analyze_email builds its own client (`async with AsyncOpenAI(...) as client`),
    # so the module-level `client` is never touched — patch the class at the point
    # of instantiation instead, or the mock is silently bypassed and the test
    # makes a real OpenAI call.
    mock_client = AsyncMock()
    mock_client.responses.parse = AsyncMock(return_value=mock_response)

    with patch("app.services.extraction.AsyncOpenAI") as mock_openai_cls:
        mock_openai_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_openai_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await analyze_email(
            subject="Quote request", body_text="Can you quote a logo design?", sender="client@example.com"
        )

    assert result.category == "business_lead"
    mocked = mock_client.responses.parse
    mocked.assert_awaited_once()
    call_kwargs = mocked.call_args.kwargs
    assert call_kwargs["text_format"] is EmailAnalysisExtraction
    assert "Quote request" in call_kwargs["input"][1]["content"]


def test_compute_should_notify_true_for_high_priority():
    extraction = EmailAnalysisExtraction(
        category="other", priority="high", summary="x", is_business_lead=False, is_invoice=False,
        is_meeting=False, is_customer_support=False, is_newsletter=False, is_spam=False,
        is_phishing=False, confidence=0.5,
    )
    assert compute_should_notify(extraction) is True


def test_compute_should_notify_false_for_routine_newsletter():
    extraction = EmailAnalysisExtraction(
        category="newsletter", priority="low", summary="x", is_business_lead=False, is_invoice=False,
        is_meeting=False, is_customer_support=False, is_newsletter=True, is_spam=False,
        is_phishing=False, confidence=0.9,
    )
    assert compute_should_notify(extraction) is False
