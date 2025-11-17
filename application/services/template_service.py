"""Сервис шаблонов"""
from domain.entities.example_template import ExampleTemplate
from domain.interfaces.template_repository import ITemplateRepository
from infrastructure.file_system.file_parser import FileParserFactory


class TemplateService:
    """Сервис для работы с шаблонами"""
    
    def __init__(self,
                 template_repository: ITemplateRepository,
                 file_parser_factory: FileParserFactory):
        self.template_repository = template_repository
        self.file_parser_factory = file_parser_factory
    
    async def load_template(self, file_path: str) -> ExampleTemplate:
        """Загрузить шаблон из файла"""
        content = self.file_parser_factory.parse_file(file_path)
        template = ExampleTemplate.create(file_path, content)
        await self.template_repository.save(template)
        return template
    
    async def get_current_template(self):
        """Получить текущий шаблон"""
        from typing import Optional
        return await self.template_repository.get_current()

