"""Сущность записи совещания"""
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4


@dataclass
class MeetingRecording:
    """Запись совещания"""
    id: UUID
    meeting_id: UUID
    file_path: str
    duration_seconds: float
    file_size_bytes: int
    created_at: datetime
    sample_rate: int = 44100
    channels: int = 2
    
    @classmethod
    def create(cls, meeting_id: UUID, file_path: str, duration_seconds: float, 
               file_size_bytes: int, sample_rate: int = 44100, channels: int = 2) -> "MeetingRecording":
        """Создать новую запись"""
        return cls(
            id=uuid4(),
            meeting_id=meeting_id,
            file_path=file_path,
            duration_seconds=duration_seconds,
            file_size_bytes=file_size_bytes,
            created_at=datetime.now(),
            sample_rate=sample_rate,
            channels=channels
        )
    
    @property
    def exists(self) -> bool:
        """Проверить существование файла"""
        return Path(self.file_path).exists()



