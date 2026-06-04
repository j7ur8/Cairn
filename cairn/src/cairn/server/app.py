from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from cairn import __version__
from cairn.server import db
from cairn.server.observability import db as observability_db
from cairn.server.observability import routers as observability_routers
from cairn.server.routers import attachments, capabilities, export, files, hints, intents, projects, proxies, replay, settings

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.configure(db.DEFAULT_DB)
    observability_db.configure(observability_db.DEFAULT_OBSERVABILITY_DB)
    yield


app = FastAPI(
    title="Cairn",
    description="Fact-graph based collaborative exploration protocol",
    version=__version__,
    lifespan=lifespan,
)

app.include_router(settings.router)
app.include_router(proxies.router)
app.include_router(projects.router)
app.include_router(hints.router)
app.include_router(attachments.router)
app.include_router(intents.router)
app.include_router(export.router)
app.include_router(files.router)
app.include_router(replay.router)
app.include_router(capabilities.router)
app.include_router(observability_routers.router)


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
