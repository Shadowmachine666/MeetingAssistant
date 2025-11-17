"""Точка входа приложения"""
import asyncio
import os
import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication, QMessageBox

from application.services.meeting_service import MeetingService
from application.services.template_service import TemplateService
from application.services.translation_service import TranslationService
from core.health.health_checker import HealthChecker
from core.logging.logger import get_logger
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
    # Создать пул ключей (singleton для всего приложения)
    from infrastructure.external_services.openai.api_key_pool import ApiKeyPool
    api_key_pool = ApiKeyPool()
    
    # Создать OpenAI клиент с пулом ключей
    openai_client = OpenAIClient(api_key_pool=api_key_pool)
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
    
    # Инициализировать логгер
    logger = get_logger()
    logger.info("=" * 60)
    logger.info("Запуск MeetingAssistant")
    logger.info("=" * 60)
    
    # Выполнить проверки готовности
    logger.info("Выполнение проверок готовности системы...")
    health_checker = HealthChecker()
    results = health_checker.check_all()
    
    passed, total, all_passed = health_checker.get_summary()
    
    # Создать приложение
    app = QApplication(sys.argv)
    app.setApplicationName("MeetingAssistant")
    
    # Показать результаты проверок
    if not all_passed:
        message = "Проверка готовности системы:\n\n"
        for result in results:
            icon = "✓" if result.status else "✗"
            message += f"{icon} {result.name}: {result.message}\n"
            if result.details:
                message += f"   ({result.details})\n"
        
        message += f"\nПройдено: {passed}/{total} проверок"
        
        if passed == 0:
            msg_box = QMessageBox()
            msg_box.setIcon(QMessageBox.Icon.Critical)
            msg_box.setWindowTitle("Критические ошибки")
            msg_box.setText(message + "\n\nПриложение не может работать. Исправьте ошибки и перезапустите.")
            msg_box.exec()
            logger.error("Критические ошибки обнаружены. Приложение завершено.")
            sys.exit(1)
        else:
            msg_box = QMessageBox()
            msg_box.setIcon(QMessageBox.Icon.Warning)
            msg_box.setWindowTitle("Предупреждения")
            msg_box.setText(message + "\n\nНекоторые функции могут работать некорректно.")
            msg_box.exec()
    
    # Настроить зависимости
    logger.info("Инициализация сервисов...")
    try:
        meeting_service, translation_service, template_service = setup_dependencies()
        logger.info("Сервисы инициализированы успешно")
        
        # Проверить и очистить зависшие совещания
        logger.info("Проверка зависших совещаний...")
        try:
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            current_meeting = loop.run_until_complete(meeting_service.meeting_repository.get_current())
            if current_meeting and current_meeting.status.value == "Recording":
                logger.warning(f"Обнаружено зависшее совещание: ID={current_meeting.id}, статус={current_meeting.status.value}")
                # Остановить запись, если она идет
                try:
                    if meeting_service.audio_recorder.is_recording:
                        logger.info("Остановка зависшей записи...")
                        meeting_service.audio_recorder.stop_recording()
                except Exception as e:
                    logger.warning(f"Не удалось остановить запись: {e}")
                # Изменить статус на Stopped
                current_meeting.stop()
                loop.run_until_complete(meeting_service.meeting_repository.save(current_meeting))
                logger.info("Зависшее совещание исправлено")
            loop.close()
        except Exception as e:
            logger.warning(f"Ошибка при проверке зависших совещаний: {e}")
    except Exception as e:
        logger.error(f"Ошибка инициализации сервисов: {str(e)}", exc_info=True)
        QMessageBox.critical(
            None,
            "Ошибка инициализации",
            f"Не удалось инициализировать сервисы:\n{str(e)}"
        )
        sys.exit(1)
    
    # Создать главное окно
    logger.info("Создание главного окна...")
    window = MainWindow(
        meeting_service=meeting_service,
        translation_service=translation_service,
        template_service=template_service
    )
    window.show()
    logger.info("Приложение готово к работе")
    
    # Запустить приложение
    sys.exit(app.exec())


if __name__ == "__main__":
    main()



