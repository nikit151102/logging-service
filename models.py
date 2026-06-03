# models.py
from pydantic import BaseModel, Field, field_validator
from typing import Optional, Dict, Any, List, Literal
import hashlib

class LogEntry(BaseModel):
    service_id: str = Field(..., min_length=1, max_length=100, description="ID микрофронта")
    title: str = Field(..., max_length=500, description="Краткий заголовок")
    message: str = Field(..., max_length=20000, description="Полное сообщение")
    level: str = Field(default="error", description="Уровень: error, warning, info, debug")
    section: Optional[str] = Field(None, max_length=200)
    url: Optional[str] = Field(None, max_length=2000)
    referrer: Optional[str] = Field(None, alias="previous_url", max_length=2000)
    user_id: Optional[str] = Field(None, max_length=100)
    session_id: Optional[str] = Field(None, max_length=100)
    ip_address: Optional[str] = Field(None, max_length=45, description="IP клиента (IPv4/IPv6)")
    environment: Optional[str] = Field("production")
    app_version: Optional[str] = Field(None, max_length=50)
    build_id: Optional[str] = Field(None, max_length=100)
    browser: Optional[str] = Field(None, max_length=300)
    os: Optional[str] = Field(None, max_length=100)
    device_type: Optional[str] = Field(None)
    screen_resolution: Optional[str] = Field(None, max_length=20)
    language: Optional[str] = Field(None, max_length=10)
    api_endpoint: Optional[str] = Field(None, max_length=2000)
    http_method: Optional[str] = Field(None, max_length=10)
    status_code: Optional[int] = Field(None)
    request_id: Optional[str] = Field(None, max_length=100)
    is_online: Optional[bool] = Field(True)
    stack_trace: Optional[str] = Field(None, max_length=100000)
    component_name: Optional[str] = Field(None, max_length=200)
    tags: Optional[List[str]] = Field(None)
    metadata: Optional[Dict[str, Any]] = Field(None)
    group_id: Optional[str] = Field(None, description="Hash for grouping similar errors")
    
    # 0 - сохранить в файл, 1 - отправить в Telegram
    targets: List[int] = Field(default=[0], description="Куда отправлять лог: [0]=File, [1]=Telegram")
    topic_id: Optional[int] = Field(None)

    @field_validator('level')
    @classmethod
    def validate_level(cls, v):
        allowed = {"error", "warning", "info", "debug"}
        if v.lower() not in allowed:
            raise ValueError(f"Level must be one of {allowed}")
        return v.lower()

    def generate_fingerprint(self) -> str:
        """Создает хэш для группировки похожих ошибок"""
        content = self.stack_trace or f"{self.message}_{self.component_name or 'unknown'}"
        raw_string = f"{self.service_id}::{content}"
        return hashlib.md5(raw_string.encode('utf-8')).hexdigest()

    class Config:
        populate_by_name = True

class LogResponse(BaseModel):
    status: str
    message: str
    log_id: str
    group_id: str

class ServiceStats(BaseModel):
    service_id: str
    total_logs: int
    error_count: int
    warning_count: int
    info_count: int
    debug_count: int
    unique_groups: int