from typing import Literal

from pydantic import BaseModel, Field

Category = Literal[
    "business_lead",
    "invoice",
    "meeting",
    "customer_support",
    "newsletter",
    "spam",
    "phishing",
    "personal",
    "order",
    "otp",
    "security_alert",
    "other",
]

Priority = Literal["low", "medium", "high", "urgent"]


class DecisionAssistance(BaseModel):
    """Decision support for a single email — reduces the user's choices, doesn't make them."""

    what_sender_wants: str = Field(
        description="One sentence: what is the sender asking for or trying to achieve?"
    )
    available_options: list[str] = Field(
        description="2-4 concrete options the recipient could take. Short labels only.",
        max_length=4,
    )
    recommendation: str = Field(
        description="What JARVIS recommends doing. One sentence."
    )
    reasoning: str = Field(
        description="Why JARVIS recommends that option. 1-2 sentences max."
    )
    risks: list[str] | None = Field(
        default=None,
        description="Any risks or trade-offs to consider. Max 2 items. Null if none.",
    )


class LeadDetail(BaseModel):
    """Only populated when category == 'business_lead'. Leave fields null rather than guessing."""

    client_name: str | None = Field(default=None, description="The sender's name, if identifiable.")
    client_company: str | None = Field(default=None, description="The sender's company name, if mentioned.")
    contact_email: str | None = Field(default=None, description="Best email address to reach this contact.")
    service_requested: str | None = Field(
        default=None, description="Short plain-language description of what they're asking for."
    )
    budget_mentioned: str | None = Field(
        default=None, description="Any budget figure or range mentioned, verbatim. Null if none given."
    )


class EmailAnalysisExtraction(BaseModel):
    """
    Full classification contract for a single email, covering every Jarvis Mail
    category. This is the schema OpenAI is constrained to fill in — extend
    cautiously, every new field is another thing that can be extracted wrong.
    """

    category: Category = Field(
        description="The single best-fit category for this email. Use 'other' if "
        "nothing else applies — do not force a fit."
    )
    priority: Priority = Field(description="Your best read of how urgently the recipient should deal with this.")
    summary: str = Field(description="One or two sentence plain-language summary of the email.")
    action_required: str | None = Field(
        default=None, description="What the recipient needs to do, if anything. Null if purely informational."
    )
    deadline: str | None = Field(
        default=None, description="Any deadline, meeting time, or due date mentioned, verbatim. Null if none."
    )

    is_business_lead: bool = Field(
        description="True only for inbound inquiries, referrals, or requests to hire the business "
        "for a service. False for existing-client admin chatter, internal mail, etc."
    )
    is_invoice: bool = Field(description="True if this is a bill, invoice, or payment request.")
    is_meeting: bool = Field(description="True if this proposes, confirms, or discusses a meeting/call.")
    is_customer_support: bool = Field(description="True if an existing client is reporting an issue or asking for help.")
    is_newsletter: bool = Field(description="True for mailing-list content, digests, or promotional sends.")
    is_spam: bool = Field(description="True for unsolicited, irrelevant, or low-quality bulk email.")
    is_phishing: bool = Field(
        description="True if this shows signs of a phishing/social-engineering attempt (spoofed sender, "
        "urgent credential/payment requests, suspicious links, mismatched reply-to, etc.)."
    )
    is_order: bool = Field(
        default=False,
        description="True for order confirmations, shipping notifications, delivery updates, tracking "
        "emails, and purchase receipts from any service.",
    )
    is_otp: bool = Field(
        default=False,
        description="True for emails containing one-time passwords, verification codes, login codes, "
        "or any time-sensitive authentication codes.",
    )
    is_security_alert: bool = Field(
        default=False,
        description="True for legitimate security notifications — new device logins, password change "
        "confirmations, account activity alerts from known services. IMPORTANT: distinguish from "
        "phishing. Security alerts come from known services the user likely uses and do NOT ask for "
        "credentials or contain suspicious links. Phishing pretends to be security alerts but requests "
        "action. When in doubt, prefer is_phishing over is_security_alert.",
    )

    confidence: float = Field(ge=0.0, le=1.0, description="Your overall confidence in this classification, 0 to 1.")
    confidence_explanation: str | None = Field(
        default=None,
        description="One sentence explaining why this confidence score was assigned. "
        "Example: 'High confidence because the email explicitly requests a service quote "
        "with a named budget and deadline.' or 'Medium confidence because the email could "
        "be either a lead or a support request.' Leave null only if confidence is above "
        "0.95 and the classification is unambiguous.",
    )

    lead_detail: LeadDetail | None = Field(
        default=None, description="Populate only when is_business_lead is true. Otherwise null."
    )
