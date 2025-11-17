"""Сервис управления совещаниями"""
from pathlib import Path
from uuid import UUID

from core.exceptions.meeting_exception import (
    MeetingAlreadyStartedException,
    MeetingNotStartedException,
    MeetingNotStoppedException
)
from core.logging.logger import get_logger
from domain.entities.meeting import Meeting
from domain.entities.meeting_recording import MeetingRecording
from domain.interfaces.meeting_repository import IMeetingRepository
from domain.interfaces.recording_repository import IRecordingRepository
from infrastructure.external_services.audio.audio_recorder import AudioRecorder
from infrastructure.external_services.openai.openai_client import OpenAIClient
from infrastructure.file_system.audio_splitter import AudioSplitter
from infrastructure.storage.storage_service import StorageService


class MeetingService:
    """Сервис для управления совещаниями"""
    
    def __init__(self,
                 meeting_repository: IMeetingRepository,
                 recording_repository: IRecordingRepository,
                 audio_recorder: AudioRecorder,
                 storage_service: StorageService,
                 openai_client: OpenAIClient):
        self.meeting_repository = meeting_repository
        self.recording_repository = recording_repository
        self.audio_recorder = audio_recorder
        self.storage_service = storage_service
        self.openai_client = openai_client
        self.logger = get_logger()
    
    async def start_meeting(self) -> Meeting:
        """Начать совещание"""
        self.logger.info("Запуск start_meeting")
        current = await self.meeting_repository.get_current()
        if current and current.status.value == "Recording":
            self.logger.warning("Попытка начать совещание, когда уже идет запись")
            raise MeetingAlreadyStartedException("Совещание уже идет")
        
        meeting = Meeting.create()
        meeting.start()
        await self.meeting_repository.save(meeting)
        self.logger.info(f"Совещание создано: ID={meeting.id}")
        
        # Начать запись (путь будет определен в UI)
        # Запись начнется с указанным путем из UI
        self.logger.info("Запись будет начата с путем из UI")
        
        return meeting
    
    async def stop_meeting(self) -> Meeting:
        """Остановить совещание"""
        self.logger.info("Запуск stop_meeting")
        meeting = await self.meeting_repository.get_current()
        if not meeting or meeting.status.value != "Recording":
            self.logger.warning("Попытка остановить совещание, которое не идет")
            raise MeetingNotStartedException("Совещание не идет")
        
        # Остановить запись
        self.logger.info("Остановка записи...")
        file_path = self.audio_recorder.stop_recording()
        self.logger.info(f"Запись остановлена, файл: {file_path}")
        
        # Создать запись
        import os
        file_size = os.path.getsize(file_path)
        duration = file_size / (44100 * 2 * 2)  # Примерная длительность
        self.logger.info(f"Размер файла: {file_size} байт, примерная длительность: {duration:.1f} сек")
        
        recording = MeetingRecording.create(
            meeting_id=meeting.id,
            file_path=file_path,
            duration_seconds=duration,
            file_size_bytes=file_size
        )
        await self.recording_repository.save(recording)
        self.logger.info(f"Запись сохранена: ID={recording.id}")
        
        meeting.stop()
        await self.meeting_repository.save(meeting)
        self.logger.info("Совещание остановлено")
        
        return meeting
    
    async def process_meeting(self, meeting_id: UUID, target_language: str, template_content: str = "") -> str:
        """Обработать запись совещания и сгенерировать отчет"""
        self.logger.info(f"Обработка совещания: ID={meeting_id}, язык={target_language}")
        meeting = await self.meeting_repository.get_by_id(meeting_id)
        if not meeting:
            self.logger.error(f"Совещание не найдено: ID={meeting_id}")
            raise MeetingNotStartedException("Совещание не найдено")
        
        if meeting.status.value != "Stopped":
            self.logger.warning(f"Совещание не остановлено: статус={meeting.status.value}")
            raise MeetingNotStoppedException("Совещание должно быть остановлено")
        
        meeting.mark_processing()
        await self.meeting_repository.save(meeting)
        self.logger.info("Совещание помечено как обрабатывается")
        
        # Получить запись
        recording = await self.recording_repository.get_by_meeting_id(meeting_id)
        if not recording:
            self.logger.error(f"Запись не найдена для совещания: ID={meeting_id}")
            raise MeetingNotStartedException("Запись не найдена")
        
        # Проверить размер файла и разбить на части если нужно
        audio_splitter = AudioSplitter()
        meeting_id_str = str(meeting_id)[:8]
        audio_files = audio_splitter.split_audio_file(recording.file_path, meeting_id_str)
        
        # Транскрибировать все части
        total_parts = len(audio_files)
        self.logger.info(f"Начало транскрипции аудио совещания ID={meeting_id_str}: {recording.file_path} ({total_parts} частей)")
        transcriptions = []
        
        for i, audio_file in enumerate(audio_files):
            part_num = i + 1
            self.logger.info(f"[Совещание ID={meeting_id_str}] Транскрипция части {part_num}/{total_parts}: {Path(audio_file).name}")
            part_transcription = await self.openai_client.transcribe_audio(audio_file)
            transcriptions.append(part_transcription)
            self.logger.info(f"[Совещание ID={meeting_id_str}] Часть {part_num}/{total_parts} транскрибирована, длина: {len(part_transcription)} символов")
            
            # Удалить временный файл части (если это не оригинальный файл)
            if audio_file != recording.file_path:
                try:
                    import os
                    os.remove(audio_file)
                    self.logger.debug(f"Удален временный файл части: {audio_file}")
                except Exception as e:
                    self.logger.warning(f"Не удалось удалить временный файл: {e}")
        
        # Объединить все транскрипции в хронологическом порядке
        if total_parts > 1:
            # Если несколько частей, добавить разделители для ясности
            transcription_parts = []
            for i, trans in enumerate(transcriptions):
                if i == 0:
                    transcription_parts.append(f"--- Часть {i+1} ---\n\n{trans}")
                else:
                    transcription_parts.append(f"\n\n--- Часть {i+1} ---\n\n{trans}")
            transcription = "".join(transcription_parts)
            self.logger.info(f"[Совещание ID={meeting_id_str}] Все {total_parts} частей транскрибированы и объединены в хронологическом порядке, общая длина: {len(transcription)} символов")
        else:
            transcription = transcriptions[0] if transcriptions else ""
            self.logger.info(f"[Совещание ID={meeting_id_str}] Транскрипция завершена, длина: {len(transcription)} символов")
        
        # Сгенерировать отчет
        template_len = len(template_content) if template_content else 0
        is_multipart = total_parts > 1
        self.logger.info(f"Генерация отчета на языке {target_language}, размер шаблона: {template_len} символов, частей: {total_parts}")
        report_content = await self.openai_client.generate_report(
            transcription=transcription,
            template=template_content,
            language=target_language,
            is_multipart=is_multipart
        )
        self.logger.info(f"Отчет сгенерирован, длина: {len(report_content)} символов")
        
        # Сохранить отчет
        report_path = self.storage_service.save_report(str(meeting_id), report_content)
        self.logger.info(f"Отчет сохранен: {report_path}")
        meeting.report_path = report_path
        meeting.mark_completed()
        await self.meeting_repository.save(meeting)
        self.logger.info("Обработка совещания завершена")
        
        return report_content

