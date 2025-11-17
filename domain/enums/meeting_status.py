"""Статусы совещания"""
from enum import Enum


class MeetingStatus(str, Enum):
    """Статус совещания"""
    NOT_STARTED = "NotStarted"
    RECORDING = "Recording"
    STOPPED = "Stopped"
    PROCESSING = "Processing"
    COMPLETED = "Completed"



