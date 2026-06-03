import asyncio
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI
import logging

from routers.logging import router as logging_router
from routers.management import router as management_router
from utils.log_manager import LogManager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("logging-service")

log_manager = LogManager()

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Logging Service...")
    asyncio.create_task(periodic_cleanup())
    yield
    logger.info("Shutting down Logging Service...")

app = FastAPI(
    title="Microfrontend Logger",
    version="1.0",
    lifespan=lifespan
)

app.include_router(logging_router)
app.include_router(management_router)

async def periodic_cleanup():
    while True:
        await asyncio.sleep(3600 * 24)
        try:
            log_manager.cleanup_and_compress()
        except Exception as e:
            logger.error(f"Cleanup task failed: {e}")


@app.get("/health", tags=["System"])
async def health():
    return {"status": "ok", "time": datetime.now().isoformat()}
