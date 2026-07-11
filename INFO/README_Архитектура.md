# MeetingAssistant — Архитектура приложения

> Актуализировано под текущую реализацию (Python + PyQt6). Дата ревизии: 2026-07-11.
> Прежние версии этих документов описывали проектный вариант на C#/.NET/WPF, который
> в итоге НЕ реализован — фактическая программа написана на Python.

## Краткое описание

**MeetingAssistant** — десктопное приложение для Windows для работы во время
онлайн-встреч: запись совещаний (микрофон + системный звук в один WAV), генерация
структурированных отчётов через OpenAI и оффлайн-переводы речи.

## Основные возможности

1. **Запись совещаний** — одновременный захват микрофона и системного звука
   (WASAPI loopback), потоковая запись на диск, сведение в один стерео-WAV.
2. **Авто-стоп записи по таймеру** — автоматическая остановка через заданное время.
3. **Восстановитель записи** — пересборка WAV из аварийных сырых файлов `.pcm`.
4. **Генерация отчётов** — «транскрипт + шаблон-пример → GPT» на выбранном языке.
5. **Переводы** — запись фрагмента → транскрипция → перевод (собеседник / мы).
6. **Управление окном** — прозрачность, «поверх всех», скрытие из захвата экрана
   и панели задач.

> Примечание: транскрипция записи совещания выполняется **вне приложения**
> (пользователь прогоняет WAV в Google Colab и загружает готовый `.txt`).

## Архитектурные принципы

- **Clean Architecture** — разделение на слои `domain / application / infrastructure / core / presentation`.
- **Dependency Injection** — сборка графа зависимостей в `main.py::setup_dependencies()`.
- **Repository Pattern** — абстракция доступа к данным (интерфейсы в `domain/interfaces`).
- **Ports & Adapters** — доменные протоколы/ABC + инфраструктурные реализации.

## Структура слоёв (направление зависимостей)

```
Presentation (PyQt6 GUI: main_window.py)
    ↓ вызывает
Application (services: Meeting/Translation/Template/CostEstimator)
    ↓ зависит от
Domain (entities, interfaces, enums)  ← реализуется
    ↑
Infrastructure (audio, openai, repositories, storage, file_system)

Core (logging, exceptions, health) — кросс-слойная инфраструктура
```

## Технологический стек

| Назначение            | Технология                                   |
|-----------------------|----------------------------------------------|
| Язык                  | Python 3.x                                   |
| GUI                   | PyQt6                                         |
| Запись микрофона      | sounddevice (PortAudio)                       |
| Системный звук        | soundcard (WASAPI loopback)                   |
| Обработка звука       | numpy (PCM int16)                             |
| OpenAI API            | aiohttp (HTTP-запросы), пул ключей            |
| Парсинг шаблонов      | python-docx (.docx), встроенный парсер (.txt) |
| Конфигурация          | python-dotenv (`.env`)                        |
| Тесты                 | pytest                                        |

Полный список — в `requirements.txt`.

## Документация в этой папке

1. **[Архитектура.md](./Архитектура.md)** — детальное описание слоёв, классов и потоков данных.
2. **[Диаграммы_и_зависимости.md](./Диаграммы_и_зависимости.md)** — диаграммы зависимостей, последовательностей и состояний.
3. **[Структура_проекта.md](./Структура_проекта.md)** — дерево каталогов, файлы, рантайм-папки.
4. **[КАК_РАБОТАЕТ_ЗАПИСЬ_И_ВОССТАНОВЛЕНИЕ.txt](./КАК_РАБОТАЕТ_ЗАПИСЬ_И_ВОССТАНОВЛЕНИЕ.txt)** — памятка пользователя по записи и восстановлению.

## Ключевые компоненты

### Domain (`domain/`)
- **Entities**: `Meeting`, `MeetingRecording`, `MeetingReport`, `TranslationResult`, `ExampleTemplate`.
- **Interfaces**: `IAudioRecorder` (Protocol), `IMeetingRepository`, `IRecordingRepository`, `IReportRepository`, `ITemplateRepository` (ABC).
- **Enums**: `Language`, `MeetingStatus`, `AudioSourceType`, `TranslationStatus`.

### Application (`application/services/`)
- `MeetingService` — жизненный цикл совещания + генерация отчёта.
- `TranslationService` — аудио → транскрипт → перевод.
- `TemplateService` — загрузка шаблонов-примеров.
- `CostEstimatorService` — эвристическая оценка токенов OpenAI.

### Infrastructure (`infrastructure/`)
- **audio**: `MeetingAudioRecorder` (совещания), `AudioRecorder` (переводы), `LoopbackRecorder`.
- **openai**: `OpenAIClient`, `ApiKeyPool`.
- **repositories**: `MeetingRepository` (+JSON), `RecordingRepository`, `ReportRepository`, `TemplateRepository` (in-memory).
- **storage**: `StorageService`. **file_system**: `FileParserFactory`, `TextFileParser`, `WordFileParser`.

### Core (`core/`)
- **logging**: `AppLogger` / `get_logger()`. **exceptions**: доменные исключения.
- **health**: `HealthChecker` — проверки при старте (API-ключи, устройства, папки, зависимости).

### Presentation (`presentation/`)
- `MainWindow` — весь GUI. `AsyncWorker(QThread)` — фоновое выполнение корутин.
  `CollapsibleGroupBox` — сворачиваемые секции.

## Точка входа

`main.py` → `main()`: загрузка `.env` → health-check → `setup_dependencies()` →
восстановление «зависших» совещаний → `MainWindow` → `app.exec()`.
