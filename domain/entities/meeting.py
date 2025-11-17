"""Сущность совещания"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from domain.enums.meeting_status import MeetingStatus


@dataclass
class Meeting:
    """Сущность совещания"""
    id: UUID
    start_time: datetime
    end_time: Optional[datetime]
    status: MeetingStatus
    recording_path: Optional[str] = None
    report_path: Optional[str] = None
    template_path: Optional[str] = None
    
    @classmethod
    def create(cls) -> "Meeting":
        """Создать новое совещание"""
        return cls(
            id=uuid4(),
            start_time=datetime.now(),
            end_time=None,
            status=MeetingStatus.NOT_STARTED
        )
    
    def start(self) -> None:
        """Начать совещание"""
        self.status = MeetingStatus.RECORDING
        self.start_time = datetime.now()
    
    def stop(self) -> None:
        """Остановить совещание"""
        self.status = MeetingStatus.STOPPED
        self.end_time = datetime.now()
    
    def mark_processing(self) -> None:
        """Пометить как обрабатывается"""
        self.status = MeetingStatus.PROCESSING
    
    def mark_completed(self) -> None:
        """Пометить как завершено"""
        self.status = MeetingStatus.COMPLETED



