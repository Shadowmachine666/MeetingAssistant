"""Статусы перевода"""
from enum import Enum


class TranslationStatus(str, Enum):
    """Статус перевода"""
    IDLE = "Idle"
    LISTENING = "Listening"
    PROCESSING = "Processing"
    COMPLETED = "Completed"
    ERROR = "Error"



