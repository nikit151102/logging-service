from typing import Optional, List, Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Header
from datetime import datetime

from config import API_KEY
from models import LogEntry, LogResponse
from utils.log_manager import LogManager

router = APIRouter(
    prefix="/api/v1",
    tags=["Logging"]
)

log_manager = LogManager()

async def verify_api_key(x_api_key: str = Header(..., alias="X-API-Key")):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Forbidden: Invalid API Key")


@router.post("/logs", response_model=LogResponse, dependencies=[Depends(verify_api_key)])
async def create_log(log_entry: LogEntry):
    """Принимает одиночный лог"""
    log_id, group_id = await log_manager.save_log(log_entry)
    return LogResponse(status="success", message="Logged", log_id=log_id, group_id=group_id)


@router.post("/logs/batch", dependencies=[Depends(verify_api_key)])
async def create_batch_logs(entries: List[LogEntry]):
    """Массовая загрузка (макс 50 за раз)"""
    if len(entries) > 50:
        raise HTTPException(status_code=400, detail="Batch too large")
    
    success = 0
    errors = 0
    last_group_id = ""
    
    for entry in entries:
        try:
            _, gid = await log_manager.save_log(entry)
            last_group_id = gid
            success += 1
        except HTTPException:
            errors += 1
        except Exception:
            errors += 1
            
    return {"status": "processed", "success": success, "errors": errors, "last_group_id": last_group_id}


@router.get("/services/{service_id}/logs", dependencies=[Depends(verify_api_key)], tags=["Logs"])
async def get_logs(
    service_id: str, 
    date: str = Query(..., description="YYYY-MM-DD"),
    limit: int = Query(50, le=500),
    offset: int = Query(0, ge=0),
    level: Optional[Literal["error", "warning", "info", "debug"]] = Query(None),
    q: Optional[str] = Query(None, description="Search in message/stacktrace"),
    user_id: Optional[str] = Query(None),
    component: Optional[str] = Query(None)
):
    """Просмотр логов с фильтрацией"""
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")
        
    logs = log_manager.read_logs(
        service_id, 
        date, 
        limit, 
        offset,
        level_filter=level,
        search_query=q,
        user_id_filter=user_id,
        component_filter=component
    )
    
    return {
        "service_id": service_id,
        "date": date,
        "count": len(logs),
        "filters": {
            "level": level,
            "search": q,
            "user_id": user_id,
            "component": component
        },
        "data": logs
    }