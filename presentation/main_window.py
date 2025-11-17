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
        self.target_language = Language.RUSSIAN
        self.workers = []  # Хранить ссылки на воркеры
        
        self.init_ui()
        self.setup_window_properties()
    
    def closeEvent(self, event):
        """Обработчик закрытия окна - завершить все потоки"""
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
        
        # Выбор языка
        lang_layout = QHBoxLayout()
        lang_layout.addWidget(QLabel("Язык перевода:"))
        self.combo_language = QComboBox()
        self.combo_language.addItems([lang.display_name for lang in Language])
        self.combo_language.currentIndexChanged.connect(self.on_language_changed)
        lang_layout.addWidget(self.combo_language)
        translation_layout.addLayout(lang_layout)
        
        # Кнопки переводов
        translate_btn_layout = QHBoxLayout()
        self.btn_listen_interlocutor = QPushButton("Выслушать собеседника")
        self.btn_listen_interlocutor.clicked.connect(lambda: self.translate_audio(AudioSourceType.STEREO_MIX))
        self.btn_listen_us = QPushButton("Выслушать нас")
        self.btn_listen_us.clicked.connect(lambda: self.translate_audio(AudioSourceType.MICROPHONE))
        
        translate_btn_layout.addWidget(self.btn_listen_interlocutor)
        translate_btn_layout.addWidget(self.btn_listen_us)
        translation_layout.addLayout(translate_btn_layout)
        
        translation_group.setLayout(translation_layout)
        layout.addWidget(translation_group)
        
        # Окна текста
        text_layout = QHBoxLayout()
        
        # Оригинальный текст
        original_group = QGroupBox("Текст оригинала")
        original_layout = QVBoxLayout()
        self.text_original = QTextEdit()
        self.text_original.setReadOnly(True)
        original_layout.addWidget(self.text_original)
        original_group.setLayout(original_layout)
        text_layout.addWidget(original_group)
        
        # Переведенный текст
        translated_group = QGroupBox("Текст перевода")
        translated_layout = QVBoxLayout()
        self.text_translated = QTextEdit()
        self.text_translated.setReadOnly(True)
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
    
    def on_language_changed(self, index: int):
        """Обработчик изменения языка"""
        self.target_language = list(Language)[index]
    
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
        worker = AsyncWorker(self.meeting_service.start_meeting())
        worker.finished.connect(self.on_meeting_started)
        worker.finished.connect(lambda: self._remove_worker(worker))
        worker.error.connect(self.on_error)
        worker.error.connect(lambda: self._remove_worker(worker))
        self.workers.append(worker)
        worker.start()
    
    def on_meeting_started(self, meeting):
        """Обработчик начала совещания"""
        self.current_meeting = meeting
        self.btn_start_meeting.setEnabled(False)
        self.btn_stop_meeting.setEnabled(True)
        self.label_meeting_status.setText(f"Статус: Запись идет (ID: {str(meeting.id)[:8]})")
    
    def stop_meeting(self):
        """Остановить совещание"""
        worker = AsyncWorker(self.meeting_service.stop_meeting())
        worker.finished.connect(self.on_meeting_stopped)
        worker.finished.connect(lambda: self._remove_worker(worker))
        worker.error.connect(self.on_error)
        worker.error.connect(lambda: self._remove_worker(worker))
        self.workers.append(worker)
        worker.start()
    
    def on_meeting_stopped(self, meeting):
        """Обработчик остановки совещания"""
        self.current_meeting = meeting
        self.btn_start_meeting.setEnabled(True)
        self.btn_stop_meeting.setEnabled(False)
        self.label_meeting_status.setText("Статус: Остановлено")
        
        # Автоматически обработать запись
        if self.current_template:
            self.process_meeting_recording()
    
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
        self.current_template = template
        QMessageBox.information(self, "Шаблон загружен", f"Шаблон загружен из:\n{template.file_path}")
    
    def translate_audio(self, source_type: AudioSourceType):
        """Перевести аудио"""
        worker = AsyncWorker(
            self.translation_service.translate_from_audio(
                source_type=source_type,
                target_language=self.target_language,
                duration_seconds=5.0
            )
        )
        worker.finished.connect(self.on_translation_completed)
        worker.finished.connect(lambda: self._remove_worker(worker))
        worker.error.connect(self.on_error)
        worker.error.connect(lambda: self._remove_worker(worker))
        self.workers.append(worker)
        worker.start()
    
    def on_translation_completed(self, result):
        """Обработчик завершения перевода"""
        self.text_original.append(result.original_text)
        self.text_translated.append(result.translated_text)
    
    def on_error(self, error_message: str):
        """Обработчик ошибок"""
        QMessageBox.critical(self, "Ошибка", error_message)

