"""Интерфейс репозитория шаблонов"""
from abc import ABC, abstractmethod
from typing import Optional

from domain.entities.example_template import ExampleTemplate


class ITemplateRepository(ABC):
    """Интерфейс для работы с шаблонами"""
    
    @abstractmethod
    async def save(self, template: ExampleTemplate) -> None:
        """Сохранить шаблон"""
        pass
    
    @abstractmethod
    async def get_current(self) -> Optional[ExampleTemplate]:
        """Получить текущий загруженный шаблон"""
        pass



