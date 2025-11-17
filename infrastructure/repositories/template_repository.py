"""Реализация репозитория шаблонов"""
from typing import Optional

from domain.entities.example_template import ExampleTemplate
from domain.interfaces.template_repository import ITemplateRepository


class TemplateRepository(ITemplateRepository):
    """Реализация репозитория шаблонов (in-memory)"""
    
    def __init__(self):
        self._current_template: Optional[ExampleTemplate] = None
    
    async def save(self, template: ExampleTemplate) -> None:
        """Сохранить шаблон"""
        self._current_template = template
    
    async def get_current(self) -> Optional[ExampleTemplate]:
        """Получить текущий загруженный шаблон"""
        return self._current_template



