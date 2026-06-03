from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException

from config import API_KEY
from models import ServiceStats
from utils.log_manager import LogManager

router = APIRouter(
    prefix="/api/v1",
    tags=["Management"]
)

log_manager = LogManager()

async def verify_api_key(x_api_key: str = Header(..., alias="X-API-Key")):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Forbidden: Invalid API Key")


@router.get("/services", dependencies=[Depends(verify_api_key)])
async def list_services():
    """Список сервисов"""
    if not log_manager.base_dir.exists():
        return {"services": []}
    
    services = [d.name for d in log_manager.base_dir.iterdir() if d.is_dir()]
    return {"services": sorted(services), "count": len(services)}


@router.get("/services/{service_id}/stats", response_model=ServiceStats, dependencies=[Depends(verify_api_key)])
async def get_stats(service_id: str, date: Optional[str] = None):
    """Статистика по сервису"""
    return log_manager.get_stats(service_id, date)
