"""Сервис хранилища"""
import os
from datetime import datetime
from pathlib import Path
from typing import Optional


class StorageService:
    """Сервис для работы с хранилищем файлов"""
    
    def __init__(self, 
                 recordings_path: str = "./Recordings",
                 reports_path: str = "./Reports",
                 templates_path: str = "./Templates",
                 logs_path: str = "./Logs"):
        self.recordings_path = Path(recordings_path)
        self.reports_path = Path(reports_path)
        self.templates_path = Path(templates_path)
        self.logs_path = Path(logs_path)
        
        # Создать директории
        self.recordings_path.mkdir(parents=True, exist_ok=True)
        self.reports_path.mkdir(parents=True, exist_ok=True)
        self.templates_path.mkdir(parents=True, exist_ok=True)
        self.logs_path.mkdir(parents=True, exist_ok=True)
    
    def get_recording_path(self, meeting_id: str) -> str:
        """Получить путь для записи совещания"""
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"{timestamp}_meeting_{meeting_id[:8]}.wav"
        return str(self.recordings_path / filename)
    
    def get_report_path(self, meeting_id: str) -> str:
        """Получить путь для отчета"""
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"{timestamp}_report_{meeting_id[:8]}.md"
        return str(self.reports_path / filename)
    
    def save_report(self, meeting_id: str, content: str) -> str:
        """Сохранить отчет в файл"""
        report_path = self.get_report_path(meeting_id)
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return report_path
    
    def get_temp_audio_path(self, prefix: str = "temp") -> str:
        """Получить путь для временного аудио файла"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{prefix}_{timestamp}.wav"
        return str(self.recordings_path / filename)



