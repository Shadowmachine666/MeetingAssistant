# MeetingAssistant

Десктопное приложение для Windows на Python для работы во время онлайн-встреч с поддержкой многоязычного перевода и автоматической генерации отчетов.

## Возможности

1. **Запись совещаний** с последующей обработкой через OpenAI API
2. **Перевод в реальном времени** (собеседник и мы)
3. **Генерация отчетов** на основе шаблонов
4. **Управление окном** (прозрачность, всегда поверх, скрытие экрана)

## Технологический стек

- **Python 3.10+**
- **PyQt6** - UI фреймворк
- **sounddevice** - работа с аудио
- **OpenAI API** - транскрипция, перевод, генерация отчетов
- **python-docx** - работа с Word документами

## Установка

1. Клонируйте репозиторий
2. Создайте виртуальное окружение:
```bash
python -m venv venv
venv\Scripts\activate  # Windows
```

3. Установите зависимости:
```bash
pip install -r requirements.txt
```

4. Скопируйте `config.env.example` в `.env` и заполните API ключи:
```bash
copy config.env.example .env
# Или вручную создайте .env файл и скопируйте содержимое из config.env.example
```

Откройте `.env` и добавьте ваш OpenAI API ключ:
```
OPENAI_API_KEY_1=sk-ваш-ключ-здесь
```

5. Запустите приложение:
```bash
python main.py
```

## Структура проекта

```
MeetingAssistant/
├── domain/          # Доменный слой (entities, enums, interfaces)
├── application/     # Слой приложения (use cases, services)
├── infrastructure/  # Инфраструктура (OpenAI, аудио, файлы)
├── presentation/    # UI слой (PyQt6 views, view models)
├── core/           # Общие утилиты
├── main.py         # Точка входа
└── requirements.txt
```

## Конфигурация

Настройки хранятся в `.env` файле. См. `.env.example` для примера.

## Лицензия

MIT

