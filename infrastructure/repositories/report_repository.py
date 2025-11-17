"""Реализация репозитория отчетов"""
from typing import List, Optional
from uuid import UUID

from domain.entities.meeting_report import MeetingReport
from domain.interfaces.report_repository import IReportRepository


class ReportRepository(IReportRepository):
    """Реализация репозитория отчетов (in-memory)"""
    
    def __init__(self):
        self._reports: dict[UUID, MeetingReport] = {}
    
    async def save(self, report: MeetingReport) -> None:
        """Сохранить отчет"""
        self._reports[report.id] = report
    
    async def get_by_meeting_id(self, meeting_id: UUID) -> Optional[MeetingReport]:
        """Получить отчет по ID совещания"""
        for report in self._reports.values():
            if report.meeting_id == meeting_id:
                return report
        return None
    
    async def get_all(self) -> List[MeetingReport]:
        """Получить все отчеты"""
        return list(self._reports.values())



