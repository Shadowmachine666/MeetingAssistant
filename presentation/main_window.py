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
        self.btn_start_meeting = QPushButton("Записать совещание")
        self.btn_start_meeting.clicked.connect(self.start_meeting)
        self.btn_stop_meeting = QPushButton("Остановить запись")
        self.btn_stop_meeting.clicked.connect(self.stop_meeting)
        self.btn_stop_meeting.setEnabled(False)
        
        self.btn_load_template = QPushButton("Загрузить пример")
        self.btn_load_template.clicked.connect(self.load_template)
        
        btn_layout.addWidget(self.btn_start_meeting)
        btn_layout.addWidget(self.btn_stop_meeting)
        btn_layout.addWidget(self.btn_load_template)
        meeting_layout.addLayout(btn_layout)
        
        # Статус совещания
        self.label_meeting_status = QLabel("Статус: Не начато")
        meeting_layout.addWidget(self.label_meeting_status)
        
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
        worker = AsyncWorker(self.meeting_service.start_meeting())
        worker.finished.connect(self.on_meeting_started)
        worker.finished.connect(lambda: self._remove_worker(worker))
        worker.error.connect(self.on_error)
        worker.error.connect(lambda: self._remove_worker(worker))
        self.workers.append(worker)
        worker.start()
    
    def on_meeting_started(self, meeting):
        """Обработчик начала совещания"""
        self.logger.info(f"Совещание начато: ID={meeting.id}, время={meeting.start_time}")
        self.current_meeting = meeting
        self.btn_start_meeting.setEnabled(False)
        self.btn_stop_meeting.setEnabled(True)
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
        self.label_meeting_status.setText("Статус: Остановлено")
        
        # Автоматически обработать запись
        if self.current_template:
            self.logger.info("Начало обработки записи совещания")
            self.process_meeting_recording()
        else:
            self.logger.warning("Шаблон не загружен, обработка записи пропущена")
    
    def process_meeting_recording(self):
        """Обработать запись совещания"""
        if not self.current_meeting:
            return
        
        template_content = ""
        if self.current_template:
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
        QMessageBox.information(self, "Отчет готов", f"Отчет сгенерирован:\n\n{report_content[:200]}...")
        self.label_meeting_status.setText("Статус: Завершено")
    
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
            
            # Начать запись во временный файл
            from infrastructure.storage.storage_service import StorageService
            storage = StorageService()
            temp_path = storage.get_temp_audio_path(f"translation_{source_type.value}")
            
            try:
                self.translation_recorder.start_recording(temp_path, source_type)
                self.label_translation_status.setText(f"Статус: Запись с {source_name}...")
                
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
            # Сбросить состояние
            self.is_recording_translation = False
            self.current_translation_source = None
            self.translation_recorder = None
            
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
        
        # Форматированный текст оригинала (жирный)
        original_html = f'<p style="font-weight: bold; margin: 5px 0;"><b>[{timestamp}]</b> {original_text_escaped}</p>'
        # Вставить в начало
        cursor = self.text_original.textCursor()
        cursor.movePosition(cursor.MoveOperation.Start)
        cursor.insertHtml(original_html)
        
        # Форматированный текст перевода (жирный)
        translated_html = f'<p style="font-weight: bold; margin: 5px 0;"><b>[{timestamp}]</b> {translated_text_escaped}</p>'
        # Вставить в начало
        cursor = self.text_translated.textCursor()
        cursor.movePosition(cursor.MoveOperation.Start)
        cursor.insertHtml(translated_html)
    
    def on_error(self, error_message: str):
        """Обработчик ошибок"""
        self.logger.error(f"Ошибка: {error_message}", exc_info=True)
        QMessageBox.critical(self, "Ошибка", error_message)

