"""Интерфейс репозитория отчетов"""
from abc import ABC, abstractmethod
from typing import List, Optional
from uuid import UUID

from domain.entities.meeting_report import MeetingReport


class IReportRepository(ABC):
    """Интерфейс для работы с отчетами"""
    
    @abstractmethod
    async def save(self, report: MeetingReport) -> None:
        """Сохранить отчет"""
        pass
    
    @abstractmethod
    async def get_by_meeting_id(self, meeting_id: UUID) -> Optional[MeetingReport]:
        """Получить отчет по ID совещания"""
        pass
    
    @abstractmethod
    async def get_all(self) -> List[MeetingReport]:
        """Получить все отчеты"""
        pass



