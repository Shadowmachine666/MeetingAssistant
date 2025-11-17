"""Точка входа приложения"""
import asyncio
import os
import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from application.services.meeting_service import MeetingService
from application.services.template_service import TemplateService
from application.services.translation_service import TranslationService
from infrastructure.external_services.audio.audio_recorder import AudioRecorder
from infrastructure.external_services.openai.openai_client import OpenAIClient
from infrastructure.file_system.file_parser import FileParserFactory
from infrastructure.repositories.meeting_repository import MeetingRepository
from infrastructure.repositories.recording_repository import RecordingRepository
from infrastructure.repositories.report_repository import ReportRepository
from infrastructure.repositories.template_repository import TemplateRepository
from infrastructure.storage.storage_service import StorageService
from presentation.main_window import MainWindow


def setup_dependencies():
    """Настроить зависимости (DI)"""
    # Storage
    storage_service = StorageService(
        recordings_path=os.getenv("STORAGE_RECORDINGS_PATH", "./Recordings"),
        reports_path=os.getenv("STORAGE_REPORTS_PATH", "./Reports"),
        templates_path=os.getenv("STORAGE_TEMPLATES_PATH", "./Templates"),
        logs_path=os.getenv("STORAGE_LOGS_PATH", "./Logs")
    )
    
    # Repositories
    meeting_repository = MeetingRepository()
    recording_repository = RecordingRepository()
    report_repository = ReportRepository()
    template_repository = TemplateRepository()
    
    # External services
    openai_client = OpenAIClient()
    audio_recorder = AudioRecorder(
        sample_rate=int(os.getenv("AUDIO_SAMPLE_RATE", "44100")),
        channels=int(os.getenv("AUDIO_CHANNELS", "2"))
    )
    
    # File system
    file_parser_factory = FileParserFactory()
    
    # Application services
    meeting_service = MeetingService(
        meeting_repository=meeting_repository,
        recording_repository=recording_repository,
        audio_recorder=audio_recorder,
        storage_service=storage_service,
        openai_client=openai_client
    )
    
    translation_service = TranslationService(
        audio_recorder=audio_recorder,
        openai_client=openai_client,
        storage_service=storage_service
    )
    
    template_service = TemplateService(
        template_repository=template_repository,
        file_parser_factory=file_parser_factory
    )
    
    return meeting_service, translation_service, template_service


def main():
    """Главная функция"""
    # Загрузить переменные окружения
    from dotenv import load_dotenv
    load_dotenv()
    
    # Проверить наличие API ключа
    if not os.getenv("OPENAI_API_KEY") and not os.getenv("OPENAI_API_KEY_1"):
        print("ОШИБКА: OpenAI API ключ не найден!")
        print("Создайте файл .env и добавьте OPENAI_API_KEY=sk-...")
        print("Или скопируйте .env.example в .env и заполните его")
        sys.exit(1)
    
    # Создать приложение
    app = QApplication(sys.argv)
    app.setApplicationName("MeetingAssistant")
    
    # Настроить зависимости
    meeting_service, translation_service, template_service = setup_dependencies()
    
    # Создать главное окно
    window = MainWindow(
        meeting_service=meeting_service,
        translation_service=translation_service,
        template_service=template_service
    )
    window.show()
    
    # Запустить приложение
    sys.exit(app.exec())


if __name__ == "__main__":
    main()



