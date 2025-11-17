"""Результат перевода"""
from dataclasses import dataclass
from datetime import datetime

from domain.enums.language import Language


@dataclass
class TranslationResult:
    """Результат перевода"""
    original_text: str
    translated_text: str
    source_language: Language
    target_language: Language
    created_at: datetime
    
    @classmethod
    def create(cls, original_text: str, translated_text: str, 
               source_language: Language, target_language: Language) -> "TranslationResult":
        """Создать результат перевода"""
        return cls(
            original_text=original_text,
            translated_text=translated_text,
            source_language=source_language,
            target_language=target_language,
            created_at=datetime.now()
        )



