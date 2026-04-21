"""Запись аудио совещания: микрофон + системный звук в один WAV.

Реализация ориентирована на Windows:
- основной способ захвата системного звука: WASAPI loopback
- запасной вариант: Stereo Mix (если включен в системе)

Выходной файл: WAV 16-bit PCM, стерео (2 канала) по умолчанию.
"""

from __future__ import annotations

import wave
from pathlib import Path
from threading import Lock
from typing import Optional

import numpy as np
import sounddevice as sd

from core.exceptions.translation_exception import AudioCaptureException
from core.logging.logger import get_logger


def _int16_to_float32(signal: np.ndarray) -> np.ndarray:
    """Преобразовать int16 PCM в float32 диапазона [-1; 1]."""
    return signal.astype(np.float32) / 32768.0


def _float32_to_int16(signal: np.ndarray) -> np.ndarray:
    """Преобразовать float32 [-1; 1] в int16 PCM с клиппингом."""
    clipped = np.clip(signal, -1.0, 1.0)
    return (clipped * 32767.0).astype(np.int16)


def mix_sources_to_stereo_int16(
    microphone_chunks: list[np.ndarray],
    system_chunks: list[np.ndarray],
    *,
    microphone_gain: float = 1.0,
    system_gain: float = 1.0,
) -> np.ndarray:
    """Свести два источника в один стерео int16 PCM сигнал.

    Args:
        microphone_chunks: Список фрагментов аудио с микрофона (int16), shape=(N, C).
        system_chunks: Список фрагментов системного звука (int16), shape=(N, C).
        microphone_gain: Множитель громкости микрофона перед смешиванием.
        system_gain: Множитель громкости системного звука перед смешиванием.

    Returns:
        np.ndarray: Стерео PCM int16, shape=(N, 2).
    """
    if not microphone_chunks and not system_chunks:
        return np.empty((0, 2), dtype=np.int16)

    mic = np.concatenate(microphone_chunks, axis=0) if microphone_chunks else np.empty((0, 1), dtype=np.int16)
    sys = np.concatenate(system_chunks, axis=0) if system_chunks else np.empty((0, 1), dtype=np.int16)

    if mic.ndim == 1:
        mic = mic.reshape(-1, 1)
    if sys.ndim == 1:
        sys = sys.reshape(-1, 1)

    # Привести к моно для смешивания: берем первый канал.
    mic_mono = mic[:, 0:1]
    sys_mono = sys[:, 0:1]

    max_len = max(mic_mono.shape[0], sys_mono.shape[0])
    if mic_mono.shape[0] < max_len:
        pad = np.zeros((max_len - mic_mono.shape[0], 1), dtype=np.int16)
        mic_mono = np.vstack([mic_mono, pad])
    if sys_mono.shape[0] < max_len:
        pad = np.zeros((max_len - sys_mono.shape[0], 1), dtype=np.int16)
        sys_mono = np.vstack([sys_mono, pad])

    mixed_float = (_int16_to_float32(mic_mono) * float(microphone_gain)) + (
        _int16_to_float32(sys_mono) * float(system_gain)
    )
    mixed_int16_mono = _float32_to_int16(mixed_float)

    # Дублировать в стерео
    return np.repeat(mixed_int16_mono, 2, axis=1)


class MeetingAudioRecorder:
    """Рекордер для совещаний (микрофон + системный звук) с сохранением в один WAV."""

    def __init__(
        self,
        *,
        sample_rate: int = 44100,
        channels: int = 2,
        microphone_gain: float = 1.0,
        system_gain: float = 1.0,
    ) -> None:
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
        self.microphone_gain = float(microphone_gain)
        self.system_gain = float(system_gain)

        self.is_recording = False
        self._output_path: Optional[str] = None

        self._mic_stream: Optional[sd.InputStream] = None
        self._sys_stream: Optional[sd.InputStream] = None

        self._mic_chunks: list[np.ndarray] = []
        self._sys_chunks: list[np.ndarray] = []

        self._mic_lock = Lock()
        self._sys_lock = Lock()
        self.logger = get_logger()

    def start_recording(
        self,
        output_path: str,
        *,
        microphone_device_index: Optional[int] = None,
        stereo_mix_device_index: Optional[int] = None,
        prefer_wasapi_loopback: bool = True,
    ) -> None:
        """Начать запись совещания.

        Args:
            output_path: Путь WAV файла результата.
            microphone_device_index: Индекс устройства микрофона (sounddevice).
            stereo_mix_device_index: Индекс входного устройства Stereo Mix (fallback).
            prefer_wasapi_loopback: Если True, пробовать WASAPI loopback для системного звука.
        """
        if self.is_recording:
            raise AudioCaptureException("Запись уже идет")

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        self._output_path = output_path
        self._mic_chunks = []
        self._sys_chunks = []
        self.is_recording = True

        def mic_callback(indata, frames, time, status):
            if status:
                self.logger.warning(f"Microphone status: {status}")
            if not self.is_recording:
                return
            with self._mic_lock:
                self._mic_chunks.append(indata.copy())

        def sys_callback(indata, frames, time, status):
            if status:
                self.logger.warning(f"System audio status: {status}")
            if not self.is_recording:
                return
            with self._sys_lock:
                self._sys_chunks.append(indata.copy())

        try:
            self._mic_stream = sd.InputStream(
                device=microphone_device_index,
                channels=1,
                samplerate=self.sample_rate,
                callback=mic_callback,
                dtype=np.int16,
            )
            self._mic_stream.start()
            mic_name = sd.query_devices(microphone_device_index)["name"] if microphone_device_index is not None else "default"
            self.logger.info(f"Запись микрофона начата: {mic_name}")
        except Exception as e:
            self.is_recording = False
            self._safe_close_streams()
            raise AudioCaptureException(f"Ошибка начала записи микрофона: {str(e)}")

        # Запись системного звука
        sys_started = False
        last_error: Optional[Exception] = None

        if prefer_wasapi_loopback:
            try:
                wasapi_settings = sd.WasapiSettings(loopback=True)
                default_output = sd.query_devices(kind="output")
                output_device_index = None
                devices = sd.query_devices()
                for i, dev in enumerate(devices):
                    if dev.get("name") == default_output.get("name"):
                        output_device_index = i
                        break

                self._sys_stream = sd.InputStream(
                    device=output_device_index,
                    channels=1,
                    samplerate=self.sample_rate,
                    callback=sys_callback,
                    dtype=np.int16,
                    extra_settings=wasapi_settings,
                )
                self._sys_stream.start()
                out_name = default_output.get("name", "default output")
                self.logger.info(f"Запись системного звука через WASAPI loopback начата: {out_name}")
                sys_started = True
            except Exception as e:
                last_error = e
                self.logger.warning(f"Не удалось запустить WASAPI loopback: {e}")

        if not sys_started:
            try:
                self._sys_stream = sd.InputStream(
                    device=stereo_mix_device_index,
                    channels=1,
                    samplerate=self.sample_rate,
                    callback=sys_callback,
                    dtype=np.int16,
                )
                self._sys_stream.start()
                sys_name = (
                    sd.query_devices(stereo_mix_device_index)["name"] if stereo_mix_device_index is not None else "default input"
                )
                self.logger.info(f"Запись системного звука через Stereo Mix начата: {sys_name}")
                sys_started = True
            except Exception as e:
                last_error = e

        if not sys_started:
            self.is_recording = False
            self._safe_close_streams()
            raise AudioCaptureException(
                "Не удалось начать запись системного звука. "
                "Проверьте поддержку WASAPI loopback и/или включите Stereo Mix в настройках Windows."
            ) from last_error

        self.logger.info("Запись совещания (микрофон + системный звук) начата успешно")

    def _safe_close_streams(self) -> None:
        """Остановить и закрыть потоки без выброса исключений."""
        for stream in (self._mic_stream, self._sys_stream):
            if stream is None:
                continue
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
        self._mic_stream = None
        self._sys_stream = None

    def stop_recording(self) -> str:
        """Остановить запись и сохранить итоговый WAV."""
        if not self.is_recording:
            raise AudioCaptureException("Запись не идет")
        if not self._output_path:
            raise AudioCaptureException("Не задан путь для сохранения")

        self.is_recording = False
        self._safe_close_streams()

        with self._mic_lock:
            mic_chunks = list(self._mic_chunks)
        with self._sys_lock:
            sys_chunks = list(self._sys_chunks)

        mixed = mix_sources_to_stereo_int16(
            mic_chunks,
            sys_chunks,
            microphone_gain=self.microphone_gain,
            system_gain=self.system_gain,
        )

        if mixed.size == 0:
            raise AudioCaptureException("Нет данных для сохранения")

        try:
            with wave.open(self._output_path, "wb") as wf:
                wf.setnchannels(2)
                wf.setsampwidth(2)
                wf.setframerate(self.sample_rate)
                wf.writeframes(mixed.tobytes())
        except Exception as e:
            raise AudioCaptureException(f"Ошибка сохранения файла: {str(e)}")

        file_path = self._output_path
        self._output_path = None
        self._mic_chunks = []
        self._sys_chunks = []
        return file_path

    def get_audio_level(self) -> float:
        """Получить текущий уровень звука (0-100) по микшированному потоку."""
        try:
            with self._mic_lock:
                mic_last = self._mic_chunks[-1] if self._mic_chunks else None
            with self._sys_lock:
                sys_last = self._sys_chunks[-1] if self._sys_chunks else None

            chunks_mic = [mic_last] if mic_last is not None else []
            chunks_sys = [sys_last] if sys_last is not None else []
            mixed = mix_sources_to_stereo_int16(chunks_mic, chunks_sys)
            if mixed.size == 0:
                return 0.0
            mono = mixed[:, 0].astype(np.float32)
            rms = float(np.sqrt(np.mean(mono * mono)))
            return min(100.0, (rms / 32767.0) * 100.0)
        except Exception:
            return 0.0

