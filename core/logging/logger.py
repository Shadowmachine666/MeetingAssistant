"""Система логирования"""
import logging
import os
from datetime import datetime
from pathlib import Path
from logging.handlers import RotatingFileHandler


class AppLogger:
    """Логгер приложения"""
    
    _instance = None
    _logger = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._logger is None:
            self._setup_logger()
    
    def _setup_logger(self):
        """Настроить логгер"""
        self._logger = logging.getLogger("MeetingAssistant")
        self._logger.setLevel(logging.DEBUG)
        
        # Формат логов
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # Консольный handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        self._logger.addHandler(console_handler)
        
        # Файловый handler с ротацией
        logs_dir = Path(os.getenv("STORAGE_LOGS_PATH", "./Logs"))
        logs_dir.mkdir(parents=True, exist_ok=True)
        
        log_file = logs_dir / f"app_{datetime.now().strftime('%Y-%m-%d')}.log"
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        self._logger.addHandler(file_handler)
    
    def get_logger(self):
        """Получить логгер"""
        return self._logger
    
    @classmethod
    def get_instance(cls):
        """Получить экземпляр логгера"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance.get_logger()


def get_logger():
    """Получить логгер (удобная функция)"""
    return AppLogger.get_instance()

