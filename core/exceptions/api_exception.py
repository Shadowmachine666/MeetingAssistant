"""Исключения API"""


class ApiException(Exception):
    """Базовое исключение для API"""
    pass


class ApiKeyNotFoundException(ApiException):
    """API ключ не найден"""
    pass


class ApiRateLimitException(ApiException):
    """Превышен лимит запросов"""
    pass


class ApiRequestException(ApiException):
    """Ошибка запроса к API"""
    pass



