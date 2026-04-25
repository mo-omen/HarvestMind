import json
from typing import Annotated, Any

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AgriPivot API"
    app_env: str = "development"
    app_port: int = 8000
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]
    database_url: str | None = None
    mem0_api_key: str | None = None
    ilmu_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ILMU_API_KEY", "ZAI_API_KEY"),
    )
    ilmu_base_url: str = Field(
        default="https://api.ilmu.ai/v1",
        validation_alias=AliasChoices("ILMU_BASE_URL", "ZAI_BASE_URL"),
    )
    glm_model: str = Field(
        default="ilmu-glm-5.1",
        validation_alias=AliasChoices("ILMU_MODEL", "GLM_MODEL"),
    )
    redis_url: str = "redis://localhost:6379/0"
    demo_farmer_id: str = "demo-farmer"
    firecrawl_api_key: str | None = None
    firecrawl_api_url: str = "http://localhost:3002/v1"
    fama_price_urls: Annotated[list[str], NoDecode] = [
        "https://www.fama.gov.my/web/pub/harga-pasaran-terkini",
        "https://www.fama.gov.my/harga-pasaran-terkini",
    ]

    model_config = SettingsConfigDict(
        extra="ignore",
        env_file=(".env", "../.env"),
        env_ignore_empty=True,
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if value is None:
            return ["http://localhost:5173"]

        raw = str(value).strip()
        if not raw:
            return ["http://localhost:5173"]

        if raw.startswith("["):
            parsed = json.loads(raw)
            if not isinstance(parsed, list):
                raise ValueError("CORS_ORIGINS must decode to a list of origins")
            return [str(item).strip() for item in parsed if str(item).strip()]

        return [item.strip() for item in raw.split(",") if item.strip()]

    @field_validator("glm_model", mode="before")
    @classmethod
    def _normalize_glm_model(cls, value: Any) -> str:
        raw = str(value).strip() if value is not None else ""
        if not raw:
            return "ilmu-glm-5.1"
        if raw.casefold() in {"glm-5.1", "glm5.1", "glm_5_1"}:
            return "ilmu-glm-5.1"
        return raw

    @field_validator("fama_price_urls", mode="before")
    @classmethod
    def _parse_fama_price_urls(cls, value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        raw = str(value or "").strip()
        if not raw:
            return []
        if raw.startswith("["):
            parsed = json.loads(raw)
            if not isinstance(parsed, list):
                raise ValueError("FAMA_PRICE_URLS must decode to a list of URLs")
            return [str(item).strip() for item in parsed if str(item).strip()]
        return [item.strip() for item in raw.split(",") if item.strip()]

    @property
    def zai_api_key(self) -> str | None:
        return self.ilmu_api_key

    @property
    def zai_base_url(self) -> str:
        return self.ilmu_base_url


settings = Settings()
