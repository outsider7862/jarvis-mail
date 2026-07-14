from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import accounts, analyses, leads, webhooks
from app.core.config import settings

app = FastAPI(title="Jarvis Mail API")

# Allow the dashboard (and later the deployed frontend) to call the API.
# In production, replace "*" with your actual frontend domain.
origins = ["*"] if settings.app_env == "development" else [
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


@app.get("/health")
async def health():
    return {"status": "ok"}
