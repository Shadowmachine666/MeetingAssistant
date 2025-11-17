"""Парсеры файлов"""
from abc import ABC, abstractmethod
from pathlib import Path


class IFileParser(ABC):
    """Интерфейс парсера файлов"""
    
    @abstractmethod
    def can_parse(self, file_path: str) -> bool:
        """Проверить, может ли парсер обработать файл"""
        pass
    
    @abstractmethod
    def parse(self, file_path: str) -> str:
        """Извлечь текст из файла"""
        pass


class TextFileParser(IFileParser):
    """Парсер текстовых файлов"""
    
    def can_parse(self, file_path: str) -> bool:
        """Проверить, является ли файл текстовым"""
        ext = Path(file_path).suffix.lower()
        return ext in ['.txt', '.md', '.log']
    
    def parse(self, file_path: str) -> str:
        """Прочитать текстовый файл"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except UnicodeDecodeError:
            # Попробовать другие кодировки
            for encoding in ['cp1251', 'latin-1']:
                try:
                    with open(file_path, 'r', encoding=encoding) as f:
                        return f.read()
                except UnicodeDecodeError:
                    continue
            raise ValueError(f"Не удалось прочитать файл {file_path}")


class WordFileParser(IFileParser):
    """Парсер Word документов"""
    
    def can_parse(self, file_path: str) -> bool:
        """Проверить, является ли файл Word документом"""
        ext = Path(file_path).suffix.lower()
        return ext in ['.docx']
    
    def parse(self, file_path: str) -> str:
        """Извлечь текст из Word документа"""
        try:
            from docx import Document
            doc = Document(file_path)
            paragraphs = [p.text for p in doc.paragraphs]
            return '\n'.join(paragraphs)
        except ImportError:
            raise ImportError("python-docx не установлен. Установите: pip install python-docx")
        except Exception as e:
            raise ValueError(f"Ошибка чтения Word файла: {str(e)}")


class FileParserFactory:
    """Фабрика парсеров файлов"""
    
    def __init__(self):
        self.parsers: list[IFileParser] = [
            TextFileParser(),
            WordFileParser()
        ]
    
    def get_parser(self, file_path: str) -> IFileParser:
        """Получить подходящий парсер для файла"""
        for parser in self.parsers:
            if parser.can_parse(file_path):
                return parser
        raise ValueError(f"Нет парсера для файла: {file_path}")
    
    def parse_file(self, file_path: str) -> str:
        """Извлечь текст из файла"""
        parser = self.get_parser(file_path)
        return parser.parse(file_path)



