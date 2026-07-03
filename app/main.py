from fastapi import FastAPI

from app.api.routes import analyses, leads, webhooks

app = FastAPI(title="Jarvis Mail API")

app.include_router(webhooks.router)
app.include_router(leads.router)
app.include_router(analyses.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
