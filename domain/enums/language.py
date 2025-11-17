"""Языки"""
from enum import Enum


class Language(str, Enum):
    """Поддерживаемые языки"""
    RUSSIAN = "Russian"
    POLISH = "Polish"
    ENGLISH = "English"
    
    @property
    def code(self) -> str:
        """Код языка для API"""
        codes = {
            Language.RUSSIAN: "ru",
            Language.POLISH: "pl",
            Language.ENGLISH: "en"
        }
        return codes[self]
    
    @property
    def display_name(self) -> str:
        """Отображаемое имя"""
        names = {
            Language.RUSSIAN: "Русский",
            Language.POLISH: "Polski",
            Language.ENGLISH: "English"
        }
        return names[self]



