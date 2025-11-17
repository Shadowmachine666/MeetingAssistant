"""OpenAI API клиент"""
import asyncio
import os
from typing import Optional

import aiohttp
from dotenv import load_dotenv

from core.exceptions.api_exception import (
    ApiException,
    ApiKeyNotFoundException,
    ApiRateLimitException,
    ApiRequestException
)
from infrastructure.external_services.openai.api_key_pool import ApiKeyPool

load_dotenv()


class OpenAIClient:
    """Клиент для работы с OpenAI API с поддержкой пула ключей"""
    
    def __init__(self, api_key_pool: Optional[ApiKeyPool] = None):
        self.base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.model = os.getenv("OPENAI_MODEL", "gpt-4")
        self.transcription_model = os.getenv("OPENAI_TRANSCRIPTION_MODEL", "whisper-1")
        self.max_tokens = int(os.getenv("OPENAI_MAX_TOKENS", "4000"))
        self.temperature = float(os.getenv("OPENAI_TEMPERATURE", "0.7"))
        
        # Пул ключей для балансировки нагрузки
        self.api_key_pool = api_key_pool or ApiKeyPool()
        self.retry_attempts = int(os.getenv("OPENAI_RETRY_ATTEMPTS", "3"))
        self.retry_delay_ms = int(os.getenv("OPENAI_RETRY_DELAY_MS", "1000"))
        
        from core.logging.logger import get_logger
        self.logger = get_logger()
        self.logger.info(f"OpenAI клиент инициализирован с пулом из {self.api_key_pool.get_total_keys()} ключей")
    
    async def _make_request(self, method: str, endpoint: str, **kwargs) -> dict:
        """Выполнить HTTP запрос с обработкой ошибок и использованием пула ключей"""
        url = f"{self.base_url}/{endpoint}"
        
        # Попробовать с разными ключами из пула
        last_exception = None
        used_keys = set()
        
        for attempt in range(self.retry_attempts):
            try:
                # Получить доступный ключ из пула
                async with self.api_key_pool.acquire_key() as api_key:
                    # Проверить, не использовали ли мы этот ключ ранее в этой попытке
                    if api_key in used_keys:
                        # Если этот ключ уже использовался, освободим его и попробуем другой
                        await asyncio.sleep(self.retry_delay_ms / 1000 * (attempt + 1))
                        continue
                    
                    used_keys.add(api_key)
                    self.logger.debug(f"Использование ключа для запроса {endpoint}, попытка {attempt + 1}")
                    # Создать копию headers чтобы не изменять оригинальный kwargs
                    headers = dict(kwargs.get("headers", {}))
                    headers["Authorization"] = f"Bearer {api_key}"
                    # Обновить kwargs с новыми headers
                    kwargs_with_headers = {**kwargs, "headers": headers}
                    
                    async with aiohttp.ClientSession() as session:
                        async with session.request(method, url, **kwargs_with_headers) as response:
                            if response.status == 429:  # Rate limit
                                self.logger.warning(f"Rate limit на ключе, попытка {attempt + 1}/{self.retry_attempts}")
                                await self.api_key_pool.mark_key_failed(api_key, block_temporarily=True)
                                if attempt < self.retry_attempts - 1:
                                    await asyncio.sleep(self.retry_delay_ms / 1000 * (attempt + 1))
                                    continue
                                raise ApiRateLimitException("Превышен лимит запросов к OpenAI API")
                            
                            if response.status >= 400:
                                error_data = await response.json()
                                error_msg = error_data.get('error', {}).get('message', 'Unknown error')
                                self.logger.error(f"Ошибка API (статус {response.status}): {error_msg}")
                                await self.api_key_pool.mark_key_failed(api_key)
                                raise ApiRequestException(f"Ошибка API: {error_msg}")
                            
                            # Успешный запрос - разблокировать ключ если был заблокирован
                            await self.api_key_pool.unblock_key(api_key)
                            return await response.json()
            
            except (ApiRateLimitException, ApiRequestException) as e:
                last_exception = e
                if attempt < self.retry_attempts - 1:
                    await asyncio.sleep(self.retry_delay_ms / 1000 * (attempt + 1))
                    continue
                raise
            
            except aiohttp.ClientError as e:
                last_exception = ApiRequestException(f"Ошибка соединения: {str(e)}")
                if attempt < self.retry_attempts - 1:
                    await asyncio.sleep(self.retry_delay_ms / 1000 * (attempt + 1))
                    continue
                raise last_exception
        
        raise ApiException(f"Не удалось выполнить запрос после всех попыток: {last_exception}")
    
    async def transcribe_audio(self, audio_file_path: str, language: Optional[str] = None) -> str:
        """Транскрибировать аудио файл с использованием пула ключей"""
        url = f"{self.base_url}/audio/transcriptions"
        
        # Подготовить данные один раз
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
        
        # Попробовать с разными ключами из пула
        last_exception = None
        used_keys = set()
        
        for attempt in range(self.retry_attempts):
            try:
                # Получить доступный ключ из пула
                async with self.api_key_pool.acquire_key() as api_key:
                    # Проверить, не использовали ли мы этот ключ ранее в этой попытке
                    if api_key in used_keys:
                        # Если этот ключ уже использовался, освободим его и попробуем другой
                        await asyncio.sleep(self.retry_delay_ms / 1000 * (attempt + 1))
                        continue
                    
                    used_keys.add(api_key)
                    self.logger.debug(f"Использование ключа для транскрипции, попытка {attempt + 1}")
                    headers = {"Authorization": f"Bearer {api_key}"}
                    
                    async with aiohttp.ClientSession() as session:
                        async with session.post(url, headers=headers, data=data) as response:
                            if response.status == 429:
                                self.logger.warning(f"Rate limit при транскрипции, попытка {attempt + 1}/{self.retry_attempts}")
                                await self.api_key_pool.mark_key_failed(api_key, block_temporarily=True)
                                if attempt < self.retry_attempts - 1:
                                    await asyncio.sleep(self.retry_delay_ms / 1000 * (attempt + 1))
                                    continue
                                raise ApiRateLimitException("Превышен лимит запросов к OpenAI API")
                            
                            if response.status >= 400:
                                error_data = await response.json()
                                error_msg = error_data.get('error', {}).get('message', 'Unknown error')
                                self.logger.error(f"Ошибка транскрипции (статус {response.status}): {error_msg}")
                                await self.api_key_pool.mark_key_failed(api_key)
                                raise ApiRequestException(f"Ошибка API: {error_msg}")
                            
                            # Успешный запрос
                            await self.api_key_pool.unblock_key(api_key)
                            result = await response.json()
                            return result.get("text", "")
            
            except (ApiRateLimitException, ApiRequestException) as e:
                last_exception = e
                if attempt < self.retry_attempts - 1:
                    await asyncio.sleep(self.retry_delay_ms / 1000 * (attempt + 1))
                    continue
                raise
            
            except aiohttp.ClientError as e:
                last_exception = ApiRequestException(f"Ошибка соединения: {str(e)}")
                if attempt < self.retry_attempts - 1:
                    await asyncio.sleep(self.retry_delay_ms / 1000 * (attempt + 1))
                    continue
                raise last_exception
        
        raise ApiException(f"Не удалось выполнить транскрипцию после всех попыток: {last_exception}")
    
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
    
    async def generate_report(self, transcription: str, template: str, language: str, is_multipart: bool = False) -> str:
        """Сгенерировать отчет на основе транскрипции и шаблона
        
        Args:
            transcription: Транскрипция совещания
            template: Шаблон отчета
            language: Язык отчета (ru, pl, en)
            is_multipart: True, если транскрипция состоит из нескольких частей
        """
        language_names = {
            "ru": "русском",
            "pl": "польском",
            "en": "английском"
        }
        
        lang_name = language_names.get(language, language)
        
        # Добавить информацию о частях, если транскрипция разбита
        multipart_note = ""
        if is_multipart:
            multipart_note = "\n\nВАЖНО: Эта транскрипция состоит из нескольких частей одного совещания, объединенных в хронологическом порядке. Все части относятся к одному и тому же совещанию. Создай единый отчет, объединяющий информацию из всех частей."
        
        prompt = f"""На основе следующей транскрипции совещания и примера структуры отчета, создай полный отчет о совещании на {lang_name} языке.{multipart_note}

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

