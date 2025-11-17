"""Сущность отчета о совещании"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from domain.enums.language import Language


@dataclass
class MeetingReport:
    """Отчет о совещании"""
    id: UUID
    meeting_id: UUID
    content: str
    language: Language
    created_at: datetime
    template_path: Optional[str] = None
    
    @classmethod
    def create(cls, meeting_id: UUID, content: str, language: Language, 
               template_path: Optional[str] = None) -> "MeetingReport":
        """Создать новый отчет"""
        return cls(
            id=uuid4(),
            meeting_id=meeting_id,
            content=content,
            language=language,
            created_at=datetime.now(),
            template_path=template_path
        )

