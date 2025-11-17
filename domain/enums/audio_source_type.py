"""Типы источников аудио"""
from enum import Enum


class AudioSourceType(str, Enum):
    """Тип источника аудио"""
    MICROPHONE = "Microphone"
    STEREO_MIX = "StereoMix"



