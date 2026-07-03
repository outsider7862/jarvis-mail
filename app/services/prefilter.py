"""
Runs BEFORE any OpenAI call, same as before — but much lighter touch than the
original LeadPilot version.

In LeadPilot, the only thing that mattered was lead detection, so it made sense to
aggressively drop newsletters/spam/noise before paying for an LLM call. In Jarvis
Mail, classifying newsletters and spam correctly IS part of the product (morning
brief counts them, search can filter by them) — dropping them here would just make
the dashboard wrong.

So this now only filters things that carry zero information value even as a
classified item: mail-system bounce/delivery-status notifications and duplicate
read-receipts. Everything else — including things that will end up classified as
newsletter/spam/other — goes to the LLM.
"""

import re

# Only true mail-system noise, not "unwanted" content — that distinction matters now.
SYSTEM_NOISE_SENDER_PATTERNS = [
    r"mailer-daemon@",
    r"postmaster@",
]

SYSTEM_NOISE_SUBJECT_KEYWORDS = [
    "delivery status notification",
    "undeliverable:",
    "read: ",  # Outlook read-receipt subject prefix
]


def is_system_noise(sender: str | None, subject: str | None, body_text: str | None) -> bool:
    sender = (sender or "").lower()
    subject = (subject or "").lower()

    for pattern in SYSTEM_NOISE_SENDER_PATTERNS:
        if re.search(pattern, sender):
            return True

    for keyword in SYSTEM_NOISE_SUBJECT_KEYWORDS:
        if subject.startswith(keyword):
            return True

    return False
