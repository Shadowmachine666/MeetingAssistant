"""Запись аудио"""
import os
import wave
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd

from core.exceptions.translation_exception import AudioCaptureException
from core.logging.logger import get_logger
from domain.enums.audio_source_type import AudioSourceType


class AudioRecorder:
    """Класс для записи аудио"""
    
    def __init__(self, sample_rate: int = 44100, channels: int = 2):
        self.sample_rate = sample_rate
        self.channels = channels
        self.is_recording = False
        self.recording_data: Optional[np.ndarray] = None
        self.recording_stream: Optional[sd.InputStream] = None
        self.output_path: Optional[str] = None
        self.logger = get_logger()
    
    def start_recording(self, output_path: str, source_type: AudioSourceType = AudioSourceType.MICROPHONE, device_index: Optional[int] = None) -> None:
        """Начать запись"""
        if self.is_recording:
            raise AudioCaptureException("Запись уже идет")
        
        # Создать директорию если не существует
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        
        self.output_path = output_path
        self.recording_data = []
        self.is_recording = True
        
        # Определить устройство ввода
        device = device_index  # Использовать переданное устройство
        
        if device is None:
            # Если устройство не указано, найти автоматически
            if source_type == AudioSourceType.STEREO_MIX:
                # Попытка найти Stereo Mix / Miks stereo
                devices = sd.query_devices()
                for i, dev in enumerate(devices):
                    name_lower = dev["name"].lower()
                    if ("stereo mix" in name_lower or 
                        "what u hear" in name_lower or 
                        "miks stereo" in name_lower):
                        device = i
                        break
            else:
                # Для микрофона - найти реальный микрофон (не Stereo Mix)
                devices = sd.query_devices()
                for i, dev in enumerate(devices):
                    if dev['max_input_channels'] > 0:
                        name_lower = dev["name"].lower()
                        # Исключаем Stereo Mix
                        if not ("stereo mix" in name_lower or 
                                "what u hear" in name_lower or 
                                "miks stereo" in name_lower or
                                "wave out mix" in name_lower):
                            device = i
                            break
                # Если не нашли, используем устройство по умолчанию
                if device is None:
                    try:
                        default_input = sd.query_devices(kind='input')
                        devices = sd.query_devices()
                        for i, dev in enumerate(devices):
                            if dev['name'] == default_input['name']:
                                device = i
                                break
                    except Exception:
                        pass
        
        # Логирование выбранного устройства
        if device is not None:
            device_info = sd.query_devices(device)
            self.logger.info(f"Выбрано устройство записи: {device_info['name']} (индекс: {device})")
        else:
            self.logger.warning("Устройство не выбрано, используется по умолчанию")
        
        def callback(indata, frames, time, status):
            if status:
                self.logger.warning(f"Audio status: {status}")
            if self.is_recording:
                self.recording_data.append(indata.copy())
        
        try:
            self.recording_stream = sd.InputStream(
                device=device,
                channels=self.channels,
                samplerate=self.sample_rate,
                callback=callback,
                dtype=np.int16
            )
            self.recording_stream.start()
            self.logger.info("Запись начата успешно")
        except Exception as e:
            self.is_recording = False
            raise AudioCaptureException(f"Ошибка начала записи: {str(e)}")
    
    def get_audio_level(self) -> float:
        """Получить текущий уровень звука (0-100)"""
        if not self.recording_data or len(self.recording_data) == 0:
            return 0.0
        
        try:
            # Объединить все фрагменты для вычисления среднего уровня
            all_data = np.concatenate(self.recording_data, axis=0)
            if len(all_data) == 0:
                return 0.0
            
            # Вычислить RMS
            rms = np.sqrt(np.mean(all_data.astype(np.float32) ** 2))
            # Нормализовать к диапазону 0-100
            level = min(100, (rms / 32767.0) * 100)
            return level
        except Exception:
            return 0.0
    
    def stop_recording(self) -> str:
        """Остановить запись и сохранить файл"""
        if not self.is_recording:
            raise AudioCaptureException("Запись не идет")
        
        self.is_recording = False
        
        if self.recording_stream:
            self.recording_stream.stop()
            self.recording_stream.close()
            self.recording_stream = None
        
        if not self.recording_data or len(self.recording_data) == 0:
            raise AudioCaptureException("Нет данных для сохранения")
        
        # Объединить все фрагменты
        audio_data = np.concatenate(self.recording_data, axis=0)
        
        # Нормализовать до int16
        if audio_data.dtype != np.int16:
            audio_data = (audio_data * 32767).astype(np.int16)
        
        # Сохранить в WAV файл
        try:
            with wave.open(self.output_path, 'wb') as wf:
                wf.setnchannels(self.channels)
                wf.setsampwidth(2)  # 16-bit = 2 bytes
                wf.setframerate(self.sample_rate)
                wf.writeframes(audio_data.tobytes())
        except Exception as e:
            raise AudioCaptureException(f"Ошибка сохранения файла: {str(e)}")
        
        file_path = self.output_path
        self.recording_data = None
        self.output_path = None
        
        return file_path
    
    def record_short_audio(self, duration_seconds: float, source_type: AudioSourceType = AudioSourceType.MICROPHONE) -> np.ndarray:
        """Записать короткий фрагмент аудио (для переводов) - устаревший метод"""
        device = None
        if source_type == AudioSourceType.STEREO_MIX:
            devices = sd.query_devices()
            for i, dev in enumerate(devices):
                name_lower = dev["name"].lower()
                if ("stereo mix" in name_lower or 
                    "what u hear" in name_lower or 
                    "miks stereo" in name_lower):
                    device = i
                    break
        
        try:
            recording = sd.rec(
                int(duration_seconds * self.sample_rate),
                samplerate=self.sample_rate,
                channels=self.channels,
                device=device,
                dtype=np.int16
            )
            sd.wait()  # Дождаться окончания записи
            return recording
        except Exception as e:
            raise AudioCaptureException(f"Ошибка записи аудио: {str(e)}")
    
    def save_audio_to_file(self, audio_data: np.ndarray, output_path: str) -> str:
        """Сохранить аудио данные в файл"""
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        
        # Нормализовать до int16
        if audio_data.dtype != np.int16:
            audio_data = (audio_data * 32767).astype(np.int16)
        
        try:
            with wave.open(output_path, 'wb') as wf:
                wf.setnchannels(self.channels)
                wf.setsampwidth(2)
                wf.setframerate(self.sample_rate)
                wf.writeframes(audio_data.tobytes())
        except Exception as e:
            raise AudioCaptureException(f"Ошибка сохранения файла: {str(e)}")
        
        return output_path



