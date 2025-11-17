"""Разбиение больших аудио файлов на части"""
import os
import wave
from pathlib import Path
from typing import List

from core.logging.logger import get_logger


class AudioSplitter:
    """Класс для разбиения больших аудио файлов"""
    
    # Лимит OpenAI: 25MB, делаем по 20MB для безопасности
    MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB
    
    def __init__(self):
        self.logger = get_logger()
    
    def split_audio_file(self, audio_file_path: str, meeting_id: str = None) -> List[str]:
        """Разбить аудио файл на части, если он слишком большой
        
        Args:
            audio_file_path: Путь к исходному аудио файлу
            meeting_id: ID совещания для включения в имена файлов частей
        """
        file_size = os.path.getsize(audio_file_path)
        self.logger.info(f"Размер файла: {file_size / (1024*1024):.2f} MB")
        
        if file_size <= self.MAX_FILE_SIZE_BYTES:
            self.logger.info("Файл не требует разбиения")
            return [audio_file_path]
        
        self.logger.info(f"Файл слишком большой ({file_size / (1024*1024):.2f} MB), разбиваем на части...")
        if meeting_id:
            self.logger.info(f"ID совещания для идентификации частей: {meeting_id[:8]}")
        
        # Читаем исходный файл
        with wave.open(audio_file_path, 'rb') as wf:
            params = wf.getparams()
            frames = wf.readframes(wf.getnframes())
        
        # Вычисляем размер одного фрейма в байтах
        frame_size = params.sampwidth * params.nchannels
        # Вычисляем количество фреймов на чанк (90% от лимита для безопасности)
        bytes_per_chunk = int(self.MAX_FILE_SIZE_BYTES * 0.9)
        frames_per_chunk = bytes_per_chunk // frame_size
        
        total_frames = params.nframes
        chunk_paths = []
        
        base_path = Path(audio_file_path)
        base_name = base_path.stem
        base_dir = base_path.parent
        
        # Включить ID совещания в имя файла части, если указан
        if meeting_id:
            meeting_prefix = f"{meeting_id[:8]}_"
        else:
            meeting_prefix = ""
        
        chunk_index = 0
        current_frame = 0
        
        while current_frame < total_frames:
            end_frame = min(current_frame + frames_per_chunk, total_frames)
            # Читаем нужное количество фреймов
            chunk_frames = frames[current_frame * frame_size:end_frame * frame_size]
            
            # Сохранить чанк с ID совещания в имени
            chunk_path = base_dir / f"{meeting_prefix}{base_name}_part{chunk_index + 1:03d}.wav"
            with wave.open(str(chunk_path), 'wb') as chunk_wf:
                chunk_wf.setparams(params)
                chunk_wf.writeframes(chunk_frames)
            
            chunk_size = os.path.getsize(chunk_path)
            # Вычислить общее количество частей
            total_chunks = (total_frames + frames_per_chunk - 1) // frames_per_chunk
            self.logger.info(f"Создан чанк {chunk_index + 1}/{total_chunks}: {chunk_path.name}, размер: {chunk_size / (1024*1024):.2f} MB")
            chunk_paths.append(str(chunk_path))
            
            current_frame = end_frame
            chunk_index += 1
        
        self.logger.info(f"Файл разбит на {len(chunk_paths)} частей (совещание ID: {meeting_id[:8] if meeting_id else 'не указан'})")
        return chunk_paths

