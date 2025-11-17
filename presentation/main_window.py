"""Главное окно приложения"""
import asyncio
import os
import sys
from pathlib import Path
from typing import Optional

# Добавить корневую директорию проекта в путь для импортов
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
import sounddevice as sd
import numpy as np
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTextEdit, QFileDialog, QComboBox, QSlider,
    QCheckBox, QMessageBox, QGroupBox
)

from application.services.meeting_service import MeetingService
from application.services.template_service import TemplateService
from application.services.translation_service import TranslationService
from core.logging.logger import get_logger
from domain.enums.audio_source_type import AudioSourceType
from domain.enums.language import Language
from domain.enums.meeting_status import MeetingStatus


class AsyncWorker(QThread):
    """Воркер для асинхронных операций"""
    finished = pyqtSignal(object)
    error = pyqtSignal(str)
    
    def __init__(self, coro):
        super().__init__()
        self.coro = coro
        self.loop = None
    
    def run(self):
        """Запустить асинхронную операцию"""
        try:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            result = self.loop.run_until_complete(self.coro)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))
        finally:
            if self.loop:
                try:
                    # Отменить все оставшиеся задачи
                    pending = asyncio.all_tasks(self.loop)
                    for task in pending:
                        task.cancel()
                    # Дождаться отмены задач
                    if pending:
                        self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                except Exception:
                    pass
                finally:
                    self.loop.close()
                    self.loop = None


class MainWindow(QMainWindow):
    """Главное окно приложения"""
    
    def __init__(self,
                 meeting_service: MeetingService,
                 translation_service: TranslationService,
                 template_service: TemplateService):
        super().__init__()
        self.meeting_service = meeting_service
        self.translation_service = translation_service
        self.template_service = template_service
        
        self.current_meeting = None
        self.current_template = None
        self.source_language = Language.RUSSIAN  # Язык оригинала
        self.target_language = Language.RUSSIAN  # Язык перевода
        self.workers = []  # Хранить ссылки на воркеры
        self.logger = get_logger()
        
        # Состояния записи для переводов
        self.is_recording_translation = False
        self.current_translation_source = None
        self.translation_recorder = None  # Будет создан при необходимости
        
        # Выбранные устройства
        self.selected_microphone_device = None  # Индекс устройства
        self.selected_stereo_mix_device = None  # Индекс устройства
        
        # Устройство записи совещания
        self.meeting_source_type = AudioSourceType.MICROPHONE
        self.meeting_device_index = None  # Индекс устройства для совещания
        
        # Таймер для мониторинга уровня звука
        self.audio_level_timer = QTimer()
        self.audio_level_timer.timeout.connect(self.check_audio_level)
        self.last_audio_level = 0.0
        
        # Папка для записей
        self.recordings_folder = "./Recordings"
        
        self.logger.info("Инициализация главного окна...")
        self.init_ui()
        self.setup_window_properties()
        self.logger.info("Главное окно инициализировано")
    
    def closeEvent(self, event):
        """Обработчик закрытия окна - завершить все потоки"""
        # Остановить запись перевода, если идет
        if self.is_recording_translation:
            self.logger.info("Остановка записи перевода при закрытии окна")
            try:
                self._stop_translation_recording()
            except Exception as e:
                self.logger.error(f"Ошибка при остановке записи: {e}")
        
        # Завершить все потоки
        for worker in self.workers[:]:  # Копия списка, так как он может изменяться
            if worker.isRunning():
                worker.quit()
                worker.wait(3000)  # Ждать до 3 секунд
        event.accept()
    
    def _remove_worker(self, worker):
        """Удалить воркер из списка"""
        if worker in self.workers:
            self.workers.remove(worker)
    
    def init_ui(self):
        """Инициализация UI"""
        self.setWindowTitle("MeetingAssistant")
        self.setMinimumSize(800, 600)
        
        # Центральный виджет
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        
        # Группа управления совещанием
        meeting_group = QGroupBox("Управление совещанием")
        meeting_layout = QVBoxLayout()
        
        # Кнопки совещания
        btn_layout = QHBoxLayout()
        self.btn_start_meeting = QPushButton("🔴 Записать совещание")
        self.btn_start_meeting.clicked.connect(self.start_meeting)
        self.btn_stop_meeting = QPushButton("⏹ Остановить запись")
        self.btn_stop_meeting.clicked.connect(self.stop_meeting)
        self.btn_stop_meeting.setEnabled(False)
        
        self.btn_load_template = QPushButton("Загрузить пример")
        self.btn_load_template.clicked.connect(self.load_template)
        
        self.btn_generate_report = QPushButton("📄 ОТЧЕТ")
        self.btn_generate_report.clicked.connect(self.generate_report)
        self.btn_generate_report.setEnabled(False)
        
        btn_layout.addWidget(self.btn_start_meeting)
        btn_layout.addWidget(self.btn_stop_meeting)
        btn_layout.addWidget(self.btn_load_template)
        btn_layout.addWidget(self.btn_generate_report)
        meeting_layout.addLayout(btn_layout)
        
        # Папка для сохранения
        folder_layout = QHBoxLayout()
        folder_layout.addWidget(QLabel("Папка записей:"))
        self.label_recordings_folder = QLabel("./Recordings")
        self.label_recordings_folder.setStyleSheet("border: 1px solid gray; padding: 3px;")
        folder_layout.addWidget(self.label_recordings_folder)
        self.btn_choose_folder = QPushButton("Выбрать папку")
        self.btn_choose_folder.clicked.connect(self.choose_recordings_folder)
        folder_layout.addWidget(self.btn_choose_folder)
        meeting_layout.addLayout(folder_layout)
        
        # Выбор устройства для записи совещания
        meeting_device_layout = QHBoxLayout()
        meeting_device_layout.addWidget(QLabel("Устройство записи:"))
        self.combo_meeting_source = QComboBox()
        self.combo_meeting_source.addItem("Микрофон", AudioSourceType.MICROPHONE)
        self.combo_meeting_source.addItem("Stereo Mix", AudioSourceType.STEREO_MIX)
        self.combo_meeting_source.setCurrentIndex(0)  # Микрофон по умолчанию
        self.combo_meeting_source.currentIndexChanged.connect(self.on_meeting_source_changed)
        meeting_device_layout.addWidget(self.combo_meeting_source)
        meeting_device_layout.addStretch()
        meeting_layout.addLayout(meeting_device_layout)
        
        # Статус совещания с таймером
        status_layout = QHBoxLayout()
        self.label_meeting_status = QLabel("Статус: Не начато")
        status_layout.addWidget(self.label_meeting_status)
        
        # Индикатор записи (красный круг)
        self.recording_indicator = QLabel("●")
        self.recording_indicator.setStyleSheet("color: gray; font-size: 20px;")
        self.recording_indicator.setVisible(False)
        status_layout.addWidget(self.recording_indicator)
        
        # Таймер записи
        self.label_recording_timer = QLabel("00:00:00")
        self.label_recording_timer.setStyleSheet("font-weight: bold; color: red;")
        self.label_recording_timer.setVisible(False)
        status_layout.addWidget(self.label_recording_timer)
        
        meeting_layout.addLayout(status_layout)
        
        # Таймер для обновления времени записи
        self.recording_timer = QTimer()
        self.recording_timer.timeout.connect(self.update_recording_timer)
        self.recording_start_time = None
        
        meeting_group.setLayout(meeting_layout)
        layout.addWidget(meeting_group)
        
        # Группа переводов
        translation_group = QGroupBox("Переводы в реальном времени")
        translation_layout = QVBoxLayout()
        
        # Выбор языков
        lang_layout = QHBoxLayout()
        lang_layout.addWidget(QLabel("Язык оригинала:"))
        self.combo_source_language = QComboBox()
        self.combo_source_language.addItems([lang.display_name for lang in Language])
        self.combo_source_language.setCurrentIndex(0)  # Русский по умолчанию
        self.combo_source_language.currentIndexChanged.connect(self.on_source_language_changed)
        lang_layout.addWidget(self.combo_source_language)
        
        lang_layout.addWidget(QLabel("→ Язык перевода:"))
        self.combo_target_language = QComboBox()
        self.combo_target_language.addItems([lang.display_name for lang in Language])
        self.combo_target_language.setCurrentIndex(2)  # English по умолчанию
        self.combo_target_language.currentIndexChanged.connect(self.on_target_language_changed)
        lang_layout.addWidget(self.combo_target_language)
        translation_layout.addLayout(lang_layout)
        
        # Выбор устройств
        device_layout = QHBoxLayout()
        device_layout.addWidget(QLabel("Микрофон:"))
        self.combo_microphone = QComboBox()
        self.combo_microphone.currentIndexChanged.connect(self.on_microphone_changed)
        device_layout.addWidget(self.combo_microphone)
        
        device_layout.addWidget(QLabel("Stereo Mix:"))
        self.combo_stereo_mix = QComboBox()
        self.combo_stereo_mix.currentIndexChanged.connect(self.on_stereo_mix_changed)
        device_layout.addWidget(self.combo_stereo_mix)
        translation_layout.addLayout(device_layout)
        
        # Загрузить список устройств
        self.load_audio_devices()
        
        # Кнопки переводов (toggle buttons)
        translate_btn_layout = QHBoxLayout()
        self.btn_listen_interlocutor = QPushButton("Выслушать собеседника")
        self.btn_listen_interlocutor.setCheckable(True)  # Toggle button
        self.btn_listen_interlocutor.toggled.connect(lambda checked: self.toggle_translation_recording(AudioSourceType.STEREO_MIX, checked))
        self.btn_listen_us = QPushButton("Выслушать нас")
        self.btn_listen_us.setCheckable(True)  # Toggle button
        self.btn_listen_us.toggled.connect(lambda checked: self.toggle_translation_recording(AudioSourceType.MICROPHONE, checked))
        
        translate_btn_layout.addWidget(self.btn_listen_interlocutor)
        translate_btn_layout.addWidget(self.btn_listen_us)
        translation_layout.addLayout(translate_btn_layout)
        
        # Статус записи перевода
        self.label_translation_status = QLabel("Статус: Не записывается")
        translation_layout.addWidget(self.label_translation_status)
        
        translation_group.setLayout(translation_layout)
        layout.addWidget(translation_group)
        
        # Окна текста
        text_layout = QHBoxLayout()
        
        # Оригинальный текст
        original_group = QGroupBox("Текст оригинала")
        original_layout = QVBoxLayout()
        self.text_original = QTextEdit()
        self.text_original.setReadOnly(True)
        # Настроить форматирование для жирного текста
        self.text_original.setAcceptRichText(True)
        original_layout.addWidget(self.text_original)
        original_group.setLayout(original_layout)
        text_layout.addWidget(original_group)
        
        # Переведенный текст
        translated_group = QGroupBox("Текст перевода")
        translated_layout = QVBoxLayout()
        self.text_translated = QTextEdit()
        self.text_translated.setReadOnly(True)
        # Настроить форматирование для жирного текста
        self.text_translated.setAcceptRichText(True)
        translated_layout.addWidget(self.text_translated)
        translated_group.setLayout(translated_layout)
        text_layout.addWidget(translated_group)
        
        layout.addLayout(text_layout)
        
        # Настройки окна
        settings_group = QGroupBox("Настройки окна")
        settings_layout = QVBoxLayout()
        
        # Прозрачность
        opacity_layout = QHBoxLayout()
        opacity_layout.addWidget(QLabel("Прозрачность:"))
        self.slider_opacity = QSlider(Qt.Orientation.Horizontal)
        self.slider_opacity.setMinimum(30)
        self.slider_opacity.setMaximum(100)
        self.slider_opacity.setValue(90)
        self.slider_opacity.valueChanged.connect(self.on_opacity_changed)
        opacity_layout.addWidget(self.slider_opacity)
        self.label_opacity = QLabel("90%")
        opacity_layout.addWidget(self.label_opacity)
        settings_layout.addLayout(opacity_layout)
        
        # Всегда поверх
        self.checkbox_always_on_top = QCheckBox("Поверх всех окон")
        self.checkbox_always_on_top.toggled.connect(self.on_always_on_top_changed)
        settings_layout.addWidget(self.checkbox_always_on_top)
        
        # Скрыть экран
        self.checkbox_hide_screen = QCheckBox("Спрятать экран")
        self.checkbox_hide_screen.toggled.connect(self.on_hide_screen_changed)
        settings_layout.addWidget(self.checkbox_hide_screen)
        
        settings_group.setLayout(settings_layout)
        layout.addWidget(settings_group)
    
    def setup_window_properties(self):
        """Настроить свойства окна"""
        self.setWindowOpacity(0.9)
        flags = self.windowFlags()
        # Можно добавить флаги для прозрачности и т.д.
    
    def on_source_language_changed(self, index: int):
        """Обработчик изменения языка оригинала"""
        self.source_language = list(Language)[index]
        self.logger.info(f"Язык оригинала изменен на: {self.source_language.display_name}")
    
    def on_target_language_changed(self, index: int):
        """Обработчик изменения языка перевода"""
        self.target_language = list(Language)[index]
        self.logger.info(f"Язык перевода изменен на: {self.target_language.display_name}")
    
    def on_meeting_source_changed(self, index: int):
        """Обработчик изменения источника записи совещания"""
        self.meeting_source_type = self.combo_meeting_source.itemData(index)
        # Определить индекс устройства
        if self.meeting_source_type == AudioSourceType.STEREO_MIX:
            self.meeting_device_index = self.selected_stereo_mix_device
        else:
            self.meeting_device_index = self.selected_microphone_device
        source_name = "Stereo Mix" if self.meeting_source_type == AudioSourceType.STEREO_MIX else "Микрофон"
        self.logger.info(f"Источник записи совещания изменен на: {source_name}")
    
    def load_audio_devices(self):
        """Загрузить список аудио устройств"""
        try:
            devices = sd.query_devices()
            
            # Загрузить микрофоны (исключая Stereo Mix)
            microphone_devices = []
            stereo_mix_devices = []
            
            for i, dev in enumerate(devices):
                if dev['max_input_channels'] > 0:
                    name_lower = dev['name'].lower()
                    if ('stereo mix' in name_lower or 
                        'what u hear' in name_lower or 
                        'miks stereo' in name_lower or
                        'wave out mix' in name_lower):
                        stereo_mix_devices.append((i, dev['name']))
                    else:
                        microphone_devices.append((i, dev['name']))
            
            # Заполнить комбобоксы
            self.combo_microphone.clear()
            for idx, name in microphone_devices:
                self.combo_microphone.addItem(name, idx)
                if self.selected_microphone_device is None:
                    self.selected_microphone_device = idx
            
            self.combo_stereo_mix.clear()
            for idx, name in stereo_mix_devices:
                self.combo_stereo_mix.addItem(name, idx)
                if self.selected_stereo_mix_device is None:
                    self.selected_stereo_mix_device = idx
            
            # Установить выбранные устройства
            if self.selected_microphone_device is not None:
                for i in range(self.combo_microphone.count()):
                    if self.combo_microphone.itemData(i) == self.selected_microphone_device:
                        self.combo_microphone.setCurrentIndex(i)
                        break
            
            if self.selected_stereo_mix_device is not None:
                for i in range(self.combo_stereo_mix.count()):
                    if self.combo_stereo_mix.itemData(i) == self.selected_stereo_mix_device:
                        self.combo_stereo_mix.setCurrentIndex(i)
                        break
            
            # Обновить индекс устройства для совещания
            if self.meeting_source_type == AudioSourceType.STEREO_MIX:
                self.meeting_device_index = self.selected_stereo_mix_device
            else:
                self.meeting_device_index = self.selected_microphone_device
            
            self.logger.info(f"Загружено микрофонов: {len(microphone_devices)}, Stereo Mix: {len(stereo_mix_devices)}")
            
        except Exception as e:
            self.logger.error(f"Ошибка загрузки устройств: {e}")
    
    def on_microphone_changed(self, index: int):
        """Обработчик изменения микрофона"""
        if index >= 0:
            device_idx = self.combo_microphone.itemData(index)
            if device_idx is not None:
                self.selected_microphone_device = device_idx
                device_info = sd.query_devices(device_idx)
                self.logger.info(f"Выбран микрофон: {device_info['name']} (индекс: {device_idx})")
                # Обновить индекс устройства для совещания, если используется микрофон
                if self.meeting_source_type == AudioSourceType.MICROPHONE:
                    self.meeting_device_index = device_idx
    
    def on_stereo_mix_changed(self, index: int):
        """Обработчик изменения Stereo Mix"""
        if index >= 0:
            device_idx = self.combo_stereo_mix.itemData(index)
            if device_idx is not None:
                self.selected_stereo_mix_device = device_idx
                device_info = sd.query_devices(device_idx)
                self.logger.info(f"Выбран Stereo Mix: {device_info['name']} (индекс: {device_idx})")
                # Обновить индекс устройства для совещания, если используется Stereo Mix
                if self.meeting_source_type == AudioSourceType.STEREO_MIX:
                    self.meeting_device_index = device_idx
    
    def check_audio_level(self):
        """Проверить уровень звука во время записи"""
        if not self.is_recording_translation or not self.translation_recorder:
            return
        
        try:
            # Использовать метод get_audio_level если доступен, иначе вычислять вручную
            if hasattr(self.translation_recorder, 'get_audio_level'):
                level = self.translation_recorder.get_audio_level()
            else:
                # Fallback - вычисление вручную
                if not hasattr(self.translation_recorder, 'recording_data') or not self.translation_recorder.recording_data:
                    source_name = "Stereo Mix" if self.current_translation_source == AudioSourceType.STEREO_MIX else "Микрофон"
                    self.logger.debug(f"Ожидание данных с {source_name}...")
                    return
                
                if len(self.translation_recorder.recording_data) > 0:
                    last_chunk = self.translation_recorder.recording_data[-1]
                    if last_chunk is not None and len(last_chunk) > 0:
                        rms = np.sqrt(np.mean(last_chunk.astype(np.float32) ** 2))
                        level = min(100, (rms / 32767.0) * 100)
                    else:
                        return
                else:
                    return
            
            source_name = "Stereo Mix" if self.current_translation_source == AudioSourceType.STEREO_MIX else "Микрофон"
            
            # Логировать всегда, но с разными уровнями
            if level < 1.0:
                # Очень тихо или нет звука
                if abs(level - self.last_audio_level) > 0.5:
                    self.last_audio_level = level
                    self.logger.warning(f"⚠ Уровень звука ({source_name}): {level:.2f}% - звук не обнаружен!")
            elif level < 5.0:
                # Тихий звук
                if abs(level - self.last_audio_level) > 1.0:
                    self.last_audio_level = level
                    self.logger.info(f"🔉 Уровень звука ({source_name}): {level:.1f}% - тихий звук")
            else:
                # Нормальный звук
                if abs(level - self.last_audio_level) > 5.0:
                    self.last_audio_level = level
                    self.logger.info(f"🔊 Уровень звука ({source_name}): {level:.1f}% - звук обнаружен")
        except Exception as e:
            self.logger.debug(f"Ошибка проверки уровня звука: {e}")
    
    def on_opacity_changed(self, value: int):
        """Обработчик изменения прозрачности"""
        opacity = value / 100.0
        self.setWindowOpacity(opacity)
        self.label_opacity.setText(f"{value}%")
    
    def on_always_on_top_changed(self, checked: bool):
        """Обработчик изменения 'всегда поверх'"""
        flags = self.windowFlags()
        if checked:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()
    
    def on_hide_screen_changed(self, checked: bool):
        """Обработчик скрытия экрана"""
        # В Windows можно использовать SetWindowDisplayAffinity
        # Для простоты пока просто минимизируем окно
        if checked:
            self.showMinimized()
        else:
            self.showNormal()
    
    def start_meeting(self):
        """Начать совещание"""
        self.logger.info("Запрос на начало совещания")
        
        # Защита от двойного клика - блокировать кнопку сразу
        if not self.btn_start_meeting.isEnabled():
            self.logger.warning("Попытка начать совещание при заблокированной кнопке")
            return
        
        self.btn_start_meeting.setEnabled(False)
        
        # Проверить конфликт устройств с записью перевода
        if self.is_recording_translation:
            # Определить устройство для совещания
            meeting_device_idx = None
            if self.meeting_source_type == AudioSourceType.STEREO_MIX:
                meeting_device_idx = self.selected_stereo_mix_device
            else:
                meeting_device_idx = self.selected_microphone_device
            
            # Определить устройство для перевода
            translation_device_idx = None
            if self.current_translation_source == AudioSourceType.STEREO_MIX:
                translation_device_idx = self.selected_stereo_mix_device
            else:
                translation_device_idx = self.selected_microphone_device
            
            # Проверить конфликт
            if meeting_device_idx == translation_device_idx:
                device_name = "Stereo Mix" if self.meeting_source_type == AudioSourceType.STEREO_MIX else "Микрофон"
                QMessageBox.warning(
                    self,
                    "Конфликт устройств",
                    f"Невозможно начать запись совещания с {device_name}:\n"
                    f"Это устройство уже используется для записи перевода.\n\n"
                    f"Остановите запись перевода или выберите другое устройство для совещания."
                )
                # Разблокировать кнопку при ошибке
                self.btn_start_meeting.setEnabled(True)
                return
        
        # Создать совещание и начать запись с указанной папкой
        async def start_meeting_with_path():
            meeting = await self.meeting_service.start_meeting()
            
            # Получить путь для записи с учетом выбранной папки
            from infrastructure.storage.storage_service import StorageService
            storage = StorageService()
            recording_path = storage.get_recording_path(str(meeting.id), self.recordings_folder)
            
            # Начать запись с выбранным устройством
            self.logger.info(f"Начало записи в файл: {recording_path}, устройство: {self.meeting_source_type.value}")
            self.meeting_service.audio_recorder.start_recording(
                recording_path, 
                source_type=self.meeting_source_type,
                device_index=self.meeting_device_index
            )
            meeting.recording_path = recording_path
            await self.meeting_service.meeting_repository.save(meeting)
            self.logger.info("Запись начата успешно")
            
            return meeting
        
        worker = AsyncWorker(start_meeting_with_path())
        worker.finished.connect(self.on_meeting_started)
        worker.finished.connect(lambda: self._remove_worker(worker))
        worker.error.connect(self.on_meeting_start_error)
        worker.error.connect(lambda: self._remove_worker(worker))
        self.workers.append(worker)
        worker.start()
    
    def on_meeting_start_error(self, error_message: str):
        """Обработчик ошибки начала совещания"""
        self.logger.error(f"Ошибка начала совещания: {error_message}")
        # Разблокировать кнопку при ошибке
        self.btn_start_meeting.setEnabled(True)
        self.on_error(error_message)
    
    def on_meeting_started(self, meeting):
        """Обработчик начала совещания"""
        self.logger.info(f"Совещание начато: ID={meeting.id}, время={meeting.start_time}")
        self.current_meeting = meeting
        self.btn_start_meeting.setEnabled(False)
        self.btn_stop_meeting.setEnabled(True)
        self.btn_generate_report.setEnabled(False)
        
        # Показать индикатор записи
        self.recording_indicator.setVisible(True)
        self.recording_indicator.setStyleSheet("color: red; font-size: 20px;")
        
        # Запустить таймер
        from datetime import datetime
        self.recording_start_time = datetime.now()
        self.recording_timer.start(1000)  # Обновлять каждую секунду
        self.update_recording_timer()
        
        self.label_meeting_status.setText(f"Статус: Запись идет (ID: {str(meeting.id)[:8]})")
    
    def stop_meeting(self):
        """Остановить совещание"""
        self.logger.info("Запрос на остановку совещания")
        worker = AsyncWorker(self.meeting_service.stop_meeting())
        worker.finished.connect(self.on_meeting_stopped)
        worker.finished.connect(lambda: self._remove_worker(worker))
        worker.error.connect(self.on_error)
        worker.error.connect(lambda: self._remove_worker(worker))
        self.workers.append(worker)
        worker.start()
    
    def on_meeting_stopped(self, meeting):
        """Обработчик остановки совещания"""
        duration = (meeting.end_time - meeting.start_time).total_seconds() if meeting.end_time else 0
        self.logger.info(f"Совещание остановлено: ID={meeting.id}, длительность={duration:.1f} сек")
        self.current_meeting = meeting
        self.btn_start_meeting.setEnabled(True)
        self.btn_stop_meeting.setEnabled(False)
        
        # Скрыть индикатор записи
        self.recording_indicator.setVisible(False)
        self.label_recording_timer.setVisible(False)
        self.recording_timer.stop()
        self.recording_start_time = None
        
        # Сбросить индекс устройства совещания
        self.meeting_device_index = None
        
        # Показать путь к файлу
        if meeting.recording_path:
            file_size = os.path.getsize(meeting.recording_path) / (1024 * 1024)  # MB
            self.label_meeting_status.setText(f"Статус: Остановлено | Файл: {Path(meeting.recording_path).name} ({file_size:.2f} MB)")
            self.logger.info(f"Запись сохранена: {meeting.recording_path} ({file_size:.2f} MB)")
        
        # Включить кнопку ОТЧЕТ
        self.btn_generate_report.setEnabled(True)
    
    def choose_recordings_folder(self):
        """Выбрать папку для сохранения записей"""
        from PyQt6.QtWidgets import QFileDialog
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку для записей", self.recordings_folder)
        if folder:
            self.recordings_folder = folder
            self.label_recordings_folder.setText(folder)
            self.logger.info(f"Выбрана папка для записей: {folder}")
    
    def update_recording_timer(self):
        """Обновить таймер записи"""
        if self.recording_start_time:
            from datetime import datetime
            elapsed = (datetime.now() - self.recording_start_time).total_seconds()
            hours = int(elapsed // 3600)
            minutes = int((elapsed % 3600) // 60)
            seconds = int(elapsed % 60)
            self.label_recording_timer.setText(f"{hours:02d}:{minutes:02d}:{seconds:02d}")
            self.label_recording_timer.setVisible(True)
    
    def generate_report(self):
        """Сгенерировать отчет (кнопка ОТЧЕТ)"""
        if not self.current_meeting:
            QMessageBox.warning(self, "Ошибка", "Нет активного совещания")
            return
        
        if not self.current_template:
            QMessageBox.warning(self, "Ошибка", "Не загружен шаблон отчета. Загрузите шаблон перед генерацией отчета.")
            return
        
        self.logger.info("Запрос на генерацию отчета")
        self.btn_generate_report.setEnabled(False)
        self.label_meeting_status.setText("Статус: Генерация отчета...")
        
        template_content = self.current_template.content
        
        worker = AsyncWorker(
            self.meeting_service.process_meeting(
                self.current_meeting.id,
                self.target_language.code,
                template_content
            )
        )
        worker.finished.connect(self.on_report_generated)
        worker.finished.connect(lambda: self._remove_worker(worker))
        worker.error.connect(self.on_error)
        worker.error.connect(lambda: self._remove_worker(worker))
        self.workers.append(worker)
        worker.start()
    
    def on_report_generated(self, report_content: str):
        """Обработчик генерации отчета"""
        self.logger.info(f"Отчет сгенерирован, длина: {len(report_content)} символов")
        
        # Получить путь к сохраненному отчету
        report_path = None
        if self.current_meeting and self.current_meeting.report_path:
            report_path = self.current_meeting.report_path
        
        # Определить язык отчета
        lang_name = self.target_language.display_name
        
        # Сформировать сообщение
        message = f"Отчет сгенерирован на языке: {lang_name}\n\n"
        if report_path:
            message += f"Путь к файлу:\n{report_path}\n\n"
        message += f"Превью отчета:\n{report_content[:200]}..."
        
        QMessageBox.information(self, "Отчет готов", message)
        self.label_meeting_status.setText(f"Статус: Завершено | Язык: {lang_name}")
        self.btn_generate_report.setEnabled(False)
    
    def load_template(self):
        """Загрузить шаблон"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите файл шаблона",
            "",
            "Текстовые файлы (*.txt);;Word документы (*.docx);;Все файлы (*.*)"
        )
        
        if file_path:
            worker = AsyncWorker(self.template_service.load_template(file_path))
            worker.finished.connect(self.on_template_loaded)
            worker.finished.connect(lambda: self._remove_worker(worker))
            worker.error.connect(self.on_error)
            worker.error.connect(lambda: self._remove_worker(worker))
            self.workers.append(worker)
            worker.start()
    
    def on_template_loaded(self, template):
        """Обработчик загрузки шаблона"""
        self.logger.info(f"Шаблон загружен: {template.file_path}, тип: {template.file_type}, размер: {len(template.content)} символов")
        self.current_template = template
        QMessageBox.information(self, "Шаблон загружен", f"Шаблон загружен из:\n{template.file_path}")
    
    def toggle_translation_recording(self, source_type: AudioSourceType, checked: bool):
        """Переключить запись для перевода"""
        source_name = "Stereo Mix" if source_type == AudioSourceType.STEREO_MIX else "Микрофон"
        
        if checked:
            # Проверить конфликт устройств с записью совещания
            if self.current_meeting and self.current_meeting.status.value == "Recording":
                # Определить устройство для перевода
                translation_device_idx = None
                if source_type == AudioSourceType.STEREO_MIX:
                    translation_device_idx = self.selected_stereo_mix_device
                else:
                    translation_device_idx = self.selected_microphone_device
                
                # Проверить конфликт
                if translation_device_idx == self.meeting_device_index:
                    device_name = "Stereo Mix" if source_type == AudioSourceType.STEREO_MIX else "Микрофон"
                    QMessageBox.warning(
                        self, 
                        "Конфликт устройств", 
                        f"Невозможно начать запись перевода с {device_name}:\n"
                        f"Это устройство уже используется для записи совещания.\n\n"
                        f"Выберите другое устройство или остановите запись совещания."
                    )
                    # Сбросить состояние кнопки
                    if source_type == AudioSourceType.STEREO_MIX:
                        self.btn_listen_interlocutor.setChecked(False)
                    else:
                        self.btn_listen_us.setChecked(False)
                    return
            
            # Начать запись
            if self.is_recording_translation:
                # Если уже идет запись с другого источника, остановить её
                self.logger.warning("Остановка предыдущей записи перевода")
                self._stop_translation_recording()
            
            self.logger.info(f"Начало записи для перевода с {source_name}")
            self.is_recording_translation = True
            self.current_translation_source = source_type
            
            # Создать отдельный рекордер для перевода
            from infrastructure.external_services.audio.audio_recorder import AudioRecorder
            import os
            self.translation_recorder = AudioRecorder(
                sample_rate=int(os.getenv("AUDIO_SAMPLE_RATE", "44100")),
                channels=int(os.getenv("AUDIO_CHANNELS", "2"))
            )
            
            # Определить устройство
            device_idx = None
            if source_type == AudioSourceType.STEREO_MIX:
                device_idx = self.selected_stereo_mix_device
            else:
                device_idx = self.selected_microphone_device
            
            # Начать запись во временный файл
            from infrastructure.storage.storage_service import StorageService
            storage = StorageService()
            temp_path = storage.get_temp_audio_path(f"translation_{source_type.value}")
            
            try:
                self.translation_recorder.start_recording(temp_path, source_type, device_idx)
                self.label_translation_status.setText(f"Статус: Запись с {source_name}...")
                
                # Запустить мониторинг уровня звука
                self.last_audio_level = 0.0
                self.audio_level_timer.start(1000)  # Проверять каждую секунду
                self.logger.info(f"Мониторинг уровня звука запущен для {source_name}")
                
                # Обновить текст кнопки
                if source_type == AudioSourceType.STEREO_MIX:
                    self.btn_listen_interlocutor.setText("⏹ Остановить запись")
                    self.btn_listen_us.setEnabled(False)
                else:
                    self.btn_listen_us.setText("⏹ Остановить запись")
                    self.btn_listen_interlocutor.setEnabled(False)
            except Exception as e:
                self.logger.error(f"Ошибка начала записи: {str(e)}")
                self.on_error(f"Ошибка начала записи: {str(e)}")
                self.is_recording_translation = False
                self.current_translation_source = None
                if source_type == AudioSourceType.STEREO_MIX:
                    self.btn_listen_interlocutor.setChecked(False)
                else:
                    self.btn_listen_us.setChecked(False)
        else:
            # Остановить запись и обработать
            if self.is_recording_translation and self.current_translation_source == source_type:
                self._stop_translation_recording()
    
    def _stop_translation_recording(self):
        """Остановить запись перевода и обработать"""
        if not self.is_recording_translation or not self.translation_recorder:
            return
        
        source_type = self.current_translation_source
        source_name = "Stereo Mix" if source_type == AudioSourceType.STEREO_MIX else "Микрофон"
        
        try:
            self.logger.info(f"Остановка записи для перевода с {source_name}")
            self.label_translation_status.setText("Статус: Обработка...")
            
            # Вычислить средний уровень звука перед остановкой
            try:
                avg_level = self.translation_recorder.get_audio_level()
                self.logger.info(f"Средний уровень звука за запись: {avg_level:.1f}%")
                if avg_level < 1.0:
                    self.logger.warning(f"⚠ ВНИМАНИЕ: Очень низкий уровень звука ({avg_level:.2f}%) - возможно устройство не работает или звук слишком тихий!")
            except Exception as e:
                self.logger.debug(f"Не удалось вычислить средний уровень: {e}")
            
            # Остановить запись
            file_path = self.translation_recorder.stop_recording()
            self.logger.info(f"Запись остановлена, файл: {file_path}")
            
            # Обработать запись
            worker = AsyncWorker(
                self.translation_service.translate_from_audio_file(
                    file_path=file_path,
                    source_type=source_type,
                    target_language=self.target_language,
                    source_language=self.source_language
                )
            )
            worker.finished.connect(self.on_translation_completed)
            worker.finished.connect(lambda: self._remove_worker(worker))
            worker.error.connect(self.on_error)
            worker.error.connect(lambda: self._remove_worker(worker))
            self.workers.append(worker)
            worker.start()
            
        except Exception as e:
            self.logger.error(f"Ошибка остановки записи: {str(e)}")
            self.on_error(f"Ошибка остановки записи: {str(e)}")
        finally:
            # Остановить мониторинг уровня звука
            self.audio_level_timer.stop()
            
            # Сбросить состояние
            self.is_recording_translation = False
            self.current_translation_source = None
            self.translation_recorder = None
            self.last_audio_level = 0.0
            
            # Обновить UI
            self.btn_listen_interlocutor.setText("Выслушать собеседника")
            self.btn_listen_us.setText("Выслушать нас")
            self.btn_listen_interlocutor.setEnabled(True)
            self.btn_listen_us.setEnabled(True)
            self.btn_listen_interlocutor.setChecked(False)
            self.btn_listen_us.setChecked(False)
            self.label_translation_status.setText("Статус: Не записывается")
    
    def on_translation_completed(self, result):
        """Обработчик завершения перевода"""
        self.logger.info(f"Перевод завершен: {len(result.original_text)} -> {len(result.translated_text)} символов")
        
        # Добавить текст в начало (сверху) с жирным шрифтом
        from datetime import datetime
        from html import escape
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # Экранировать HTML символы
        original_text_escaped = escape(result.original_text)
        translated_text_escaped = escape(result.translated_text)
        
        # Форматированный текст оригинала (жирный, с новой строки)
        # Используем <br> для новой строки и добавляем в начало
        original_html = f'<div style="font-weight: bold; margin: 5px 0;"><b>[{timestamp}]</b> {original_text_escaped}</div><br>'
        # Вставить в начало
        cursor = self.text_original.textCursor()
        cursor.movePosition(cursor.MoveOperation.Start)
        # Если уже есть текст, добавить разрыв перед новым
        if self.text_original.toPlainText().strip():
            cursor.insertHtml("<br>")
        cursor.insertHtml(original_html)
        
        # Форматированный текст перевода (жирный, с новой строки)
        translated_html = f'<div style="font-weight: bold; margin: 5px 0;"><b>[{timestamp}]</b> {translated_text_escaped}</div><br>'
        # Вставить в начало
        cursor = self.text_translated.textCursor()
        cursor.movePosition(cursor.MoveOperation.Start)
        # Если уже есть текст, добавить разрыв перед новым
        if self.text_translated.toPlainText().strip():
            cursor.insertHtml("<br>")
        cursor.insertHtml(translated_html)
    
    def on_error(self, error_message: str):
        """Обработчик ошибок"""
        self.logger.error(f"Ошибка: {error_message}", exc_info=True)
        QMessageBox.critical(self, "Ошибка", error_message)

