"""SQLite storage (SQLAlchemy 2). One file, WAL mode, safe for the server's worker threads."""
import time
import uuid

from sqlalchemy import JSON, Float, ForeignKey, Integer, String, Text, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .config import DATA


def new_id(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


class Base(DeclarativeBase):
    type_annotation_map = {dict: JSON, list: JSON}


class Model(Base):
    """A local GGUF model (one quant; multi-part files are listed together)."""
    __tablename__ = "models"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    repo: Mapped[str] = mapped_column(String, default="")
    name: Mapped[str] = mapped_column(String)
    quant: Mapped[str] = mapped_column(String, default="")
    files: Mapped[list] = mapped_column(JSON, default=list)        # relative paths inside the model dir
    local_dir: Mapped[str] = mapped_column(String, default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String, default="ready")   # queued | downloading | paused | ready | failed
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)          # parsed GGUF summary
    source: Mapped[str] = mapped_column(String, default="hf")       # hf | imported
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class Provider(Base):
    __tablename__ = "providers"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    vendor: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    base_url: Mapped[str] = mapped_column(String)
    api_style: Mapped[str] = mapped_column(String)                  # openai-chat | openai-responses | anthropic
    has_key: Mapped[bool] = mapped_column(default=False)
    budget_usd: Mapped[float] = mapped_column(Float, default=5.0)
    spent_usd: Mapped[float] = mapped_column(Float, default=0.0)
    models_cache: Mapped[list] = mapped_column(JSON, default=list)
    last_check: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class Profile(Base):
    __tablename__ = "profiles"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)                       # local | cloud | endpoint
    model_id: Mapped[str | None] = mapped_column(ForeignKey("models.id", ondelete="SET NULL"), nullable=True)
    provider_id: Mapped[str | None] = mapped_column(ForeignKey("providers.id", ondelete="SET NULL"), nullable=True)
    remote_model: Mapped[str] = mapped_column(String, default="")   # vendor model id for cloud/endpoint
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    pricing: Mapped[dict] = mapped_column(JSON, default=dict)       # USD per 1M tokens: input, cached, output
    notes: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    fit: Mapped[dict] = mapped_column(JSON, default=dict)           # last memory check
    smoke: Mapped[dict] = mapped_column(JSON, default=dict)         # last quick test
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time)


class HarnessBuild(Base):
    __tablename__ = "harness_builds"
    harness_id: Mapped[str] = mapped_column(String, primary_key=True)
    image: Mapped[str] = mapped_column(String, default="")
    version: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="missing")  # missing | building | ready | failed
    built_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    smoke: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")


class CustomHarness(Base):
    __tablename__ = "custom_harnesses"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    manifest: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class Suite(Base):
    __tablename__ = "suites"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text, default="")
    benchmark_ids: Mapped[list] = mapped_column(JSON, default=list)
    builtin: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class Plan(Base):
    __tablename__ = "plans"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    profile_ids: Mapped[list] = mapped_column(JSON)
    harness_ids: Mapped[list] = mapped_column(JSON)
    benchmark_ids: Mapped[list] = mapped_column(JSON)
    iterations: Mapped[int] = mapped_column(Integer, default=1)
    options: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, default="draft")    # draft | queued | running | paused | done | cancelled | failed
    preflight: Mapped[dict] = mapped_column(JSON, default=dict)
    sample: Mapped[bool] = mapped_column(default=False)             # bundled sample results
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    started_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    ended_at: Mapped[float | None] = mapped_column(Float, nullable=True)


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"), index=True)
    profile_id: Mapped[str] = mapped_column(String, index=True)
    harness_id: Mapped[str] = mapped_column(String)
    benchmark_id: Mapped[str] = mapped_column(String)
    iteration: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String, default="queued")   # queued | running | grading | done | failed | cancelled | skipped
    stage: Mapped[str] = mapped_column(String, default="")
    dir: Mapped[str] = mapped_column(String, default="")
    started_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    ended_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    correctness: Mapped[float | None] = mapped_column(Float, nullable=True)
    instruction_following: Mapped[float | None] = mapped_column(Float, nullable=True)
    wall_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    quality: Mapped[dict] = mapped_column(JSON, default=dict)
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)      # profile/harness/benchmark as they were at run time
    error: Mapped[str] = mapped_column(Text, default="")


class Review(Base):
    __tablename__ = "reviews"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    judge_id: Mapped[str] = mapped_column(String)                   # profile id or external label
    judge_name: Mapped[str] = mapped_column(String)
    judge_job_id: Mapped[str] = mapped_column(String, default="")
    overall: Mapped[float | None] = mapped_column(Float, nullable=True)
    scores: Mapped[dict] = mapped_column(JSON, default=dict)
    summary: Mapped[str] = mapped_column(Text, default="")
    issues: Mapped[list] = mapped_column(JSON, default=list)
    extras: Mapped[list] = mapped_column(JSON, default=list)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String)                       # download | install | build | plan | judge | validate | smoke
    title: Mapped[str] = mapped_column(String)
    ref: Mapped[str] = mapped_column(String, default="")            # object the job works on
    status: Mapped[str] = mapped_column(String, default="queued")   # queued | running | done | failed | cancelled | interrupted
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    detail: Mapped[str] = mapped_column(Text, default="")
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    log: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    started_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    ended_at: Mapped[float | None] = mapped_column(Float, nullable=True)


engine = None
Session = None


def init(url=None):
    global engine, Session
    DATA.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url or f"sqlite:///{DATA / 'llmdyno.db'}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _pragmas(conn, _):
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=10000")
        cur.close()

    Base.metadata.create_all(engine)
    _migrate(engine)
    Session = sessionmaker(engine, expire_on_commit=False)
    return engine


# ------------------------------------------------------------------ schema versioning
# The schema version lives in SQLite's own user_version field. A release that changes the schema bumps SCHEMA_VERSION
# and adds MIGRATIONS[old] = fn(conn) to move a database from version old to old + 1; create_all() above already adds
# new tables. A database written by a newer LLMDyno is refused rather than silently damaged.
SCHEMA_VERSION = 1
MIGRATIONS = {}


def _migrate(eng):
    with eng.begin() as conn:
        current = conn.exec_driver_sql("PRAGMA user_version").scalar() or 0
        if current > SCHEMA_VERSION:
            raise RuntimeError(f"this data folder was created by a newer LLMDyno (database schema {current}, this "
                               f"version understands {SCHEMA_VERSION}); upgrade LLMDyno or use another data folder")
        while current < SCHEMA_VERSION:
            step = MIGRATIONS.get(current)
            if step:
                step(conn)
            current += 1
        conn.exec_driver_sql(f"PRAGMA user_version = {SCHEMA_VERSION}")


def row(obj):
    """Plain dict of a mapped object's columns."""
    return {c.key: getattr(obj, c.key) for c in obj.__mapper__.column_attrs}
