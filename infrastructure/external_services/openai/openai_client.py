"""OpenAI API клиент"""
import asyncio
import os
from typing import List, Optional

import aiohttp
from dotenv import load_dotenv

from core.exceptions.api_exception import (
    ApiException,
    ApiKeyNotFoundException,
    ApiRateLimitException,
    ApiRequestException
)

load_dotenv()


class OpenAIClient:
    """Клиент для работы с OpenAI API"""
    
    def __init__(self):
        self.base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.model = os.getenv("OPENAI_MODEL", "gpt-4")
        self.transcription_model = os.getenv("OPENAI_TRANSCRIPTION_MODEL", "whisper-1")
        self.max_tokens = int(os.getenv("OPENAI_MAX_TOKENS", "4000"))
        self.temperature = float(os.getenv("OPENAI_TEMPERATURE", "0.7"))
        
        # Поддержка нескольких ключей для ротации
        self.api_keys: List[str] = []
        for i in range(1, 4):  # Поддержка до 3 ключей
            key = os.getenv(f"OPENAI_API_KEY_{i}")
            if key:
                self.api_keys.append(key)
        
        if not self.api_keys:
            key = os.getenv("OPENAI_API_KEY")
            if key:
                self.api_keys.append(key)
        
        if not self.api_keys:
            raise ApiKeyNotFoundException("OpenAI API ключ не найден в .env файле")
        
        self.current_key_index = 0
        self.retry_attempts = int(os.getenv("OPENAI_RETRY_ATTEMPTS", "3"))
        self.retry_delay_ms = int(os.getenv("OPENAI_RETRY_DELAY_MS", "1000"))
    
    def _get_current_key(self) -> str:
        """Получить текущий API ключ"""
        return self.api_keys[self.current_key_index]
    
    def _rotate_key(self) -> None:
        """Переключиться на следующий ключ"""
        self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
    
    async def _make_request(self, method: str, endpoint: str, **kwargs) -> dict:
        """Выполнить HTTP запрос с обработкой ошибок"""
        url = f"{self.base_url}/{endpoint}"
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self._get_current_key()}"
        
        for attempt in range(self.retry_attempts):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.request(method, url, headers=headers, **kwargs) as response:
                        if response.status == 429:  # Rate limit
                            if attempt < self.retry_attempts - 1:
                                self._rotate_key()
                                await asyncio.sleep(self.retry_delay_ms / 1000 * (attempt + 1))
                                continue
                            raise ApiRateLimitException("Превышен лимит запросов к OpenAI API")
                        
                        if response.status >= 400:
                            error_data = await response.json()
                            raise ApiRequestException(
                                f"Ошибка API: {error_data.get('error', {}).get('message', 'Unknown error')}"
                            )
                        
                        return await response.json()
            
            except aiohttp.ClientError as e:
                if attempt < self.retry_attempts - 1:
                    await asyncio.sleep(self.retry_delay_ms / 1000 * (attempt + 1))
                    continue
                raise ApiRequestException(f"Ошибка соединения: {str(e)}")
        
        raise ApiException("Не удалось выполнить запрос после всех попыток")
    
    async def transcribe_audio(self, audio_file_path: str, language: Optional[str] = None) -> str:
        """Транскрибировать аудио файл"""
        url = f"{self.base_url}/audio/transcriptions"
        
        for attempt in range(self.retry_attempts):
            try:
                headers = {"Authorization": f"Bearer {self._get_current_key()}"}
                
                data = aiohttp.FormData()
                data.add_field('model', self.transcription_model)
                if language:
                    data.add_field('language', language)
                
                # Читаем файл в память для повторных попыток
                with open(audio_file_path, "rb") as audio_file:
                    audio_data = audio_file.read()
                
                data.add_field('file', 
                              audio_data,
                              filename=os.path.basename(audio_file_path),
                              content_type='audio/wav')
                
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, headers=headers, data=data) as response:
                        if response.status == 429:
                            if attempt < self.retry_attempts - 1:
                                self._rotate_key()
                                await asyncio.sleep(self.retry_delay_ms / 1000 * (attempt + 1))
                                continue
                            raise ApiRateLimitException("Превышен лимит запросов к OpenAI API")
                        
                        if response.status >= 400:
                            error_data = await response.json()
                            raise ApiRequestException(
                                f"Ошибка API: {error_data.get('error', {}).get('message', 'Unknown error')}"
                            )
                        
                        result = await response.json()
                        return result.get("text", "")
            
            except aiohttp.ClientError as e:
                if attempt < self.retry_attempts - 1:
                    await asyncio.sleep(self.retry_delay_ms / 1000 * (attempt + 1))
                    continue
                raise ApiRequestException(f"Ошибка соединения: {str(e)}")
        
        raise ApiException("Не удалось выполнить запрос после всех попыток")
    
    async def translate_text(self, text: str, target_language: str, source_language: Optional[str] = None) -> str:
        """Перевести текст"""
        language_names = {
            "ru": "русский",
            "pl": "польский",
            "en": "английский"
        }
        
        target_lang_name = language_names.get(target_language, target_language)
        source_lang_name = language_names.get(source_language, "автоматически определяемый") if source_language else "автоматически определяемый"
        
        prompt = f"Переведи следующий текст с {source_lang_name} на {target_lang_name}. Переведи только текст, без дополнительных комментариев:\n\n{text}"
        
        response = await self._make_request(
            "POST",
            "chat/completions",
            json={
                "model": self.model,
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": self.max_tokens,
                "temperature": self.temperature
            }
        )
        
        return response["choices"][0]["message"]["content"].strip()
    
    async def generate_report(self, transcription: str, template: str, language: str) -> str:
        """Сгенерировать отчет на основе транскрипции и шаблона"""
        language_names = {
            "ru": "русском",
            "pl": "польском",
            "en": "английском"
        }
        
        lang_name = language_names.get(language, language)
        
        prompt = f"""На основе следующей транскрипции совещания и примера структуры отчета, создай полный отчет о совещании на {lang_name} языке.

Пример структуры отчета:
{template}

Транскрипция совещания:
{transcription}

Создай отчет, следуя структуре примера, но используя информацию из транскрипции."""
        
        response = await self._make_request(
            "POST",
            "chat/completions",
            json={
                "model": self.model,
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": self.max_tokens,
                "temperature": self.temperature
            }
        )
        
        return response["choices"][0]["message"]["content"].strip()

