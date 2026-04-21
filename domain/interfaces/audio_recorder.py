"""Аудио-рекордер (контракт).

Здесь описан минимальный контракт, который нужен `MeetingService` для управления записью.
Это позволяет подменять реализацию рекордера (например, запись микрофона + системного звука)
без изменения логики сервиса.
"""

from __future__ import annotations

from typing import Optional, Protocol


class IAudioRecorder(Protocol):
    """Протокол аудио-рекордера для записи в WAV."""

    sample_rate: int
    channels: int
    is_recording: bool

    def start_recording(self, output_path: str, **kwargs) -> None:
        """Начать запись в `output_path`.

        Реализация может принимать дополнительные параметры через `kwargs`.
        """

    def stop_recording(self) -> str:
        """Остановить запись и вернуть путь к сохраненному WAV."""

    def get_audio_level(self) -> float:
        """Вернуть текущий уровень звука (0-100)."""

