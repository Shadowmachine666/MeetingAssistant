"""Сервис переводов"""
import tempfile
from pathlib import Path

from domain.entities.translation_result import TranslationResult
from domain.enums.audio_source_type import AudioSourceType
from domain.enums.language import Language
from infrastructure.external_services.audio.audio_recorder import AudioRecorder
from infrastructure.external_services.openai.openai_client import OpenAIClient
from infrastructure.storage.storage_service import StorageService


class TranslationService:
    """Сервис для переводов в реальном времени"""
    
    def __init__(self,
                 audio_recorder: AudioRecorder,
                 openai_client: OpenAIClient,
                 storage_service: StorageService):
        self.audio_recorder = audio_recorder
        self.openai_client = openai_client
        self.storage_service = storage_service
    
    async def translate_from_audio(self,
                                   source_type: AudioSourceType,
                                   target_language: Language,
                                   duration_seconds: float = 5.0,
                                   source_language: Language = None) -> TranslationResult:
        """Перевести аудио в реальном времени"""
        # Записать короткий фрагмент
        audio_data = self.audio_recorder.record_short_audio(duration_seconds, source_type)
        
        # Сохранить во временный файл
        temp_path = self.storage_service.get_temp_audio_path("translation")
        self.audio_recorder.save_audio_to_file(audio_data, temp_path)
        
        try:
            # Транскрибировать
            source_lang_code = source_language.code if source_language else None
            original_text = await self.openai_client.transcribe_audio(temp_path, source_lang_code)
            
            # Перевести
            translated_text = await self.openai_client.translate_text(
                text=original_text,
                target_language=target_language.code,
                source_language=source_lang_code
            )
            
            # Определить исходный язык (если не указан)
            if not source_language:
                # Упрощенная логика - можно улучшить через API
                source_language = Language.ENGLISH  # По умолчанию
            
            return TranslationResult.create(
                original_text=original_text,
                translated_text=translated_text,
                source_language=source_language,
                target_language=target_language
            )
        finally:
            # Удалить временный файл
            try:
                Path(temp_path).unlink()
            except Exception:
                pass



