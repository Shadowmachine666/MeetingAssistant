"""Пул API ключей с отслеживанием занятости"""
import asyncio
import os
from typing import Optional, Dict
from dataclasses import dataclass, field
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from core.logging.logger import get_logger
from core.exceptions.api_exception import ApiKeyNotFoundException

load_dotenv()


@dataclass
class ApiKeyInfo:
    """Информация об API ключе"""
    key: str
    index: int
    active_requests: int = 0
    total_requests: int = 0
    failed_requests: int = 0
    is_blocked: bool = False  # Временно заблокирован из-за ошибок


class ApiKeyPool:
    """Пул API ключей с балансировкой нагрузки и отслеживанием занятости"""
    
    def __init__(self):
        self.logger = get_logger()
        self._lock = asyncio.Lock()
        self._keys: Dict[int, ApiKeyInfo] = {}
        self._load_keys()
        
        if not self._keys:
            raise ApiKeyNotFoundException("OpenAI API ключ не найден в .env файле")
        
        self.logger.info(f"Инициализирован пул API ключей: {len(self._keys)} ключ(ей)")
    
    def _load_keys(self):
        """Загрузить ключи из .env файла"""
        key_index = 0
        loaded_keys = []
        for i in range(1, 4):  # OPENAI_API_KEY_1, OPENAI_API_KEY_2, OPENAI_API_KEY_3
            key = os.getenv(f"OPENAI_API_KEY_{i}")
            if key and key.strip():
                self._keys[key_index] = ApiKeyInfo(key=key.strip(), index=key_index)
                loaded_keys.append(f"OPENAI_API_KEY_{i}")
                key_index += 1
                self.logger.info(f"✅ Загружен API ключ {i} (индекс {key_index - 1}): OPENAI_API_KEY_{i}")
        
        # Fallback на OPENAI_API_KEY если нет пронумерованных ключей
        if not self._keys:
            key = os.getenv("OPENAI_API_KEY")
            if key and key.strip():
                self._keys[0] = ApiKeyInfo(key=key.strip(), index=0)
                loaded_keys.append("OPENAI_API_KEY")
                self.logger.info("✅ Загружен API ключ из OPENAI_API_KEY")
        
        # Логировать итоговую информацию о загруженных ключах
        if loaded_keys:
            self.logger.info(f"📋 Загружено ключей: {len(loaded_keys)} - {', '.join(loaded_keys)}")
        else:
            self.logger.warning("⚠️ Не загружено ни одного API ключа")
    
    async def get_available_key(self) -> Optional[str]:
        """Получить доступный ключ (наименее загруженный)"""
        async with self._lock:
            if not self._keys:
                return None
            
            # Найти ключ с минимальным количеством активных запросов среди незаблокированных
            available_keys = {idx: info for idx, info in self._keys.items() if not info.is_blocked}
            
            if not available_keys:
                # Если все заблокированы, использовать наименее загруженный
                available_keys = self._keys
                self.logger.warning("Все ключи заблокированы, используется наименее загруженный")
            
            # Выбрать ключ с минимальным количеством активных запросов
            best_key_info = min(available_keys.values(), key=lambda k: k.active_requests)
            best_key_info.active_requests += 1
            best_key_info.total_requests += 1
            
            self.logger.info(
                f"🔑 Выбран ключ {best_key_info.index + 1}: активных запросов={best_key_info.active_requests}, "
                f"всего запросов={best_key_info.total_requests}"
            )
            
            return best_key_info.key
    
    async def release_key(self, key: str):
        """Освободить ключ после завершения запроса"""
        async with self._lock:
            for key_info in self._keys.values():
                if key_info.key == key:
                    key_info.active_requests = max(0, key_info.active_requests - 1)
                    self.logger.debug(
                        f"🔓 Освобожден ключ {key_info.index + 1}: активных запросов={key_info.active_requests}"
                    )
                    return
    
    async def mark_key_failed(self, key: str, block_temporarily: bool = False):
        """Пометить ключ как проблемный"""
        async with self._lock:
            for key_info in self._keys.values():
                if key_info.key == key:
                    key_info.failed_requests += 1
                    if block_temporarily:
                        key_info.is_blocked = True
                        self.logger.warning(
                            f"⚠️ Ключ {key_info.index + 1} временно заблокирован из-за ошибок. "
                            f"Всего ошибок: {key_info.failed_requests}"
                        )
                    else:
                        self.logger.warning(
                            f"⚠️ Ошибка на ключе {key_info.index + 1}. Всего ошибок: {key_info.failed_requests}"
                        )
                    return
    
    async def unblock_key(self, key: str):
        """Разблокировать ключ"""
        async with self._lock:
            for key_info in self._keys.values():
                if key_info.key == key:
                    if key_info.is_blocked:
                        key_info.is_blocked = False
                        self.logger.info(f"✅ Ключ {key_info.index + 1} разблокирован")
                    return
    
    @asynccontextmanager
    async def acquire_key(self):
        """Контекстный менеджер для получения и освобождения ключа"""
        key = await self.get_available_key()
        if not key:
            raise ApiKeyNotFoundException("Нет доступных API ключей")
        
        try:
            yield key
        finally:
            await self.release_key(key)
    
    def get_stats(self) -> Dict:
        """Получить статистику использования ключей"""
        return {
            idx: {
                "active_requests": info.active_requests,
                "total_requests": info.total_requests,
                "failed_requests": info.failed_requests,
                "is_blocked": info.is_blocked
            }
            for idx, info in self._keys.items()
        }
    
    def get_total_keys(self) -> int:
        """Получить общее количество ключей"""
        return len(self._keys)

