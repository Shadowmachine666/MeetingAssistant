"""Реализация репозитория совещаний"""
import json
import os
from pathlib import Path
from typing import List, Optional
from uuid import UUID

from domain.entities.meeting import Meeting
from domain.interfaces.meeting_repository import IMeetingRepository


class MeetingRepository(IMeetingRepository):
    """Реализация репозитория совещаний (in-memory + JSON)"""
    
    def __init__(self, storage_path: str = "./Config"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.meetings_file = self.storage_path / "meetings.json"
        self._meetings: dict[UUID, Meeting] = {}
        self._current_meeting: Optional[Meeting] = None
        self._load()
    
    def _load(self) -> None:
        """Загрузить совещания из файла"""
        if self.meetings_file.exists():
            try:
                with open(self.meetings_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # В реальном проекте нужно десериализовать Meeting объекты
                    # Для простоты используем in-memory хранилище
            except Exception:
                pass
    
    def _save(self) -> None:
        """Сохранить совещания в файл"""
        try:
            data = {
                str(meeting.id): {
                    "id": str(meeting.id),
                    "start_time": meeting.start_time.isoformat(),
                    "end_time": meeting.end_time.isoformat() if meeting.end_time else None,
                    "status": meeting.status.value,
                    "recording_path": meeting.recording_path,
                    "report_path": meeting.report_path,
                    "template_path": meeting.template_path
                }
                for meeting in self._meetings.values()
            }
            with open(self.meetings_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass
    
    async def save(self, meeting: Meeting) -> None:
        """Сохранить совещание"""
        self._meetings[meeting.id] = meeting
        if meeting.status.value == "Recording":
            self._current_meeting = meeting
        self._save()
    
    async def get_by_id(self, meeting_id: UUID) -> Optional[Meeting]:
        """Получить совещание по ID"""
        return self._meetings.get(meeting_id)
    
    async def get_all(self) -> List[Meeting]:
        """Получить все совещания"""
        return list(self._meetings.values())
    
    async def get_current(self) -> Optional[Meeting]:
        """Получить текущее активное совещание"""
        return self._current_meeting



