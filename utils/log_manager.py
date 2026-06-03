import os
import re
import json
import asyncio
import shutil
import hashlib
import gzip
from datetime import datetime, date, timedelta
from typing import Optional, Dict, Any, List
from pathlib import Path
import logging
import aiofiles
from fastapi import Depends, HTTPException

from config import GLOBAL_MAX_LOGS_PER_SECOND, LOGS_BASE_DIR, MAX_LOGS_PER_MINUTE_PER_SERVICE, RETENTION_DAYS
from models import LogEntry, ServiceStats
from utils.telegram import send_error_to_telegram

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("logging-service")


class LogManager:
    def __init__(self, base_dir: str = LOGS_BASE_DIR, retention_days: int = RETENTION_DAYS):
        self.base_dir = Path(base_dir)
        try:
            self.base_dir.mkdir(parents=True, exist_ok=True, mode=0o777)
        except Exception as e:
            logger.error(f"Failed to create log directory {base_dir}: {e}")
            
        self.retention_days = retention_days
        self.service_rate_limits: Dict[str, Dict[str, Any]] = {}
        self.global_rate_limit = {"count": 0, "reset_time": 0}
        self._lock = asyncio.Lock()

    def _sanitize_service_id(self, service_id: str) -> str:
        if not service_id:
            raise ValueError("Service ID cannot be empty")
        sanitized = re.sub(r'[^a-zA-Z0-9_-]', '_', service_id)
        if '..' in sanitized or sanitized.startswith('/') or sanitized.startswith('.'):
            raise ValueError("Invalid service ID format")
        return sanitized

    async def check_rate_limit(self, service_id: str) -> bool:
        now = datetime.now().timestamp()
        safe_id = self._sanitize_service_id(service_id)
        
        async with self._lock:
            if now > self.global_rate_limit["reset_time"]:
                self.global_rate_limit = {"count": 1, "reset_time": now + 1}
            else:
                self.global_rate_limit["count"] += 1
                if self.global_rate_limit["count"] > GLOBAL_MAX_LOGS_PER_SECOND:
                    return False

            if safe_id not in self.service_rate_limits:
                self.service_rate_limits[safe_id] = {"count": 1, "reset_time": now + 60}
                return True
            
            data = self.service_rate_limits[safe_id]
            
            if now > data["reset_time"]:
                self.service_rate_limits[safe_id] = {"count": 1, "reset_time": now + 60}
                return True
            
            if data["count"] >= MAX_LOGS_PER_MINUTE_PER_SERVICE:
                return False
            
            data["count"] += 1
            return True

    def _get_log_file_path(self, service_id: str, date_str: str) -> Path:
        safe_id = self._sanitize_service_id(service_id)
        service_dir = self.base_dir / safe_id
        service_dir.mkdir(parents=True, exist_ok=True)
        return service_dir / f"{date_str}.jsonl"

    def _format_telegram_message(self, entry: LogEntry) -> str:
        header = f"<b>{entry.title}</b>\n"
        header += f"<i>Service:</i> <code>{entry.service_id}</code> | <i>Level:</i> {entry.level}\n"
        
        if entry.user_id:
            header += f"<i>User:</i> <code>{entry.user_id}</code>\n"
        if entry.url:
            header += f"<i>URL:</i> <a href='{entry.url}'>Link</a>\n"
        if entry.ip_address:
            header += f"<i>IP:</i> <code>{entry.ip_address}</code>\n"
            
        msg_preview = entry.message[:1500] 
        body = f"\n<b>Message:</b>\n<pre>{msg_preview}</pre>"
        
        if entry.stack_trace:
            stack_preview = entry.stack_trace[:800].replace('<', '&lt;').replace('>', '&gt;')
            body += f"\n<b>Stack Trace (preview):</b>\n<pre>{stack_preview}...</pre>"
            
        return header + body

    async def save_log(self, log_entry: LogEntry) -> tuple[str, str]:
        if not await self.check_rate_limit(log_entry.service_id):
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
        
        now = datetime.now()
        group_id = log_entry.generate_fingerprint()
        log_entry.group_id = group_id
        
        log_dict = log_entry.model_dump(by_alias=True, exclude_none=False)
        log_dict['received_at'] = now.isoformat()
        
        log_id = f"{int(now.timestamp() * 1000)}_{hashlib.md5(os.urandom(4)).hexdigest()[:8]}"
        log_dict['log_id'] = log_id
        
        targets = log_entry.targets if log_entry.targets is not None else [0]
        should_send_tg = 1 in targets
        should_save_file = 0 in targets

        # 1. Отправка в Telegram (в фоне)
        if should_send_tg:
            try:
                tg_message = self._format_telegram_message(log_entry)
                topic_id = getattr(log_entry, 'topic_id', None) or 2 
                
                asyncio.create_task(
                    asyncio.to_thread(
                        send_error_to_telegram, 
                        tg_message, 
                        topic_id, 
                        log_entry.level
                    )
                )
            except Exception as e:
                logger.error(f"Failed to schedule Telegram task: {e}")

        # 2. Сохранение в файл
        if should_save_file:
            log_line = json.dumps(log_dict, ensure_ascii=False, default=str) + "\n"
            file_path = self._get_log_file_path(log_entry.service_id, date.today().isoformat())
            
            try:
                async with aiofiles.open(file_path, mode='a', encoding='utf-8') as f:
                    await f.write(log_line)
            except Exception as e:
                logger.error(f"Disk write error: {e}")
        
        return log_id, group_id

    def get_stats(self, service_id: str, date_str: Optional[str] = None) -> ServiceStats:
        safe_id = self._sanitize_service_id(service_id)
        target_date = date_str or date.today().isoformat()
        file_path = self._get_log_file_path(safe_id, target_date)
        
        stats = ServiceStats(
            service_id=service_id,
            total_logs=0, error_count=0, warning_count=0, info_count=0, debug_count=0,
            unique_groups=0
        )
         
        if not file_path.exists():
            return stats
            
        groups_seen = set()
            
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if not line.strip(): continue
                    try:
                        entry = json.loads(line)
                        stats.total_logs += 1
                        
                        lvl = entry.get('level', 'info')
                        if lvl == 'error': stats.error_count += 1
                        elif lvl == 'warning': stats.warning_count += 1
                        elif lvl == 'info': stats.info_count += 1
                        elif lvl == 'debug': stats.debug_count += 1
                        
                        if entry.get('group_id'):
                            groups_seen.add(entry['group_id'])
                            
                    except: continue
        except Exception as e:
            logger.error(f"Stats read error: {e}")
            
        stats.unique_groups = len(groups_seen)
        return stats

    def read_logs(
        self, 
        service_id: str, 
        date_str: str, 
        limit: int = 50, 
        offset: int = 0,
        level_filter: Optional[str] = None,
        search_query: Optional[str] = None,
        user_id_filter: Optional[str] = None,
        component_filter: Optional[str] = None
    ) -> List[Dict]:
        safe_id = self._sanitize_service_id(service_id)
        file_path = self._get_log_file_path(safe_id, date_str)
        
        logs = []
        if not file_path.exists():
            return logs
            
        matched_count = 0 
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if not line.strip(): continue
                    
                    try:
                        entry = json.loads(line)
                    except:
                        continue

                    if level_filter and entry.get('level') != level_filter:
                        continue
                    if user_id_filter and entry.get('user_id') != user_id_filter:
                        continue
                    if component_filter and entry.get('component_name') != component_filter:
                        continue
                    
                    if search_query:
                        q = search_query.lower()
                        text_blob = (
                            f"{entry.get('message', '')} "
                            f"{entry.get('title', '')} "
                            f"{entry.get('stack_trace', '')} "
                            f"{entry.get('url', '')}"
                        ).lower()
                        if q not in text_blob:
                            continue
        
                    if matched_count < offset:
                        matched_count += 1
                        continue
                    
                    if len(logs) >= limit:
                        break
                        
                    logs.append(entry)
                    matched_count += 1

        except Exception as e:
            logger.error(f"Read error: {e}")
            
        return logs

    def cleanup_and_compress(self):
        if not self.base_dir.exists(): return
        
        cutoff = date.today() - timedelta(days=self.retention_days)
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        
        for service_dir in self.base_dir.iterdir():
            if not service_dir.is_dir(): continue
            
            for log_file in service_dir.iterdir():
                if not log_file.is_file(): continue
                
                if log_file.name.startswith(yesterday) and log_file.name.endswith('.jsonl'):
                    gz_path = log_file.with_suffix('.jsonl.gz') 
                    if not gz_path.exists():
                        try:
                            with open(log_file, 'rb') as f_in:
                                with gzip.open(gz_path, 'wb') as f_out:
                                    shutil.copyfileobj(f_in, f_out)
                            log_file.unlink()
                            logger.info(f"Compressed: {log_file.name}")
                        except Exception as e:
                            logger.error(f"Compression failed: {e}")

                try:
                    date_part = log_file.name.split('.')[0]
                    file_date = date.fromisoformat(date_part)
                    
                    if file_date < cutoff:
                        log_file.unlink()
                        logger.info(f"Deleted old log: {log_file.name}")
                        
                        if not any(service_dir.iterdir()):
                            service_dir.rmdir()
                except ValueError:
                    continue 
                except Exception as e:
                    logger.error(f"Cleanup error for {log_file}: {e}")