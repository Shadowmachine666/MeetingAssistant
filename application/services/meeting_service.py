"""Сервис управления совещаниями"""
from uuid import UUID

from core.exceptions.meeting_exception import (
    MeetingAlreadyStartedException,
    MeetingNotStartedException,
    MeetingNotStoppedException
)
from domain.entities.meeting import Meeting
from domain.entities.meeting_recording import MeetingRecording
from domain.interfaces.meeting_repository import IMeetingRepository
from domain.interfaces.recording_repository import IRecordingRepository
from infrastructure.external_services.audio.audio_recorder import AudioRecorder
from infrastructure.external_services.openai.openai_client import OpenAIClient
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
    
    async def start_meeting(self) -> Meeting:
        """Начать совещание"""
        current = await self.meeting_repository.get_current()
        if current and current.status.value == "Recording":
            raise MeetingAlreadyStartedException("Совещание уже идет")
        
        meeting = Meeting.create()
        meeting.start()
        await self.meeting_repository.save(meeting)
        
        # Начать запись
        recording_path = self.storage_service.get_recording_path(str(meeting.id))
        self.audio_recorder.start_recording(recording_path)
        meeting.recording_path = recording_path
        
        return meeting
    
    async def stop_meeting(self) -> Meeting:
        """Остановить совещание"""
        meeting = await self.meeting_repository.get_current()
        if not meeting or meeting.status.value != "Recording":
            raise MeetingNotStartedException("Совещание не идет")
        
        # Остановить запись
        file_path = self.audio_recorder.stop_recording()
        
        # Создать запись
        import os
        file_size = os.path.getsize(file_path)
        duration = file_size / (44100 * 2 * 2)  # Примерная длительность
        
        recording = MeetingRecording.create(
            meeting_id=meeting.id,
            file_path=file_path,
            duration_seconds=duration,
            file_size_bytes=file_size
        )
        await self.recording_repository.save(recording)
        
        meeting.stop()
        await self.meeting_repository.save(meeting)
        
        return meeting
    
    async def process_meeting(self, meeting_id: UUID, target_language: str, template_content: str = "") -> str:
        """Обработать запись совещания и сгенерировать отчет"""
        meeting = await self.meeting_repository.get_by_id(meeting_id)
        if not meeting:
            raise MeetingNotStartedException("Совещание не найдено")
        
        if meeting.status.value != "Stopped":
            raise MeetingNotStoppedException("Совещание должно быть остановлено")
        
        meeting.mark_processing()
        await self.meeting_repository.save(meeting)
        
        # Получить запись
        recording = await self.recording_repository.get_by_meeting_id(meeting_id)
        if not recording:
            raise MeetingNotStartedException("Запись не найдена")
        
        # Транскрибировать
        transcription = await self.openai_client.transcribe_audio(recording.file_path)
        
        # Сгенерировать отчет
        report_content = await self.openai_client.generate_report(
            transcription=transcription,
            template=template_content,
            language=target_language
        )
        
        # Сохранить отчет
        report_path = self.storage_service.save_report(str(meeting_id), report_content)
        meeting.report_path = report_path
        meeting.mark_completed()
        await self.meeting_repository.save(meeting)
        
        return report_content

