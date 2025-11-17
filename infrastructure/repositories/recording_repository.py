"""Реализация репозитория записей"""
from typing import List, Optional
from uuid import UUID

from domain.entities.meeting_recording import MeetingRecording
from domain.interfaces.recording_repository import IRecordingRepository


class RecordingRepository(IRecordingRepository):
    """Реализация репозитория записей (in-memory)"""
    
    def __init__(self):
        self._recordings: dict[UUID, MeetingRecording] = {}
    
    async def save(self, recording: MeetingRecording) -> None:
        """Сохранить запись"""
        self._recordings[recording.id] = recording
    
    async def get_by_meeting_id(self, meeting_id: UUID) -> Optional[MeetingRecording]:
        """Получить запись по ID совещания"""
        for recording in self._recordings.values():
            if recording.meeting_id == meeting_id:
                return recording
        return None
    
    async def get_all(self) -> List[MeetingRecording]:
        """Получить все записи"""
        return list(self._recordings.values())



