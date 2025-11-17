"""Исключения переводов"""


class TranslationException(Exception):
    """Базовое исключение для переводов"""
    pass


class TranslationFailedException(TranslationException):
    """Перевод не удался"""
    pass


class AudioCaptureException(TranslationException):
    """Ошибка захвата аудио"""
    pass



