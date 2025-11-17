"""Проверка готовности системы"""
import os
from typing import List, Tuple

import sounddevice as sd

from core.logging.logger import get_logger
from infrastructure.external_services.openai.openai_client import OpenAIClient

logger = get_logger()


class HealthCheckResult:
    """Результат проверки"""
    def __init__(self, name: str, status: bool, message: str, details: str = ""):
        self.name = name
        self.status = status
        self.message = message
        self.details = details
    
    def __str__(self):
        status_icon = "✓" if self.status else "✗"
        return f"{status_icon} {self.name}: {self.message}"


class HealthChecker:
    """Проверка готовности системы"""
    
    def __init__(self):
        self.logger = get_logger()
        self.results: List[HealthCheckResult] = []
    
    def check_all(self) -> List[HealthCheckResult]:
        """Выполнить все проверки"""
        self.logger.info("=" * 60)
        self.logger.info("Начало проверки готовности системы")
        self.logger.info("=" * 60)
        
        self.results = []
        
        # Проверки
        self._check_openai_api()
        self._check_microphone()
        self._check_stereo_mix()
        self._check_storage_directories()
        self._check_dependencies()
        
        # Итоги
        passed = sum(1 for r in self.results if r.status)
        total = len(self.results)
        
        self.logger.info("=" * 60)
        self.logger.info(f"Проверка завершена: {passed}/{total} проверок пройдено")
        self.logger.info("=" * 60)
        
        return self.results
    
    def _check_openai_api(self):
        """Проверка OpenAI API ключа"""
        self.logger.info("Проверка OpenAI API...")
        
        try:
            # Проверить наличие ключей
            api_keys = []
            for i in range(1, 4):
                key = os.getenv(f"OPENAI_API_KEY_{i}")
                if key:
                    api_keys.append(key)
            
            if not api_keys:
                key = os.getenv("OPENAI_API_KEY")
                if key:
                    api_keys.append(key)
            
            if not api_keys:
                result = HealthCheckResult(
                    "OpenAI API",
                    False,
                    "API ключ не найден",
                    "Создайте файл .env и добавьте OPENAI_API_KEY_1=sk-..."
                )
                self.results.append(result)
                self.logger.error(f"  {result}")
                return
            
            # Проверить валидность ключа (попытка создать клиент)
            try:
                client = OpenAIClient()
                result = HealthCheckResult(
                    "OpenAI API",
                    True,
                    f"API ключ найден ({len(api_keys)} ключ(ей))",
                    f"Модель: {client.model}, Транскрипция: {client.transcription_model}"
                )
                self.logger.info(f"  {result}")
            except Exception as e:
                result = HealthCheckResult(
                    "OpenAI API",
                    False,
                    "Ошибка инициализации клиента",
                    str(e)
                )
                self.logger.error(f"  {result}")
            
            self.results.append(result)
            
        except Exception as e:
            result = HealthCheckResult(
                "OpenAI API",
                False,
                "Ошибка проверки",
                str(e)
            )
            self.results.append(result)
            self.logger.error(f"  {result}")
    
    def _check_microphone(self):
        """Проверка микрофона (для записи нашего голоса)"""
        self.logger.info("Проверка микрофона...")
        
        try:
            devices = sd.query_devices()
            # Исключаем Stereo Mix из списка микрофонов
            input_devices = [
                d for d in devices 
                if d['max_input_channels'] > 0 
                and 'stereo mix' not in d['name'].lower()
                and 'miks stereo' not in d['name'].lower()
                and 'what u hear' not in d['name'].lower()
                and 'wave out mix' not in d['name'].lower()
            ]
            
            if not input_devices:
                result = HealthCheckResult(
                    "Микрофон",
                    False,
                    "Микрофон не найден",
                    "Подключите микрофон к системе (не Stereo Mix)"
                )
                self.results.append(result)
                self.logger.error(f"  {result}")
                return
            
            # Попытка получить устройство по умолчанию
            try:
                default_input = sd.query_devices(kind='input')
                # Если по умолчанию Stereo Mix, ищем другой микрофон
                if 'stereo mix' in default_input['name'].lower() or 'miks stereo' in default_input['name'].lower():
                    # Берем первый не-Stereo Mix микрофон
                    mic_device = input_devices[0] if input_devices else default_input
                else:
                    mic_device = default_input
                
                result = HealthCheckResult(
                    "Микрофон",
                    True,
                    f"Микрофон найден: {mic_device['name']}",
                    f"Доступно микрофонов: {len(input_devices)} (без Stereo Mix)"
                )
                self.logger.info(f"  {result}")
            except Exception as e:
                result = HealthCheckResult(
                    "Микрофон",
                    False,
                    "Ошибка доступа к микрофону",
                    str(e)
                )
                self.logger.error(f"  {result}")
            
            self.results.append(result)
            
        except Exception as e:
            result = HealthCheckResult(
                "Микрофон",
                False,
                "Ошибка проверки",
                str(e)
            )
            self.results.append(result)
            self.logger.error(f"  {result}")
    
    def _check_stereo_mix(self):
        """Проверка Stereo Mix (Miks stereo)"""
        self.logger.info("Проверка Stereo Mix...")
        
        try:
            devices = sd.query_devices()
            
            # Поиск Stereo Mix / Miks stereo
            stereo_mix_found = False
            stereo_mix_name = None
            
            for device in devices:
                name_lower = device['name'].lower()
                # Проверяем как устройства ввода (для записи системного звука)
                if device['max_input_channels'] > 0:
                    if ('stereo mix' in name_lower or 
                        'what u hear' in name_lower or 
                        'wave out mix' in name_lower or
                        'miks stereo' in name_lower):
                        stereo_mix_found = True
                        stereo_mix_name = device['name']
                        break
            
            if stereo_mix_found:
                result = HealthCheckResult(
                    "Stereo Mix",
                    True,
                    f"Stereo Mix найден: {stereo_mix_name}",
                    "Можно записывать звук системы (собеседника)"
                )
                self.logger.info(f"  {result}")
            else:
                result = HealthCheckResult(
                    "Stereo Mix",
                    False,
                    "Stereo Mix не найден",
                    "Включите Stereo Mix (Miks stereo) в настройках Windows: Звук → Устройства входа → Включить стерео микширование"
                )
                self.logger.warning(f"  {result}")
            
            self.results.append(result)
            
        except Exception as e:
            result = HealthCheckResult(
                "Stereo Mix",
                False,
                "Ошибка проверки",
                str(e)
            )
            self.results.append(result)
            self.logger.error(f"  {result}")
    
    def _check_storage_directories(self):
        """Проверка директорий для хранения"""
        self.logger.info("Проверка директорий...")
        
        try:
            from pathlib import Path
            
            directories = {
                "Recordings": os.getenv("STORAGE_RECORDINGS_PATH", "./Recordings"),
                "Reports": os.getenv("STORAGE_REPORTS_PATH", "./Reports"),
                "Templates": os.getenv("STORAGE_TEMPLATES_PATH", "./Templates"),
                "Logs": os.getenv("STORAGE_LOGS_PATH", "./Logs")
            }
            
            all_ok = True
            details = []
            
            for name, path in directories.items():
                dir_path = Path(path)
                try:
                    dir_path.mkdir(parents=True, exist_ok=True)
                    if dir_path.exists() and dir_path.is_dir():
                        details.append(f"{name}: {dir_path.absolute()}")
                    else:
                        all_ok = False
                        details.append(f"{name}: ОШИБКА создания")
                except Exception as e:
                    all_ok = False
                    details.append(f"{name}: {str(e)}")
            
            result = HealthCheckResult(
                "Директории",
                all_ok,
                "Все директории готовы" if all_ok else "Ошибка создания директорий",
                "; ".join(details)
            )
            
            if all_ok:
                self.logger.info(f"  {result}")
            else:
                self.logger.error(f"  {result}")
            
            self.results.append(result)
            
        except Exception as e:
            result = HealthCheckResult(
                "Директории",
                False,
                "Ошибка проверки",
                str(e)
            )
            self.results.append(result)
            self.logger.error(f"  {result}")
    
    def _check_dependencies(self):
        """Проверка зависимостей"""
        self.logger.info("Проверка зависимостей...")
        
        dependencies = {
            "PyQt6": "PyQt6",
            "sounddevice": "sounddevice",
            "numpy": "numpy",
            "openai": "openai",
            "python-docx": "docx",
            "aiohttp": "aiohttp",
            "python-dotenv": "dotenv"
        }
        
        all_ok = True
        details = []
        
        for name, module_name in dependencies.items():
            try:
                __import__(module_name)
                details.append(f"{name}: OK")
            except ImportError:
                all_ok = False
                details.append(f"{name}: НЕ УСТАНОВЛЕН")
        
        result = HealthCheckResult(
            "Зависимости",
            all_ok,
            "Все зависимости установлены" if all_ok else "Некоторые зависимости отсутствуют",
            "; ".join(details)
        )
        
        if all_ok:
            self.logger.info(f"  {result}")
        else:
            self.logger.error(f"  {result}")
        
        self.results.append(result)
    
    def get_summary(self) -> Tuple[int, int, bool]:
        """Получить сводку проверок"""
        passed = sum(1 for r in self.results if r.status)
        total = len(self.results)
        all_passed = passed == total
        return passed, total, all_passed

