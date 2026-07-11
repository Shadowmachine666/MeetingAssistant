"""Запись аудио совещания: микрофон + системный звук в один WAV.

Реализация ориентирована на Windows:
- основной способ захвата системного звука: WASAPI loopback через библиотеку `soundcard`
  (на практике стабильнее и не зависит от наличия Stereo Mix)
- запасной вариант: входное устройство Stereo Mix (если включено в системе)

Выходной файл: WAV 16-bit PCM, стерео (2 канала) по умолчанию.
"""

from __future__ import annotations

import os
import wave
from pathlib import Path
from threading import Lock, Thread
from typing import BinaryIO, Optional

import numpy as np
import sounddevice as sd

from core.exceptions.translation_exception import AudioCaptureException
from core.logging.logger import get_logger

# Размер блока (в кадрах) для потокового сведения при остановке. Каждая запись в
# итоговый WAV не превышает ~4 МБ стерео — это исключает одиночную запись >2 ГБ,
# которая на Windows падает с [Errno 22] Invalid argument.
_MIX_BLOCK_FRAMES = 1_048_576

# Практический предел размера данных WAV (формат RIFF хранит размер в 32-битном
# поле, ~4.29 ГБ). Останавливаем дозапись немного раньше, чтобы файл гарантированно
# остался валидным и открывался.
_WAV_MAX_DATA_BYTES = 4_200_000_000


def _int16_to_float32(signal: np.ndarray) -> np.ndarray:
    """Преобразовать int16 PCM в float32 диапазона [-1; 1]."""
    return signal.astype(np.float32) / 32768.0


def _float32_to_int16(signal: np.ndarray) -> np.ndarray:
    """Преобразовать float32 [-1; 1] в int16 PCM с клиппингом."""
    clipped = np.clip(signal, -1.0, 1.0)
    return (clipped * 32767.0).astype(np.int16)


def mix_mono_blocks_to_stereo_int16(
    mic_mono: np.ndarray,
    sys_mono: np.ndarray,
    *,
    microphone_gain: float = 1.0,
    system_gain: float = 1.0,
) -> np.ndarray:
    """Свести два моно int16-блока в один стерео int16 PCM блок.

    Блоки выравниваются по длине дополнением тишиной (нулями). Это ядро
    смешивания, пригодное как для монолитной, так и для поблочной (потоковой)
    обработки — память ограничена размером переданных блоков.

    Args:
        mic_mono: Моно-блок микрофона (int16), shape=(N,) или (N, 1).
        sys_mono: Моно-блок системного звука (int16), shape=(M,) или (M, 1).
        microphone_gain: Множитель громкости микрофона перед смешиванием.
        system_gain: Множитель громкости системного звука перед смешиванием.

    Returns:
        np.ndarray: Стерео PCM int16, shape=(max(N, M), 2).
    """
    mic = mic_mono.reshape(-1, 1) if mic_mono.ndim == 1 else mic_mono[:, 0:1]
    sys = sys_mono.reshape(-1, 1) if sys_mono.ndim == 1 else sys_mono[:, 0:1]

    max_len = max(mic.shape[0], sys.shape[0])
    if max_len == 0:
        return np.empty((0, 2), dtype=np.int16)

    if mic.shape[0] < max_len:
        pad = np.zeros((max_len - mic.shape[0], 1), dtype=np.int16)
        mic = np.vstack([mic, pad])
    if sys.shape[0] < max_len:
        pad = np.zeros((max_len - sys.shape[0], 1), dtype=np.int16)
        sys = np.vstack([sys, pad])

    mixed_float = (_int16_to_float32(mic) * float(microphone_gain)) + (
        _int16_to_float32(sys) * float(system_gain)
    )
    mixed_int16_mono = _float32_to_int16(mixed_float)

    # Дублировать в стерео
    return np.repeat(mixed_int16_mono, 2, axis=1)


def mix_sources_to_stereo_int16(
    microphone_chunks: list[np.ndarray],
    system_chunks: list[np.ndarray],
    *,
    microphone_gain: float = 1.0,
    system_gain: float = 1.0,
) -> np.ndarray:
    """Свести два источника (списки фрагментов) в один стерео int16 PCM сигнал.

    Тонкая обёртка над :func:`mix_mono_blocks_to_stereo_int16`: конкатенирует
    фрагменты и приводит к моно (первый канал). Оставлена для обратной
    совместимости (используется тестами и индикатором уровня).

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

    return mix_mono_blocks_to_stereo_int16(
        mic[:, 0:1],
        sys[:, 0:1],
        microphone_gain=microphone_gain,
        system_gain=system_gain,
    )


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
        self._sys_thread: Optional[Thread] = None
        self._sys_thread_error: Optional[Exception] = None

        # Потоковая запись на диск: сырой int16 mono PCM пишется по мере поступления
        # в отдельные временные файлы (память не растёт), сведение — при остановке.
        self._mic_raw_path: Optional[str] = None
        self._sys_raw_path: Optional[str] = None
        self._mic_file: Optional[BinaryIO] = None
        self._sys_file: Optional[BinaryIO] = None

        # Последний блок каждого источника (только для индикатора уровня) — ограничено
        # одним блоком, всю запись в памяти больше не держим.
        self._mic_last: Optional[np.ndarray] = None
        self._sys_last: Optional[np.ndarray] = None

        self._mic_lock = Lock()
        self._sys_lock = Lock()
        self.logger = get_logger()

    def start_recording(
        self,
        output_path: str,
        *,
        capture_microphone: bool = True,
        capture_system_audio: bool = True,
        system_output_name: Optional[str] = None,
        microphone_device_index: Optional[int] = None,
        stereo_mix_device_index: Optional[int] = None,
        prefer_wasapi_loopback: bool = True,
    ) -> None:
        """Начать запись совещания.

        Args:
            output_path: Путь WAV файла результата.
            capture_microphone: Если True, писать микрофон.
            capture_system_audio: Если True, писать системный звук.
            system_output_name: Имя устройства вывода (speaker) для loopback (soundcard).
            microphone_device_index: Индекс устройства микрофона (sounddevice).
            stereo_mix_device_index: Индекс входного устройства Stereo Mix (fallback).
            prefer_wasapi_loopback: Если True, пробовать WASAPI loopback для системного звука.
        """
        if self.is_recording:
            raise AudioCaptureException("Запись уже идет")

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        self._output_path = output_path
        # Временные файлы сырого PCM рядом с итоговым WAV — при сбое сохранения
        # остаются на диске и позволяют восстановить запись.
        self._mic_raw_path = output_path + ".mic.pcm"
        self._sys_raw_path = output_path + ".sys.pcm"
        self._mic_file = open(self._mic_raw_path, "wb")
        self._sys_file = open(self._sys_raw_path, "wb")
        self._mic_last = None
        self._sys_last = None
        self.is_recording = True

        def mic_callback(indata, frames, time, status):
            if status:
                self.logger.warning(f"Microphone status: {status}")
            if not self.is_recording:
                return
            with self._mic_lock:
                if self._mic_file is not None:
                    self._mic_file.write(indata.tobytes())
                self._mic_last = indata.copy()

        def sys_callback(indata, frames, time, status):
            if status:
                self.logger.warning(f"System audio status: {status}")
            if not self.is_recording:
                return
            with self._sys_lock:
                if self._sys_file is not None:
                    self._sys_file.write(indata.tobytes())
                self._sys_last = indata.copy()

        if capture_microphone:
            try:
                self._mic_stream = sd.InputStream(
                    device=microphone_device_index,
                    channels=1,
                    samplerate=self.sample_rate,
                    callback=mic_callback,
                    dtype=np.int16,
                )
                self._mic_stream.start()
                mic_name = (
                    sd.query_devices(microphone_device_index)["name"]
                    if microphone_device_index is not None
                    else "default"
                )
                self.logger.info(f"Запись микрофона начата: {mic_name}")
            except Exception as e:
                self.is_recording = False
                self._safe_close_streams()
                self._safe_close_raw_files()
                raise AudioCaptureException(f"Ошибка начала записи микрофона: {str(e)}")
        else:
            self.logger.info("Запись микрофона отключена (capture_microphone=False)")

        # Запись системного звука
        sys_started = False
        last_error: Optional[Exception] = None

        if capture_system_audio and prefer_wasapi_loopback:
            try:
                import soundcard as sc  # type: ignore

                self._sys_thread_error = None

                def _run_soundcard_loopback() -> None:
                    try:
                        speaker_name = system_output_name or sc.default_speaker().name
                        loopback_mic = sc.get_microphone(speaker_name, include_loopback=True)
                        if loopback_mic is None:
                            raise AudioCaptureException(
                                f"Не удалось открыть WASAPI loopback для устройства вывода: {speaker_name}"
                            )

                        self.logger.info(
                            f"Запись системного звука через WASAPI loopback (soundcard) начата: {loopback_mic.name}"
                        )
                        blocksize = 1024
                        with loopback_mic.recorder(samplerate=self.sample_rate, channels=1) as rec:
                            while self.is_recording:
                                data = rec.record(numframes=blocksize)
                                if data is None:
                                    continue
                                # soundcard -> float32 [-1; 1], shape (N, C)
                                arr = np.asarray(data, dtype=np.float32)
                                if arr.ndim == 1:
                                    arr = arr.reshape(-1, 1)
                                int16_chunk = _float32_to_int16(arr)
                                with self._sys_lock:
                                    if self._sys_file is not None:
                                        self._sys_file.write(int16_chunk.tobytes())
                                    self._sys_last = int16_chunk
                    except Exception as e:  # pragma: no cover (device/runtime dependent)
                        self._sys_thread_error = e
                        self.logger.error(f"Системный звук (loopback) прерван ошибкой: {e}", exc_info=True)

                self._sys_thread = Thread(target=_run_soundcard_loopback, daemon=True)
                self._sys_thread.start()
                sys_started = True
            except Exception as e:
                last_error = e
                self.logger.warning(f"Не удалось запустить WASAPI loopback: {e}")

        if capture_system_audio and not sys_started:
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

        if capture_system_audio and not sys_started:
            self.is_recording = False
            self._safe_close_streams()
            self._safe_close_raw_files()
            raise AudioCaptureException(
                "Не удалось начать запись системного звука. "
                "Проверьте поддержку WASAPI loopback и/или включите Stereo Mix в настройках Windows."
            ) from last_error
        if not capture_system_audio:
            self.logger.info("Запись системного звука отключена (capture_system_audio=False)")

        if capture_microphone and capture_system_audio:
            self.logger.info("Запись совещания (микрофон + системный звук) начата успешно")
        elif capture_microphone:
            self.logger.info("Запись совещания (только микрофон) начата успешно")
        elif capture_system_audio:
            self.logger.info("Запись совещания (только системный звук) начата успешно")
        else:
            self.logger.warning("Запись совещания начата без источников (оба отключены)")

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

    def _safe_close_raw_files(self) -> None:
        """Дописать и закрыть временные PCM-файлы без выброса исключений."""
        for attr in ("_mic_file", "_sys_file"):
            f = getattr(self, attr)
            if f is None:
                continue
            try:
                f.flush()
            except Exception:
                pass
            try:
                f.close()
            except Exception:
                pass
            setattr(self, attr, None)

    def _remove_raw_files(self) -> None:
        """Удалить временные PCM-файлы (после успешного сохранения)."""
        for attr in ("_mic_raw_path", "_sys_raw_path"):
            path = getattr(self, attr)
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass
            setattr(self, attr, None)

    def _reset_state_after_stop(self) -> None:
        """Сбросить рабочее состояние рекордера после остановки."""
        self._output_path = None
        self._mic_last = None
        self._sys_last = None
        self._sys_thread = None
        self._sys_thread_error = None

    def _stream_mix_to_wav(self, output_path: str, mic_raw: Optional[str], sys_raw: Optional[str]) -> bool:
        """Свести два сырых int16-mono PCM файла в стерео WAV поблочно.

        Память ограничена одним блоком; каждая запись в WAV не превышает ~4 МБ,
        что исключает одиночную запись >2 ГБ (Errno 22 на Windows).

        Returns:
            bool: True, если запись усечена по достижении предела размера WAV.
        """
        itemsize = np.dtype(np.int16).itemsize  # 2 байта
        block_bytes = _MIX_BLOCK_FRAMES * itemsize
        written_data_bytes = 0
        truncated = False

        mic_f = open(mic_raw, "rb") if mic_raw and os.path.exists(mic_raw) else None
        sys_f = open(sys_raw, "rb") if sys_raw and os.path.exists(sys_raw) else None
        try:
            with wave.open(output_path, "wb") as wf:
                wf.setnchannels(2)
                wf.setsampwidth(2)
                wf.setframerate(self.sample_rate)
                while True:
                    mic_bytes = mic_f.read(block_bytes) if mic_f is not None else b""
                    sys_bytes = sys_f.read(block_bytes) if sys_f is not None else b""
                    if not mic_bytes and not sys_bytes:
                        break

                    mic_block = np.frombuffer(mic_bytes, dtype=np.int16)
                    sys_block = np.frombuffer(sys_bytes, dtype=np.int16)
                    mixed = mix_mono_blocks_to_stereo_int16(
                        mic_block,
                        sys_block,
                        microphone_gain=self.microphone_gain,
                        system_gain=self.system_gain,
                    )
                    if mixed.size == 0:
                        continue

                    data = mixed.tobytes()
                    if written_data_bytes + len(data) > _WAV_MAX_DATA_BYTES:
                        # Оставить место так, чтобы файл остался валидным; выровнять
                        # по стерео-кадру (4 байта).
                        allowed = _WAV_MAX_DATA_BYTES - written_data_bytes
                        allowed -= allowed % 4
                        if allowed > 0:
                            wf.writeframes(data[:allowed])
                            written_data_bytes += allowed
                        truncated = True
                        break

                    wf.writeframes(data)
                    written_data_bytes += len(data)
        finally:
            if mic_f is not None:
                mic_f.close()
            if sys_f is not None:
                sys_f.close()

        return truncated

    def stop_recording(self) -> str:
        """Остановить запись и сохранить итоговый WAV (потоковое сведение)."""
        if not self.is_recording:
            raise AudioCaptureException("Запись не идет")
        if not self._output_path:
            raise AudioCaptureException("Не задан путь для сохранения")

        self.is_recording = False

        # Дать loopback-потоку корректно завершиться
        if self._sys_thread is not None:
            try:
                self._sys_thread.join(timeout=2.0)
            except Exception:
                pass

        # Остановить аудио-потоки (после этого callbacks не вызываются), затем
        # безопасно закрыть временные PCM-файлы.
        sys_thread_error = self._sys_thread_error
        self._safe_close_streams()
        self._safe_close_raw_files()

        if sys_thread_error is not None:
            self.logger.warning(f"Системный звук (loopback) завершился с ошибкой: {sys_thread_error}")

        output_path = self._output_path
        mic_raw = self._mic_raw_path
        sys_raw = self._sys_raw_path

        mic_size = os.path.getsize(mic_raw) if mic_raw and os.path.exists(mic_raw) else 0
        sys_size = os.path.getsize(sys_raw) if sys_raw and os.path.exists(sys_raw) else 0
        if mic_size == 0 and sys_size == 0:
            self._remove_raw_files()
            self._reset_state_after_stop()
            raise AudioCaptureException("Нет данных для сохранения")

        try:
            truncated = self._stream_mix_to_wav(output_path, mic_raw, sys_raw)
        except Exception as e:
            # НЕ удаляем сырые файлы — данные восстановимы вручную.
            self._reset_state_after_stop()
            raise AudioCaptureException(
                f"Ошибка сохранения файла: {str(e)}. "
                f"Сырые данные сохранены и восстановимы: {mic_raw}, {sys_raw}"
            )

        if truncated:
            self.logger.warning(
                "Достигнут предел размера WAV (~4 ГБ). Запись сохранена не полностью; "
                f"полные сырые данные оставлены для восстановления: {mic_raw}, {sys_raw}"
            )
        else:
            self._remove_raw_files()

        self._reset_state_after_stop()
        return output_path

    def get_audio_level(self) -> float:
        """Получить текущий уровень звука (0-100) по микшированному потоку."""
        try:
            with self._mic_lock:
                mic_last = self._mic_last
            with self._sys_lock:
                sys_last = self._sys_last

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

