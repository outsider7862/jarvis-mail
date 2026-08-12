from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.routes import accounts, analyses, calendar, compose, leads, profile, reply, webhooks
from app.core.config import settings
from app.core.rate_limit import limiter

_is_dev = settings.app_env == "development"

# The interactive docs publish the full API schema (every route, param, and
# response shape) to anyone who asks — useful in dev, free recon in production.
app = FastAPI(
    title="Jarvis Mail API",
    docs_url="/docs" if _is_dev else None,
    redoc_url="/redoc" if _is_dev else None,
    openapi_url="/openapi.json" if _is_dev else None,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Allow the dashboard (and later the deployed frontend) to call the API.
# In production, replace "*" with your actual frontend domain.
origins = ["*"] if _is_dev else [
    settings.frontend_url,
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhooks.router)
app.include_router(leads.router)
app.include_router(analyses.router)
app.include_router(accounts.router)
app.include_router(profile.router)
app.include_router(reply.router)
app.include_router(compose.router)
app.include_router(calendar.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
