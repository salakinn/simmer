from datetime import datetime
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class Ingredient(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    quantity: str | None = None
    unit: str | None = None
    name: str | None = None
    group: str | None = None


class Step(BaseModel):
    text: str = Field(min_length=1, max_length=10000)


class RecipeData(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    source_type: str = "url"
    source_name: str | None = None
    source_url: str | None = None
    author: str | None = None
    servings: str | None = None
    prep_minutes: int | None = Field(default=None, ge=0)
    cook_minutes: int | None = Field(default=None, ge=0)
    total_minutes: int | None = Field(default=None, ge=0)
    image_url: str | None = None
    categories: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    ingredients: list[Ingredient] = Field(min_length=1)
    steps: list[Step] = Field(min_length=1)

    @field_validator("source_url", "image_url")
    @classmethod
    def web_url_only(cls, value):
        if value is not None and (urlsplit(value).scheme.lower() not in {"http", "https"} or not urlsplit(value).hostname):
            raise ValueError("Nur HTTP-/HTTPS-URLs sind erlaubt")
        return value

    @field_validator("title")
    @classmethod
    def nonblank_title(cls, value):
        if not value.strip():
            raise ValueError("Ein Rezeptname ist erforderlich")
        return value.strip()


class RecipeUpdate(RecipeData):
    pass


class RecipeOut(RecipeData):
    has_image: bool = False
    id: int
    version: int
    created_at: datetime | None = None
    updated_at: datetime | None = None
    model_config = ConfigDict(from_attributes=True)


class ImportRequest(BaseModel):
    url: HttpUrl


class ErrorResponse(BaseModel):
    error: str
    detail: str
