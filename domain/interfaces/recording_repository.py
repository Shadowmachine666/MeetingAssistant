"""Интерфейс репозитория записей"""
from abc import ABC, abstractmethod
from typing import List, Optional
from uuid import UUID

from domain.entities.meeting_recording import MeetingRecording


class IRecordingRepository(ABC):
    """Интерфейс для работы с записями"""
    
    @abstractmethod
    async def save(self, recording: MeetingRecording) -> None:
        """Сохранить запись"""
        pass
    
    @abstractmethod
    async def get_by_meeting_id(self, meeting_id: UUID) -> Optional[MeetingRecording]:
        """Получить запись по ID совещания"""
        pass
    
    @abstractmethod
    async def get_all(self) -> List[MeetingRecording]:
        """Получить все записи"""
        pass



