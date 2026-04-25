from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.advisor import router as advisor_router
from app.api.routes.analysis import router as analysis_router
from app.api.routes.feedback import router as feedback_router
from app.api.routes.health import router as health_router
from app.api.routes.intake import router as intake_router
from app.api.routes.market import router as market_router
from app.api.routes.ops import router as ops_router
from app.api.routes.profiles import router as profiles_router
from app.api.routes.recommendations import router as recommendations_router
from app.api.routes.signals import router as signals_router
from app.core.config import settings


app = FastAPI(title=settings.app_name, version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix="/api/v1")
app.include_router(profiles_router, prefix="/api/v1")
app.include_router(recommendations_router, prefix="/api/v1")
app.include_router(analysis_router, prefix="/api/v1")
app.include_router(intake_router, prefix="/api/v1")
app.include_router(feedback_router, prefix="/api/v1")
app.include_router(signals_router, prefix="/api/v1")
app.include_router(market_router, prefix="/api/v1")
app.include_router(ops_router, prefix="/api/v1")
app.include_router(advisor_router, prefix="/api/v1")


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "message": "AgriPivot backend online",
        "docs": "/docs",
    }
