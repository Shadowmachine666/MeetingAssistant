"""Сервис переводов"""
import tempfile
from pathlib import Path

from core.logging.logger import get_logger
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
        self.logger = get_logger()
    
    async def translate_from_audio(self,
                                   source_type: AudioSourceType,
                                   target_language: Language,
                                   duration_seconds: float = 5.0,
                                   source_language: Language = None) -> TranslationResult:
        """Перевести аудио в реальном времени (устаревший метод, используйте translate_from_audio_file)"""
        # Записать короткий фрагмент
        audio_data = self.audio_recorder.record_short_audio(duration_seconds, source_type)
        
        # Сохранить во временный файл
        temp_path = self.storage_service.get_temp_audio_path("translation")
        self.audio_recorder.save_audio_to_file(audio_data, temp_path)
        
        return await self.translate_from_audio_file(temp_path, source_type, target_language, source_language)
    
    async def translate_from_audio_file(self,
                                       file_path: str,
                                       source_type: AudioSourceType,
                                       target_language: Language,
                                       source_language: Language = None) -> TranslationResult:
        """Перевести аудио из файла"""
        source_name = "Stereo Mix" if source_type == AudioSourceType.STEREO_MIX else "Микрофон"
        self.logger.info(f"Начало обработки перевода: файл={file_path}, источник={source_name}, язык={target_language.display_name}")
        
        try:
            # Транскрибировать
            source_lang_code = source_language.code if source_language else None
            self.logger.info("Транскрипция аудио...")
            original_text = await self.openai_client.transcribe_audio(file_path, source_lang_code)
            self.logger.info(f"Транскрипция завершена, длина: {len(original_text)} символов")
            
            # Перевести
            self.logger.info("Перевод текста...")
            translated_text = await self.openai_client.translate_text(
                text=original_text,
                target_language=target_language.code,
                source_language=source_lang_code
            )
            self.logger.info(f"Перевод завершен, длина: {len(translated_text)} символов")
            
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
                Path(file_path).unlink()
                self.logger.debug(f"Временный файл удален: {file_path}")
            except Exception as e:
                self.logger.warning(f"Не удалось удалить временный файл: {e}")



