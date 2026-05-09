"""Запись системного звука через WASAPI loopback (soundcard).

Используется для функции «Выслушать собеседника» в переводах:
loopback слушает именно то устройство вывода, куда сейчас играет звук
(BT-наушники, проводные наушники, встроенные колонки) — и не зависит
от наличия Stereo Mix у конкретной звуковой карты.
"""

from __future__ import annotations

import wave
from pathlib import Path
from threading import Lock, Thread
from typing import Optional

import numpy as np

from core.exceptions.translation_exception import AudioCaptureException
from core.logging.logger import get_logger


def _float32_to_int16(signal: np.ndarray) -> np.ndarray:
    clipped = np.clip(signal, -1.0, 1.0)
    return (clipped * 32767.0).astype(np.int16)


class LoopbackRecorder:
    """Запись loopback одного устройства вывода в WAV.

    API совместим с `AudioRecorder` в части, нужной UI: `start_recording`,
    `stop_recording`, `get_audio_level`, `is_recording`, `sample_rate`,
    `channels`. Лишние kwargs принимаются и игнорируются — чтобы UI
    мог звать одинаково.
    """

    def __init__(self, sample_rate: int = 44100, channels: int = 2) -> None:
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
        self.is_recording = False

        self._output_path: Optional[str] = None
        self._chunks: list[np.ndarray] = []
        self._lock = Lock()
        self._thread: Optional[Thread] = None
        self._thread_error: Optional[Exception] = None

        self.logger = get_logger()

    def start_recording(self, output_path: str, *,
                        system_output_name: Optional[str] = None,
                        **_ignored) -> None:
        """Начать loopback-запись с указанного устройства вывода.

        Если `system_output_name` не задан — используется устройство по умолчанию.
        """
        if self.is_recording:
            raise AudioCaptureException("Запись уже идёт")

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        self._output_path = output_path
        self._chunks = []
        self._thread_error = None
        self.is_recording = True

        try:
            import soundcard as sc  # type: ignore
        except Exception as e:
            self.is_recording = False
            raise AudioCaptureException(
                f"Не удалось импортировать soundcard для loopback: {e}"
            ) from e

        try:
            speaker_name = system_output_name or sc.default_speaker().name
            loopback_mic = sc.get_microphone(speaker_name, include_loopback=True)
            if loopback_mic is None:
                raise AudioCaptureException(
                    f"Не удалось открыть WASAPI loopback для устройства вывода: {speaker_name}"
                )
        except Exception as e:
            self.is_recording = False
            raise AudioCaptureException(f"Ошибка инициализации loopback: {e}") from e

        self.logger.info(f"Loopback-запись начата: {speaker_name}")

        def _run() -> None:
            try:
                blocksize = 1024
                with loopback_mic.recorder(samplerate=self.sample_rate, channels=1) as rec:
                    while self.is_recording:
                        data = rec.record(numframes=blocksize)
                        if data is None:
                            continue
                        arr = np.asarray(data, dtype=np.float32)
                        if arr.ndim == 1:
                            arr = arr.reshape(-1, 1)
                        int16_chunk = _float32_to_int16(arr)
                        with self._lock:
                            self._chunks.append(int16_chunk)
            except Exception as exc:
                self._thread_error = exc

        self._thread = Thread(target=_run, daemon=True)
        self._thread.start()

    def stop_recording(self) -> str:
        """Остановить запись и сохранить WAV."""
        if not self.is_recording:
            raise AudioCaptureException("Запись не идёт")
        if not self._output_path:
            raise AudioCaptureException("Не задан путь для сохранения")

        self.is_recording = False
        if self._thread is not None:
            try:
                self._thread.join(timeout=2.0)
            except Exception:
                pass

        if self._thread_error is not None:
            raise AudioCaptureException(
                f"Ошибка во время loopback-записи: {self._thread_error}"
            )

        with self._lock:
            chunks = list(self._chunks)

        if not chunks:
            raise AudioCaptureException("Нет данных для сохранения (loopback не дал звука)")

        mono = np.concatenate(chunks, axis=0)
        if mono.ndim == 1:
            mono = mono.reshape(-1, 1)
        # Дублируем в стерео (для совместимости с остальным пайплайном)
        stereo = np.repeat(mono[:, 0:1], 2, axis=1)

        try:
            with wave.open(self._output_path, "wb") as wf:
                wf.setnchannels(2)
                wf.setsampwidth(2)
                wf.setframerate(self.sample_rate)
                wf.writeframes(stereo.tobytes())
        except Exception as e:
            raise AudioCaptureException(f"Ошибка сохранения файла: {e}") from e

        file_path = self._output_path
        self._output_path = None
        self._chunks = []
        self._thread = None
        return file_path

    def get_audio_level(self) -> float:
        """Уровень звука 0..100 по последнему чанку."""
        try:
            with self._lock:
                last = self._chunks[-1] if self._chunks else None
            if last is None or last.size == 0:
                return 0.0
            mono = last[:, 0].astype(np.float32) if last.ndim > 1 else last.astype(np.float32)
            rms = float(np.sqrt(np.mean(mono * mono)))
            return min(100.0, (rms / 32767.0) * 100.0)
        except Exception:
            return 0.0
