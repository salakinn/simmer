from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text, create_engine, func, inspect, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from .config import settings


class Base(DeclarativeBase):
    pass


class RecipeRecord(Base):
    __tablename__ = "recipes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(30), default="url", nullable=False)
    source_name: Mapped[str | None] = mapped_column(String(300))
    source_url: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(String(300))
    servings: Mapped[str | None] = mapped_column(String(100))
    prep_minutes: Mapped[int | None] = mapped_column(Integer)
    cook_minutes: Mapped[int | None] = mapped_column(Integer)
    total_minutes: Mapped[int | None] = mapped_column(Integer)
    oven_temperature: Mapped[int | None] = mapped_column(Integer)
    bake_minutes: Mapped[int | None] = mapped_column(Integer)
    oven_mode: Mapped[str | None] = mapped_column(String(30))
    image_url: Mapped[str | None] = mapped_column(Text)
    image_data: Mapped[str | None] = mapped_column(Text)
    categories: Mapped[list] = mapped_column(JSON, default=list)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    ingredients: Mapped[list] = mapped_column(JSON, default=list)
    steps: Mapped[list] = mapped_column(JSON, default=list)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class TelegramUpdate(Base):
    __tablename__ = "telegram_updates"
    update_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(Integer, nullable=False)
    reply_text: Mapped[str] = mapped_column(Text, nullable=False)
    reply_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class TelegramPdfRequest(Base):
    __tablename__ = "telegram_pdf_requests"
    update_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recipe_id: Mapped[int] = mapped_column(Integer, nullable=False)


engine = create_engine(settings.database_url, connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {})
SessionLocal = sessionmaker(bind=engine)


def init_db():
    Base.metadata.create_all(engine)
    # Add nullable fields to existing installations without changing saved recipes.
    with engine.begin() as connection:
        columns = {column["name"] for column in inspect(connection).get_columns("recipes")}
        for name, sql_type in (("oven_temperature", "INTEGER"), ("bake_minutes", "INTEGER"), ("oven_mode", "VARCHAR(30)")):
            if name not in columns:
                connection.execute(text(f"ALTER TABLE recipes ADD COLUMN {name} {sql_type}"))


def get_db():
    with SessionLocal() as db:
        yield db
