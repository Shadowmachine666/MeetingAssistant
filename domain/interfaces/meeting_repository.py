"""Интерфейс репозитория совещаний"""
from abc import ABC, abstractmethod
from typing import List, Optional
from uuid import UUID

from domain.entities.meeting import Meeting


class IMeetingRepository(ABC):
    """Интерфейс для работы с совещаниями"""
    
    @abstractmethod
    async def save(self, meeting: Meeting) -> None:
        """Сохранить совещание"""
        pass
    
    @abstractmethod
    async def get_by_id(self, meeting_id: UUID) -> Optional[Meeting]:
        """Получить совещание по ID"""
        pass
    
    @abstractmethod
    async def get_all(self) -> List[Meeting]:
        """Получить все совещания"""
        pass
    
    @abstractmethod
    async def get_current(self) -> Optional[Meeting]:
        """Получить текущее активное совещание"""
        pass



