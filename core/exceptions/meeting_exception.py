"""Исключения совещаний"""


class MeetingException(Exception):
    """Базовое исключение для совещаний"""
    pass


class MeetingAlreadyStartedException(MeetingException):
    """Совещание уже начато"""
    pass


class MeetingNotStartedException(MeetingException):
    """Совещание не начато"""
    pass


class MeetingNotStoppedException(MeetingException):
    """Совещание не остановлено"""
    pass



