"""Шаблон примера отчета"""
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4


@dataclass
class ExampleTemplate:
    """Шаблон примера отчета"""
    id: UUID
    file_path: str
    content: str
    file_type: str  # 'txt' или 'docx'
    loaded_at: datetime
    
    @classmethod
    def create(cls, file_path: str, content: str) -> "ExampleTemplate":
        """Создать шаблон из файла"""
        file_type = Path(file_path).suffix.lstrip('.').lower()
        return cls(
            id=uuid4(),
            file_path=file_path,
            content=content,
            file_type=file_type,
            loaded_at=datetime.now()
        )
    
    @property
    def exists(self) -> bool:
        """Проверить существование файла"""
        return Path(self.file_path).exists()



