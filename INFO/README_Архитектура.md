# MeetingAssistant - Архитектура приложения

## Краткое описание

MeetingAssistant - десктопное приложение для Windows, предназначенное для работы во время онлайн-встреч с поддержкой многоязычного перевода и автоматической генерации отчетов.

## Основные возможности

1. **Запись совещаний** с последующей обработкой через OpenAI API
2. **Перевод в реальном времени** (собеседник и мы)
3. **Генерация отчетов** на основе шаблонов
4. **Управление окном** (прозрачность, всегда поверх, скрытие экрана)

## Архитектурные принципы

- **Clean Architecture** - разделение на слои
- **SOLID** - принципы объектно-ориентированного проектирования
- **Repository Pattern** - абстракция доступа к данным
- **Dependency Injection** - управление зависимостями
- **MVVM** - разделение UI и бизнес-логики

## Структура слоев

```
Presentation (WPF UI)
    ↓
Application (Use Cases, Services)
    ↓
Domain (Entities, Interfaces)
    ↑
Infrastructure (Repositories, External APIs, File System)
```

## Технологический стек

- **.NET 8.0** - платформа
- **WPF** - UI фреймворк
- **NAudio** - работа с аудио
- **OpenAI API** - транскрипция, перевод, генерация отчетов
- **DocumentFormat.OpenXml** - работа с Word документами

## Документация

1. **[Архитектура.md](./Архитектура.md)** - детальное описание архитектуры
2. **[Диаграммы_и_зависимости.md](./Диаграммы_и_зависимости.md)** - диаграммы классов и зависимостей
3. **[Структура_проекта.md](./Структура_проекта.md)** - структура папок и файлов

## Ключевые компоненты

### Domain Layer
- Entities: Meeting, MeetingRecording, MeetingReport, TranslationRequest
- Interfaces: IMeetingRepository, IRecordingRepository, etc.
- Enums: Language, MeetingStatus, AudioSourceType

### Application Layer
- Use Cases: StartMeetingUseCase, StopMeetingUseCase, TranslateTextUseCase
- Services: IMeetingService, ITranslationService, IReportGenerationService

### Infrastructure Layer
- External Services: OpenAIClient, AudioRecorder, MicrophoneCaptureService
- Repositories: MeetingRepository, RecordingRepository, ReportRepository
- File System: FileService, TextFileParser, WordFileParser

### Presentation Layer
- ViewModels: MainViewModel, TranslationViewModel, ReportViewModel
- Views: MainWindow, OriginalTextControl, TranslatedTextControl
- Services: WindowService, DialogService

## Расширяемость

Архитектура позволяет легко добавлять:
- Новые языки
- Новые форматы файлов
- Новые источники аудио
- Новые провайдеры AI
- Новые типы отчетов
- Экспорт в различные форматы

## Следующие шаги

1. Создать Solution и проекты
2. Настроить зависимости и NuGet пакеты
3. Реализовать базовые классы
4. Настроить DI контейнер
5. Создать базовую структуру UI
6. Поэтапная реализация функциональности

