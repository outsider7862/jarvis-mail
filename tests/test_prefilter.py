from app.services.prefilter import is_system_noise


def test_mailer_daemon_is_filtered():
    assert is_system_noise("MAILER-DAEMON@gmail.com", "Delivery Status Notification (Failure)", "") is True


def test_postmaster_is_filtered():
    assert is_system_noise("postmaster@company.com", "Undeliverable: Your message", "") is True


def test_outlook_read_receipt_is_filtered():
    assert is_system_noise("[email protected]", "Read: Project update", "") is True


def test_real_client_inquiry_is_not_filtered():
    assert (
        is_system_noise(
            "[email protected]",
            "Question about your web design services",
            "Hi, I'd like a quote for a new site.",
        )
        is False
    )


def test_newsletter_is_not_filtered():
    """
    Deliberate design decision: unlike LeadPilot's old aggressive prefilter,
    newsletters must still reach the LLM so they can be classified and counted
    correctly in the morning brief / search.
    """
    assert (
        is_system_noise(
            "[email protected]",
            "Your weekly digest is here",
            "Unsubscribe from this list at any time.",
        )
        is False
    )
