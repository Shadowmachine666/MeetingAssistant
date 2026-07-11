"""Главное окно приложения"""
import asyncio
import ctypes
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
    QCheckBox, QMessageBox, QGroupBox, QSizePolicy
)

# Константы Windows API для скрытия окна от захвата экрана
WDA_EXCLUDEFROMCAPTURE = 0x00000011
WDA_NONE = 0x00000000

# Константы Windows API для скрытия окна из панели задач
GWL_EXSTYLE = -20  # Индекс для расширенных стилей окна
WS_EX_TOOLWINDOW = 0x00000080  # Скрывает окно из панели задач и Alt+Tab

from application.services.meeting_service import MeetingService
from application.services.template_service import TemplateService
from application.services.translation_service import TranslationService
from core.logging.logger import get_logger
from domain.enums.audio_source_type import AudioSourceType
from domain.enums.language import Language
from domain.enums.meeting_status import MeetingStatus


class CollapsibleGroupBox(QWidget):
    """Сворачиваемая группа с кнопкой-стрелкой"""
    
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.is_collapsed = False
        self.content_widget = None
        self.content_layout = None
        
        # Главный layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Заголовок с кнопкой
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(5, 5, 5, 5)
        
        # Кнопка-стрелка
        self.toggle_button = QPushButton("▼")
        self.toggle_button.setFixedSize(20, 20)
        self.toggle_button.setFlat(True)
        self.toggle_button.setStyleSheet("""
            QPushButton {
                border: none;
                background-color: transparent;
                color: #333333;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
                border-radius: 3px;
            }
        """)
        self.toggle_button.clicked.connect(self.toggle_collapse)
        header_layout.addWidget(self.toggle_button)
        
        # Заголовок
        title_label = QLabel(title)
        title_label.setStyleSheet("font-weight: bold; color: #333333; border: none;")  # Темный текст, без рамки
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        
        # Стиль для заголовка
        header_widget.setStyleSheet("""
            QWidget {
                border: 2px solid #cccccc;
                border-radius: 5px;
                background-color: #f0f0f0;
            }
        """)
        
        main_layout.addWidget(header_widget)
        
        # Виджет для содержимого
        self.content_widget = QWidget()
        self.content_widget.setStyleSheet("""
            QWidget {
                border: 2px solid #cccccc;
                border-top: none;
                border-radius: 0 0 5px 5px;
            }
        """)
        main_layout.addWidget(self.content_widget)
    
    def setLayout(self, layout):
        """Установить layout для содержимого"""
        self.content_layout = layout
        self.content_widget.setLayout(layout)
    
    def toggle_collapse(self):
        """Переключить состояние сворачивания"""
        self.is_collapsed = not self.is_collapsed
        
        if self.is_collapsed:
            self.content_widget.setVisible(False)
            self.toggle_button.setText("▶")
        else:
            self.content_widget.setVisible(True)
            self.toggle_button.setText("▼")
        
        # Обновить размер
        self.adjustSize()
        if self.parent():
            self.parent().adjustSize()


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
        self.current_transcript_text: Optional[str] = None
        self.current_transcript_path: Optional[str] = None
        # Языки для переводов (отдельные для каждого источника)
        self.stereo_mix_source_language = Language.RUSSIAN  # Язык оригинала для "Выслушать собеседника"
        self.stereo_mix_target_language = Language.ENGLISH  # Язык перевода для "Выслушать собеседника"
        self.microphone_source_language = Language.RUSSIAN  # Язык оригинала для "Выслушать нас"
        self.microphone_target_language = Language.ENGLISH  # Язык перевода для "Выслушать нас"
        self.report_language = Language.RUSSIAN  # Язык отчета
        self.workers = []  # Хранить ссылки на воркеры
        self.logger = get_logger()
        
        # Состояния записи для переводов (поддержка параллельной записи)
        self.translation_recorders = {}  # Dict[AudioSourceType, AudioRecorder]
        self.translation_audio_levels = {}  # Dict[AudioSourceType, float] - для мониторинга уровня звука
        
        # Выбранные устройства
        self.selected_microphone_device = None  # Индекс устройства
        self.selected_stereo_mix_device = None  # Индекс устройства
        
        # Устройство записи совещания
        self.meeting_capture_microphone = True
        self.meeting_capture_system_audio = True
        self.selected_system_output_name = None  # Имя устройства вывода (soundcard speaker)
        
        # Таймер для мониторинга уровня звука
        self.audio_level_timer = QTimer()
        self.audio_level_timer.timeout.connect(self.check_audio_level)
        
        # Папка для записей
        self.recordings_folder = "./Recordings"

        # Авто-стоп записи по таймеру (None — выключено)
        self.recording_auto_stop_seconds: Optional[int] = None
        self._auto_stop_triggered = False
        
        # Сохранение исходных расширенных стилей окна для восстановления
        self.original_ex_style = None
        
        self.logger.info("Инициализация главного окна...")
        self.init_ui()
        self.setup_window_properties()
        self.logger.info("Главное окно инициализировано")
    
    def closeEvent(self, event):
        """Обработчик закрытия окна - завершить все потоки"""
        # Остановить все записи переводов, если идут
        if self.translation_recorders:
            self.logger.info("Остановка всех записей переводов при закрытии окна")
            for source_type in list(self.translation_recorders.keys()):
                try:
                    self._stop_translation_recording(source_type)
                except Exception as e:
                    self.logger.error(f"Ошибка при остановке записи {source_type}: {e}")
        
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
        meeting_group = CollapsibleGroupBox("Управление совещанием")
        meeting_layout = QVBoxLayout()
        
        # Кнопки совещания
        btn_layout = QHBoxLayout()
        self.btn_start_meeting = QPushButton("🔴 Записать совещание")
        self.btn_start_meeting.clicked.connect(self.start_meeting)
        self.btn_stop_meeting = QPushButton("⏹ Остановить запись")
        self.btn_stop_meeting.clicked.connect(self.stop_meeting)
        self.btn_stop_meeting.setEnabled(False)
        
        self.btn_load_transcript = QPushButton("📝 Загрузить транскрипт")
        self.btn_load_transcript.clicked.connect(self.load_transcript)

        self.btn_load_template = QPushButton("Загрузить пример")
        self.btn_load_template.clicked.connect(self.load_template)

        self.btn_generate_report = QPushButton("📄 ОТЧЕТ")
        self.btn_generate_report.clicked.connect(self.generate_report)
        self.btn_generate_report.setEnabled(False)

        # Восстановление записи из аварийных сырых файлов (.pcm) в готовый WAV
        self.btn_recover_recording = QPushButton("🛠 Восстановитель записи")
        self.btn_recover_recording.setToolTip(
            "Собрать готовый WAV из аварийных файлов записи (.mic.pcm / .sys.pcm),\n"
            "если запись не сохранилась автоматически или митинг превысил лимит одного файла."
        )
        self.btn_recover_recording.clicked.connect(self.recover_recording)

        btn_layout.addWidget(self.btn_start_meeting)
        btn_layout.addWidget(self.btn_stop_meeting)
        btn_layout.addWidget(self.btn_load_transcript)
        btn_layout.addWidget(self.btn_load_template)
        btn_layout.addWidget(self.btn_generate_report)
        btn_layout.addWidget(self.btn_recover_recording)
        meeting_layout.addLayout(btn_layout)

        # Авто-стоп записи по таймеру (чтобы можно было уйти от компьютера)
        auto_stop_layout = QHBoxLayout()
        auto_stop_label = QLabel("Авто-стоп записи:")
        auto_stop_label.setStyleSheet("border: none;")
        auto_stop_layout.addWidget(auto_stop_label)
        self.combo_auto_stop = QComboBox()
        # (подпись, секунды); None — выключено, -1 — произвольное значение
        self.combo_auto_stop.addItem("Выкл", None)
        self.combo_auto_stop.addItem("30 мин", 30 * 60)
        self.combo_auto_stop.addItem("1 ч", 60 * 60)
        self.combo_auto_stop.addItem("1.5 ч", 90 * 60)
        self.combo_auto_stop.addItem("2 ч", 120 * 60)
        self.combo_auto_stop.addItem("3 ч", 180 * 60)
        self.combo_auto_stop.addItem("4 ч", 240 * 60)
        self.combo_auto_stop.addItem("Другое…", -1)
        self.combo_auto_stop.setCurrentIndex(0)
        self.combo_auto_stop.currentIndexChanged.connect(self._apply_auto_stop_selection)
        auto_stop_layout.addWidget(self.combo_auto_stop)
        auto_stop_layout.addStretch()
        meeting_layout.addLayout(auto_stop_layout)
        
        # Папка для сохранения
        folder_layout = QHBoxLayout()
        folder_label = QLabel("Папка записей:")
        folder_label.setStyleSheet("border: none;")  # Информационный лейбл без рамки
        folder_layout.addWidget(folder_label)
        self.label_recordings_folder = QLabel("./Recordings")
        self.label_recordings_folder.setStyleSheet("border: none; padding: 3px; color: #666666;")  # Без рамки, серый текст
        folder_layout.addWidget(self.label_recordings_folder)
        self.btn_choose_folder = QPushButton("Выбрать папку")
        self.btn_choose_folder.clicked.connect(self.choose_recordings_folder)
        folder_layout.addWidget(self.btn_choose_folder)
        meeting_layout.addLayout(folder_layout)
        
        # Выбор устройства для записи совещания
        meeting_device_layout = QHBoxLayout()
        device_label = QLabel("Режим записи:")
        device_label.setStyleSheet("border: none;")  # Информационный лейбл без рамки
        meeting_device_layout.addWidget(device_label)
        self.combo_meeting_mode = QComboBox()
        self.combo_meeting_mode.addItem("Микрофон + системный звук (рекомендуется)", "mic+system")
        self.combo_meeting_mode.addItem("Только микрофон", "mic")
        self.combo_meeting_mode.addItem("Только системный звук", "system")
        self.combo_meeting_mode.setCurrentIndex(0)
        self.combo_meeting_mode.currentIndexChanged.connect(self.on_meeting_mode_changed)
        meeting_device_layout.addWidget(self.combo_meeting_mode)
        meeting_device_layout.addStretch()
        meeting_layout.addLayout(meeting_device_layout)

        # Выбор устройства вывода для захвата системного звука (loopback)
        meeting_output_layout = QHBoxLayout()
        output_label = QLabel("Системный звук (выход):")
        output_label.setStyleSheet("border: none;")
        meeting_output_layout.addWidget(output_label)
        self.combo_system_output = QComboBox()
        self.combo_system_output.currentIndexChanged.connect(self.on_system_output_changed)
        meeting_output_layout.addWidget(self.combo_system_output)
        self.btn_refresh_devices = QPushButton("🔄 Обновить устройства")
        self.btn_refresh_devices.clicked.connect(self.refresh_audio_devices)
        meeting_output_layout.addWidget(self.btn_refresh_devices)
        meeting_output_layout.addStretch()
        meeting_layout.addLayout(meeting_output_layout)
        
        # Выбор языка отчета
        report_lang_layout = QHBoxLayout()
        report_lang_label = QLabel("Язык отчета:")
        report_lang_label.setStyleSheet("border: none;")  # Информационный лейбл без рамки
        report_lang_layout.addWidget(report_lang_label)
        self.combo_report_language = QComboBox()
        self.combo_report_language.addItems([lang.display_name for lang in Language])
        self.combo_report_language.setCurrentIndex(0)  # Русский по умолчанию
        self.combo_report_language.currentIndexChanged.connect(self.on_report_language_changed)
        report_lang_layout.addWidget(self.combo_report_language)
        report_lang_layout.addStretch()
        meeting_layout.addLayout(report_lang_layout)
        
        # Статус совещания с таймером
        status_layout = QHBoxLayout()
        self.label_meeting_status = QLabel("Статус: Не начато")
        self.label_meeting_status.setStyleSheet("border: none;")  # Информационный лейбл без рамки
        status_layout.addWidget(self.label_meeting_status)
        
        # Индикатор записи (красный круг)
        self.recording_indicator = QLabel("●")
        self.recording_indicator.setStyleSheet("color: gray; font-size: 20px; border: none;")  # Без рамки
        self.recording_indicator.setVisible(False)
        status_layout.addWidget(self.recording_indicator)
        
        # Таймер записи
        self.label_recording_timer = QLabel("00:00:00")
        self.label_recording_timer.setStyleSheet("font-weight: bold; color: red; border: none;")  # Без рамки
        self.label_recording_timer.setVisible(False)
        status_layout.addWidget(self.label_recording_timer)
        
        meeting_layout.addLayout(status_layout)
        
        # Таймер для обновления времени записи
        self.recording_timer = QTimer()
        self.recording_timer.timeout.connect(self.update_recording_timer)
        self.recording_start_time = None
        
        meeting_group.setLayout(meeting_layout)
        layout.addWidget(meeting_group)
        layout.setStretchFactor(meeting_group, 0)  # Не растягивается
        
        # Группа переводов
        translation_group = CollapsibleGroupBox("Переводы в реальном времени")
        translation_layout = QVBoxLayout()
        
        # Выбор устройства микрофона (для «Выслушать нас»). Для собеседника
        # используется WASAPI loopback с устройства вывода, выбранного в группе
        # «Управление совещанием» — отдельный комбобокс не нужен.
        device_layout = QHBoxLayout()
        mic_label = QLabel("Микрофон:")
        mic_label.setStyleSheet("border: none;")
        device_layout.addWidget(mic_label)
        self.combo_microphone = QComboBox()
        self.combo_microphone.currentIndexChanged.connect(self.on_microphone_changed)
        device_layout.addWidget(self.combo_microphone)
        device_layout.addStretch()
        translation_layout.addLayout(device_layout)

        info_label = QLabel(
            "ℹ️  Собеседника слышим через тот же выход, что выбран выше "
            "(«Системный звук (выход)»). Работает с BT-наушниками, проводными и колонками."
        )
        info_label.setStyleSheet("border: none; color: #555555; font-size: 10px;")
        info_label.setWordWrap(True)
        translation_layout.addWidget(info_label)

        # Загрузить список устройств (init)
        self.load_audio_devices()
        self.load_system_outputs()
        
        # Статус записи перевода
        self.label_translation_status = QLabel("Статус: Не записывается")
        self.label_translation_status.setStyleSheet("border: none;")  # Информационный лейбл без рамки
        translation_layout.addWidget(self.label_translation_status)
        
        translation_group.setLayout(translation_layout)
        layout.addWidget(translation_group)
        layout.setStretchFactor(translation_group, 0)  # Не растягивается
        
        # Кнопки переводов с настройками языков (всегда видны, вне сворачиваемой панели)
        translation_buttons_group = QGroupBox("Действия переводов")
        translation_buttons_layout = QHBoxLayout()
        
        # Левая колонка: "Выслушать собеседника" с настройками языков
        interlocutor_column = QVBoxLayout()
        self.btn_listen_interlocutor = QPushButton("Выслушать собеседника")
        self.btn_listen_interlocutor.setCheckable(True)  # Toggle button
        self.btn_listen_interlocutor.toggled.connect(lambda checked: self.toggle_translation_recording(AudioSourceType.STEREO_MIX, checked))
        interlocutor_column.addWidget(self.btn_listen_interlocutor)
        
        # Языки для "Выслушать собеседника"
        interlocutor_lang_layout = QHBoxLayout()
        interlocutor_source_label = QLabel("Язык:")
        interlocutor_source_label.setStyleSheet("border: none; font-size: 10px;")  # Информационный лейбл без рамки
        interlocutor_lang_layout.addWidget(interlocutor_source_label)
        self.combo_stereo_mix_source_language = QComboBox()
        self.combo_stereo_mix_source_language.addItems([lang.display_name for lang in Language])
        self.combo_stereo_mix_source_language.setCurrentIndex(0)  # Русский по умолчанию
        self.combo_stereo_mix_source_language.currentIndexChanged.connect(self.on_stereo_mix_source_language_changed)
        interlocutor_lang_layout.addWidget(self.combo_stereo_mix_source_language)
        
        interlocutor_arrow_label = QLabel("→")
        interlocutor_arrow_label.setStyleSheet("border: none; font-size: 10px;")
        interlocutor_lang_layout.addWidget(interlocutor_arrow_label)
        
        self.combo_stereo_mix_target_language = QComboBox()
        self.combo_stereo_mix_target_language.addItems([lang.display_name for lang in Language])
        self.combo_stereo_mix_target_language.setCurrentIndex(2)  # English по умолчанию
        self.combo_stereo_mix_target_language.currentIndexChanged.connect(self.on_stereo_mix_target_language_changed)
        interlocutor_lang_layout.addWidget(self.combo_stereo_mix_target_language)
        interlocutor_column.addLayout(interlocutor_lang_layout)
        
        # Правая колонка: "Выслушать нас" с настройками языков
        us_column = QVBoxLayout()
        self.btn_listen_us = QPushButton("Выслушать нас")
        self.btn_listen_us.setCheckable(True)  # Toggle button
        self.btn_listen_us.toggled.connect(lambda checked: self.toggle_translation_recording(AudioSourceType.MICROPHONE, checked))
        us_column.addWidget(self.btn_listen_us)
        
        # Языки для "Выслушать нас"
        us_lang_layout = QHBoxLayout()
        us_source_label = QLabel("Язык:")
        us_source_label.setStyleSheet("border: none; font-size: 10px;")  # Информационный лейбл без рамки
        us_lang_layout.addWidget(us_source_label)
        self.combo_microphone_source_language = QComboBox()
        self.combo_microphone_source_language.addItems([lang.display_name for lang in Language])
        self.combo_microphone_source_language.setCurrentIndex(0)  # Русский по умолчанию
        self.combo_microphone_source_language.currentIndexChanged.connect(self.on_microphone_source_language_changed)
        us_lang_layout.addWidget(self.combo_microphone_source_language)
        
        us_arrow_label = QLabel("→")
        us_arrow_label.setStyleSheet("border: none; font-size: 10px;")
        us_lang_layout.addWidget(us_arrow_label)
        
        self.combo_microphone_target_language = QComboBox()
        self.combo_microphone_target_language.addItems([lang.display_name for lang in Language])
        self.combo_microphone_target_language.setCurrentIndex(2)  # English по умолчанию
        self.combo_microphone_target_language.currentIndexChanged.connect(self.on_microphone_target_language_changed)
        us_lang_layout.addWidget(self.combo_microphone_target_language)
        us_column.addLayout(us_lang_layout)
        
        # Добавить колонки в основной layout
        translation_buttons_layout.addLayout(interlocutor_column)
        translation_buttons_layout.addLayout(us_column)
        translation_buttons_group.setLayout(translation_buttons_layout)
        layout.addWidget(translation_buttons_group)
        layout.setStretchFactor(translation_buttons_group, 0)  # Не растягивается
        
        # Окна текста (в виджете-обертке для stretch)
        text_widget = QWidget()
        text_layout = QHBoxLayout(text_widget)
        text_layout.setContentsMargins(0, 0, 0, 0)
        
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
        
        layout.addWidget(text_widget)
        layout.setStretchFactor(text_widget, 1)  # Растягивается на все свободное пространство
        
        # Настройки окна
        settings_group = QGroupBox("Настройки окна")
        settings_layout = QVBoxLayout()
        
        # Прозрачность
        opacity_layout = QHBoxLayout()
        opacity_label = QLabel("Прозрачность:")
        opacity_label.setStyleSheet("border: none;")  # Информационный лейбл без рамки
        opacity_layout.addWidget(opacity_label)
        self.slider_opacity = QSlider(Qt.Orientation.Horizontal)
        self.slider_opacity.setMinimum(30)
        self.slider_opacity.setMaximum(100)
        self.slider_opacity.setValue(90)
        self.slider_opacity.valueChanged.connect(self.on_opacity_changed)
        opacity_layout.addWidget(self.slider_opacity)
        self.label_opacity = QLabel("90%")
        self.label_opacity.setStyleSheet("border: none; min-width: 40px;")  # Информационный лейбл без рамки
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
    
    def _apply_global_styles(self):
        """Применить глобальные стили для UI элементов"""
        # Глобальные стили для информационных лейблов (без рамок)
        # Интерактивные элементы (кнопки, комбобоксы) будут иметь свои стили
        global_style = """
            /* Информационные лейблы - без рамок */
            QLabel {
                border: none;
                padding: 2px;
                background-color: transparent;
            }
            
            /* Кнопки - с рамками и hover эффектами */
            QPushButton {
                border: 1px solid #0078d4;
                border-radius: 4px;
                padding: 6px 12px;
                background-color: #0078d4;
                color: white;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #106ebe;
                border-color: #005a9e;
            }
            QPushButton:pressed {
                background-color: #004578;
                border-color: #003d6b;
                border-width: 2px;
                padding: 5px 11px;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                border-color: #999999;
                color: #666666;
            }
            QPushButton:checked {
                background-color: #004578;
                border-color: #003d6b;
                border-width: 2px;
                box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.2);
            }
            
            /* Комбобоксы - с рамками */
            QComboBox {
                border: 1px solid #cccccc;
                border-radius: 4px;
                padding: 4px 8px;
                background-color: white;
                min-width: 120px;
            }
            QComboBox:hover {
                border-color: #0078d4;
            }
            QComboBox:focus {
                border-color: #0078d4;
                border-width: 2px;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 6px solid #333333;
                margin-right: 5px;
            }
            
            /* QSlider */
            QSlider::groove:horizontal {
                border: 1px solid #cccccc;
                height: 6px;
                background: #e0e0e0;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #0078d4;
                border: 1px solid #005a9e;
                width: 18px;
                margin: -6px 0;
                border-radius: 9px;
            }
            QSlider::handle:horizontal:hover {
                background: #106ebe;
            }
        """
        self.setStyleSheet(global_style)
    
    def setup_window_properties(self):
        """Настроить свойства окна"""
        self.setWindowOpacity(0.9)
        flags = self.windowFlags()
        # Можно добавить флаги для прозрачности и т.д.
    
    def on_stereo_mix_source_language_changed(self, index: int):
        """Обработчик изменения языка оригинала для 'Выслушать собеседника'"""
        self.stereo_mix_source_language = list(Language)[index]
        self.logger.info(f"Язык оригинала (Собеседник) изменен на: {self.stereo_mix_source_language.display_name}")
    
    def on_stereo_mix_target_language_changed(self, index: int):
        """Обработчик изменения языка перевода для 'Выслушать собеседника'"""
        self.stereo_mix_target_language = list(Language)[index]
        self.logger.info(f"Язык перевода (Собеседник) изменен на: {self.stereo_mix_target_language.display_name}")
    
    def on_microphone_source_language_changed(self, index: int):
        """Обработчик изменения языка оригинала для 'Выслушать нас'"""
        self.microphone_source_language = list(Language)[index]
        self.logger.info(f"Язык оригинала (Мы) изменен на: {self.microphone_source_language.display_name}")
    
    def on_microphone_target_language_changed(self, index: int):
        """Обработчик изменения языка перевода для 'Выслушать нас'"""
        self.microphone_target_language = list(Language)[index]
        self.logger.info(f"Язык перевода (Мы) изменен на: {self.microphone_target_language.display_name}")
    
    def on_meeting_mode_changed(self, index: int):
        """Обработчик изменения режима записи совещания"""
        mode = self.combo_meeting_mode.itemData(index)
        if mode == "mic+system":
            self.meeting_capture_microphone = True
            self.meeting_capture_system_audio = True
        elif mode == "mic":
            self.meeting_capture_microphone = True
            self.meeting_capture_system_audio = False
        elif mode == "system":
            self.meeting_capture_microphone = False
            self.meeting_capture_system_audio = True
        else:
            self.meeting_capture_microphone = True
            self.meeting_capture_system_audio = True

        self.combo_system_output.setEnabled(self.meeting_capture_system_audio)
        self.logger.info(f"Режим записи совещания изменен на: {mode}")

    def on_system_output_changed(self, index: int):
        """Обработчик изменения устройства вывода для loopback"""
        output_name = self.combo_system_output.itemData(index)
        self.selected_system_output_name = output_name
        if output_name:
            self.logger.info(f"Выбран выход для системного звука (loopback): {output_name}")

    def load_system_outputs(self) -> None:
        """Загрузить список устройств вывода (speakers) для loopback записи системного звука."""
        self.combo_system_output.clear()
        self.selected_system_output_name = None
        try:
            import soundcard as sc  # type: ignore

            speakers = sc.all_speakers()
            default_sp = sc.default_speaker()
            default_name = default_sp.name if default_sp is not None else None

            for sp in speakers:
                self.combo_system_output.addItem(sp.name, sp.name)
                if self.selected_system_output_name is None:
                    self.selected_system_output_name = sp.name

            if default_name is not None:
                for i in range(self.combo_system_output.count()):
                    if self.combo_system_output.itemData(i) == default_name:
                        self.combo_system_output.setCurrentIndex(i)
                        self.selected_system_output_name = default_name
                        break

            self.combo_system_output.setEnabled(True)
            self.logger.info(f"Загружено устройств вывода (loopback): {self.combo_system_output.count()}")
        except Exception as e:
            self.combo_system_output.setEnabled(False)
            self.logger.warning(f"Не удалось загрузить устройства вывода (loopback): {e}")
    
    def on_report_language_changed(self, index: int):
        """Обработчик изменения языка отчета"""
        self.report_language = list(Language)[index]
        self.logger.info(f"Язык отчета изменен на: {self.report_language.display_name}")
    
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
            
            # Заполнить комбобокс микрофонов (исключая Stereo Mix-устройства,
            # т.к. для системного звука используется loopback)
            self.combo_microphone.clear()
            for idx, name in microphone_devices:
                self.combo_microphone.addItem(name, idx)
                if self.selected_microphone_device is None:
                    self.selected_microphone_device = idx

            # Stereo Mix храним только как fallback для записи совещания (если loopback не сработает)
            if stereo_mix_devices and self.selected_stereo_mix_device is None:
                self.selected_stereo_mix_device = stereo_mix_devices[0][0]

            # Установить выбранный микрофон
            if self.selected_microphone_device is not None:
                for i in range(self.combo_microphone.count()):
                    if self.combo_microphone.itemData(i) == self.selected_microphone_device:
                        self.combo_microphone.setCurrentIndex(i)
                        break

            self.logger.info(
                f"Загружено микрофонов: {len(microphone_devices)}, "
                f"Stereo Mix-fallback: {len(stereo_mix_devices)}"
            )
            
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

    def refresh_audio_devices(self) -> None:
        """Обновить списки аудио-устройств (после подключения BT-наушников и т.п.)."""
        self.logger.info("Обновление списков аудио-устройств")
        try:
            sd._terminate()
            sd._initialize()
        except Exception as e:
            self.logger.debug(f"sd reinit skipped: {e}")
        self.load_audio_devices()
        self.load_system_outputs()
        QMessageBox.information(
            self,
            "Устройства обновлены",
            "Списки микрофонов и выходов перезагружены.\n"
            "Если только что подключили BT-наушники — выберите их в «Системный звук (выход)».",
        )
    
    def check_audio_level(self):
        """Проверить уровень звука во время записи (для всех активных записей)"""
        if not self.translation_recorders:
            return
        
        for source_type, recorder in self.translation_recorders.items():
            try:
                # Использовать метод get_audio_level если доступен
                if hasattr(recorder, 'get_audio_level'):
                    level = recorder.get_audio_level()
                else:
                    # Fallback - вычисление вручную
                    if not hasattr(recorder, 'recording_data') or not recorder.recording_data:
                        continue
                    
                    if len(recorder.recording_data) > 0:
                        last_chunk = recorder.recording_data[-1]
                        if last_chunk is not None and len(last_chunk) > 0:
                            rms = np.sqrt(np.mean(last_chunk.astype(np.float32) ** 2))
                            level = min(100, (rms / 32767.0) * 100)
                        else:
                            continue
                    else:
                        continue
                
                source_name = "Собеседник" if source_type == AudioSourceType.STEREO_MIX else "Микрофон"
                last_level = self.translation_audio_levels.get(source_type, 0.0)

                # Логируем только заметные изменения, чтобы не шуметь.
                # Паузы в речи (доли секунды тишины) - норма, варнингом их не считаем.
                if level >= 5.0 and abs(level - last_level) > 5.0:
                    self.translation_audio_levels[source_type] = level
                    self.logger.info(f"🔊 Уровень звука ({source_name}): {level:.1f}%")
                elif 1.0 <= level < 5.0 and abs(level - last_level) > 2.0:
                    self.translation_audio_levels[source_type] = level
                    self.logger.info(f"🔉 Уровень звука ({source_name}): {level:.1f}%")
            except Exception as e:
                self.logger.debug(f"Ошибка проверки уровня звука для {source_type}: {e}")
    
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
    
    def _set_window_display_affinity(self, exclude_from_capture: bool):
        """Установить флаг исключения окна из захвата экрана
        
        Использует Windows API SetWindowDisplayAffinity для скрытия окна
        от приложений захвата экрана (Zoom, Google Meet, Teams и т.п.)
        Окно остается видимым на локальном экране, но не видно другим пользователям.
        """
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            
            # Настроить функцию для правильной обработки ошибок
            user32.SetWindowDisplayAffinity.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.DWORD]
            user32.SetWindowDisplayAffinity.restype = ctypes.wintypes.BOOL
            
            hwnd = int(self.winId())
            flag = WDA_EXCLUDEFROMCAPTURE if exclude_from_capture else WDA_NONE
            
            result = user32.SetWindowDisplayAffinity(hwnd, flag)
            
            if result:
                status = "скрыто от захвата экрана" if exclude_from_capture else "видно в захвате экрана"
                self.logger.info(f"Окно {status}")
            else:
                # Получить код ошибки Windows
                error_code = kernel32.GetLastError()
                self.logger.warning(
                    f"Не удалось установить флаг скрытия окна. "
                    f"Код ошибки Windows: {error_code}"
                )
        except Exception as e:
            self.logger.error(f"Ошибка при установке флага скрытия окна: {e}", exc_info=True)
    
    def _set_window_taskbar_visibility(self, hide_from_taskbar: bool):
        """Скрыть/показать окно в панели задач и Alt+Tab
        
        Использует Windows API SetWindowLongPtr для изменения расширенных стилей окна.
        При скрытии окно не будет видно в панели задач и в Alt+Tab, но останется видимым на экране.
        """
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            
            # Для 64-битных систем используем SetWindowLongPtr
            # Определяем, какая функция доступна
            if hasattr(user32, 'SetWindowLongPtrW'):
                set_window_long = user32.SetWindowLongPtrW
                get_window_long = user32.GetWindowLongPtrW
            else:
                # Fallback для старых версий (32-битные или старые API)
                set_window_long = user32.SetWindowLongW
                get_window_long = user32.GetWindowLongW
            
            # Определить тип LONG_PTR (для 64-битных систем это c_longlong)
            # В ctypes.wintypes может не быть LONG_PTR, используем c_longlong
            LONG_PTR_TYPE = getattr(ctypes.wintypes, 'LONG_PTR', ctypes.c_longlong)
            
            # Настроить типы аргументов и возвращаемого значения
            set_window_long.argtypes = [ctypes.wintypes.HWND, ctypes.c_int, LONG_PTR_TYPE]
            set_window_long.restype = LONG_PTR_TYPE
            get_window_long.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
            get_window_long.restype = LONG_PTR_TYPE
            
            hwnd = int(self.winId())
            
            # Сохранить исходные стили при первом вызове
            if self.original_ex_style is None:
                self.original_ex_style = get_window_long(hwnd, GWL_EXSTYLE)
                self.logger.debug(f"Сохранены исходные расширенные стили окна: {self.original_ex_style}")
            
            # Получить текущие стили
            current_style = get_window_long(hwnd, GWL_EXSTYLE)
            
            # Сбросить код ошибки перед вызовом SetWindowLongPtr
            kernel32.SetLastError(0)
            
            if hide_from_taskbar:
                # Добавить WS_EX_TOOLWINDOW для скрытия из панели задач
                new_style = current_style | WS_EX_TOOLWINDOW
                status_msg = "скрыто из панели задач"
            else:
                # Восстановить исходные стили (убрать WS_EX_TOOLWINDOW)
                if self.original_ex_style is not None:
                    new_style = self.original_ex_style
                else:
                    # Если исходные стили не сохранены, просто убираем флаг
                    new_style = current_style & ~WS_EX_TOOLWINDOW
                status_msg = "показано в панели задач"
            
            # Установить новые стили
            # SetWindowLongPtr возвращает предыдущее значение стилей, не код ошибки
            previous_style = set_window_long(hwnd, GWL_EXSTYLE, new_style)
            
            # Проверить ошибку через GetLastError
            error_code = kernel32.GetLastError()
            
            if error_code == 0:
                # Обновить окно для применения изменений
                # Флаги: SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED
                SWP_NOMOVE = 0x0002
                SWP_NOSIZE = 0x0001
                SWP_NOZORDER = 0x0004
                SWP_FRAMECHANGED = 0x0020
                user32.SetWindowPos(
                    hwnd, 0, 0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED
                )
                self.logger.info(f"Окно {status_msg}")
            else:
                self.logger.warning(
                    f"Не удалось изменить видимость окна в панели задач. "
                    f"Код ошибки Windows: {error_code}"
                )
        except Exception as e:
            self.logger.error(f"Ошибка при изменении видимости окна в панели задач: {e}", exc_info=True)
    
    def on_hide_screen_changed(self, checked: bool):
        """Обработчик скрытия экрана"""
        # Скрыть окно от захвата экрана
        self._set_window_display_affinity(checked)
        # Скрыть окно из панели задач
        self._set_window_taskbar_visibility(checked)
    
    def start_meeting(self):
        """Начать совещание"""
        self.logger.info("Запрос на начало совещания")
        
        # Защита от двойного клика - блокировать кнопку сразу
        if not self.btn_start_meeting.isEnabled():
            self.logger.warning("Попытка начать совещание при заблокированной кнопке")
            return
        
        self.btn_start_meeting.setEnabled(False)
        
        # Проверить конфликт устройств с записью перевода
        if self.translation_recorders:
            meeting_devices = set()
            if self.meeting_capture_microphone:
                meeting_devices.add(self.selected_microphone_device)
            if self.meeting_capture_system_audio:
                # Stereo Mix используется как запасной вариант для системного звука
                meeting_devices.add(self.selected_stereo_mix_device)
            meeting_devices.discard(None)
            for source_type in self.translation_recorders.keys():
                translation_device_idx = (
                    self.selected_stereo_mix_device
                    if source_type == AudioSourceType.STEREO_MIX
                    else self.selected_microphone_device
                )
                if translation_device_idx in meeting_devices:
                    translation_name = "Stereo Mix" if source_type == AudioSourceType.STEREO_MIX else "Микрофон"
                    QMessageBox.warning(
                        self,
                        "Конфликт устройств",
                        "Невозможно начать запись совещания:\n"
                        f"Одно из устройств (микрофон/системный звук) уже используется для записи перевода ({translation_name}).\n\n"
                        "Остановите запись перевода или выберите другое устройство."
                    )
                    self.btn_start_meeting.setEnabled(True)
                    return
        
        # Создать совещание и начать запись с указанной папкой
        async def start_meeting_with_path():
            meeting = await self.meeting_service.start_meeting()
            
            # Получить путь для записи с учетом выбранной папки
            from infrastructure.storage.storage_service import StorageService
            storage = StorageService()
            recording_path = storage.get_recording_path(str(meeting.id), self.recordings_folder)
            
            # Начать запись совещания согласно выбранному режиму
            self.logger.info(
                f"Начало записи совещания в файл: {recording_path} "
                f"(mic={self.meeting_capture_microphone}, system={self.meeting_capture_system_audio})"
            )
            self.meeting_service.audio_recorder.start_recording(
                recording_path,
                capture_microphone=self.meeting_capture_microphone,
                capture_system_audio=self.meeting_capture_system_audio,
                system_output_name=self.selected_system_output_name,
                microphone_device_index=self.selected_microphone_device,
                stereo_mix_device_index=self.selected_stereo_mix_device,
                prefer_wasapi_loopback=True,
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
        # Новое совещание - сбрасываем привязанный транскрипт
        self.current_transcript_text = None
        self.current_transcript_path = None
        self.btn_start_meeting.setEnabled(False)
        self.btn_stop_meeting.setEnabled(True)
        self.btn_generate_report.setEnabled(False)
        
        # Показать индикатор записи
        self.recording_indicator.setVisible(True)
        self.recording_indicator.setStyleSheet("color: red; font-size: 20px;")
        
        # Запустить таймер (сбросив состояние авто-стопа для новой записи)
        from datetime import datetime
        self._auto_stop_triggered = False
        self.recording_start_time = datetime.now()
        self.recording_timer.start(1000)  # Обновлять каждую секунду
        self.update_recording_timer()
        
        self.label_meeting_status.setText(f"Статус: Запись идет (ID: {str(meeting.id)[:8]})")
    
    def stop_meeting(self):
        """Остановить совещание"""
        # Защита от повторных кликов: пока идёт остановка, кнопка недоступна.
        if not self.btn_stop_meeting.isEnabled():
            self.logger.warning("Повторный запрос на остановку проигнорирован")
            return
        self.logger.info("Запрос на остановку совещания")
        self.btn_stop_meeting.setEnabled(False)
        self.label_meeting_status.setText("Статус: Сохранение записи…")
        worker = AsyncWorker(self.meeting_service.stop_meeting())
        worker.finished.connect(self.on_meeting_stopped)
        worker.finished.connect(lambda: self._remove_worker(worker))
        worker.error.connect(self.on_meeting_stop_error)
        worker.error.connect(lambda: self._remove_worker(worker))
        self.workers.append(worker)
        worker.start()

    def _reset_recording_ui(self):
        """Сбросить UI записи (таймер, индикатор). Вызывается и при успехе, и при ошибке."""
        self.recording_timer.stop()
        self.recording_indicator.setVisible(False)
        self.label_recording_timer.setVisible(False)
        self.recording_start_time = None
        self._auto_stop_triggered = False

    def on_meeting_stop_error(self, error_message: str):
        """Обработчик ошибки остановки совещания.

        Критично: даже при сбое сохранения UI обязан вернуться в согласованное
        состояние — иначе «красные цифры» продолжают идти при остановленной записи.
        """
        self.logger.error(f"Ошибка остановки совещания: {error_message}")
        self._reset_recording_ui()
        self.btn_start_meeting.setEnabled(True)
        self.btn_stop_meeting.setEnabled(False)
        self.label_meeting_status.setText("Статус: Ошибка при остановке записи")
        QMessageBox.critical(
            self,
            "Ошибка остановки записи",
            f"{error_message}\n\n"
            "Если в сообщении указаны файлы .pcm — исходные данные записи сохранены "
            "на диске и их можно восстановить."
        )

    def on_meeting_stopped(self, meeting):
        """Обработчик остановки совещания"""
        duration = (meeting.end_time - meeting.start_time).total_seconds() if meeting.end_time else 0
        self.logger.info(f"Совещание остановлено: ID={meeting.id}, длительность={duration:.1f} сек")
        self.current_meeting = meeting
        self.btn_start_meeting.setEnabled(True)
        self.btn_stop_meeting.setEnabled(False)

        # Скрыть индикатор записи и остановить таймер
        self._reset_recording_ui()

        # Сбросить состояние (устройство выбирается отдельно через комбобоксы)
        
        # Показать путь к файлу
        if meeting.recording_path:
            file_size = os.path.getsize(meeting.recording_path) / (1024 * 1024)  # MB
            self.label_meeting_status.setText(
                f"Статус: Остановлено | Файл: {Path(meeting.recording_path).name} ({file_size:.2f} MB) | "
                f"Прогоните WAV в Colab и нажмите «📝 Загрузить транскрипт»"
            )
            self.logger.info(f"Запись сохранена: {meeting.recording_path} ({file_size:.2f} MB)")

        # Кнопка ОТЧЁТ включится только после загрузки транскрипта и шаблона
        self._update_generate_report_enabled()

    def recover_recording(self):
        """Собрать готовый WAV из аварийных сырых файлов (.mic.pcm / .sys.pcm).

        Пользователь выбирает любой из файлов пары; программа находит оба и сводит
        их тем же движком, что и обычную запись, в новый ..._recovered.wav.
        """
        from PyQt6.QtWidgets import QFileDialog

        recorder = self.meeting_service.audio_recorder
        if getattr(recorder, "is_recording", False):
            QMessageBox.warning(self, "Восстановление недоступно",
                                "Сейчас идёт запись. Остановите её перед восстановлением.")
            return

        path, _ = QFileDialog.getOpenFileName(
            self, "Выберите аварийный файл записи (.mic.pcm или .sys.pcm)",
            self.recordings_folder, "Сырые файлы записи (*.pcm)"
        )
        if not path:
            return

        # Определить базовый путь и пару .mic.pcm / .sys.pcm
        if path.endswith(".mic.pcm"):
            base = path[: -len(".mic.pcm")]
        elif path.endswith(".sys.pcm"):
            base = path[: -len(".sys.pcm")]
        else:
            QMessageBox.warning(self, "Неподходящий файл",
                                "Выберите файл, оканчивающийся на .mic.pcm или .sys.pcm")
            return

        mic_raw = base + ".mic.pcm"
        sys_raw = base + ".sys.pcm"
        has_mic = os.path.exists(mic_raw) and os.path.getsize(mic_raw) > 0
        has_sys = os.path.exists(sys_raw) and os.path.getsize(sys_raw) > 0
        if not has_mic and not has_sys:
            QMessageBox.warning(self, "Нет данных",
                                "Рядом не найдено непустых файлов .mic.pcm / .sys.pcm.")
            return

        # base — это исходный путь ..._meeting.wav; итог кладём отдельным файлом,
        # чтобы не затирать возможный частичный WAV.
        stem = base[: -len(".wav")] if base.endswith(".wav") else base
        output_path = stem + "_recovered.wav"

        self.btn_recover_recording.setEnabled(False)
        self.label_meeting_status.setText("Статус: Восстановление записи…")
        self.logger.info(f"Восстановление записи из {mic_raw} / {sys_raw} → {output_path}")

        async def do_recover():
            # Тяжёлое сведение — в отдельном потоке, чтобы не блокировать UI.
            truncated = await asyncio.to_thread(
                recorder._stream_mix_to_wav,
                output_path,
                mic_raw if has_mic else None,
                sys_raw if has_sys else None,
            )
            return output_path, truncated

        worker = AsyncWorker(do_recover())
        worker.finished.connect(self.on_recovery_finished)
        worker.finished.connect(lambda: self._remove_worker(worker))
        worker.error.connect(self.on_recovery_error)
        worker.error.connect(lambda: self._remove_worker(worker))
        self.workers.append(worker)
        worker.start()

    def on_recovery_finished(self, result):
        """Успешное восстановление записи."""
        output_path, truncated = result
        self.btn_recover_recording.setEnabled(True)
        size_mb = os.path.getsize(output_path) / (1024 * 1024) if os.path.exists(output_path) else 0
        self.logger.info(f"Запись восстановлена: {output_path} ({size_mb:.2f} MB), truncated={truncated}")
        self.label_meeting_status.setText(
            f"Статус: Восстановлено | Файл: {Path(output_path).name} ({size_mb:.2f} MB)"
        )
        note = ""
        if truncated:
            note = ("\n\nВнимание: запись длиннее лимита одного WAV — восстановлена только "
                    "первая часть. Полные сырые .pcm оставлены на диске.")
        QMessageBox.information(
            self, "Восстановление завершено",
            f"Готовый файл сохранён:\n{output_path}\n({size_mb:.2f} MB){note}"
        )

    def on_recovery_error(self, error_message: str):
        """Ошибка восстановления записи."""
        self.btn_recover_recording.setEnabled(True)
        self.label_meeting_status.setText("Статус: Ошибка восстановления")
        self.logger.error(f"Ошибка восстановления записи: {error_message}")
        QMessageBox.critical(self, "Ошибка восстановления", error_message)

    def choose_recordings_folder(self):
        """Выбрать папку для сохранения записей"""
        from PyQt6.QtWidgets import QFileDialog
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку для записей", self.recordings_folder)
        if folder:
            self.recordings_folder = folder
            self.label_recordings_folder.setText(folder)
            self.logger.info(f"Выбрана папка для записей: {folder}")

    def load_transcript(self) -> None:
        """Загрузить готовый текстовый транскрипт совещания (полученный из Colab)."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите файл транскрипта",
            "",
            "Текстовые файлы (*.txt);;Все файлы (*.*)",
        )
        if not file_path:
            return

        try:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    text = f.read()
            except UnicodeDecodeError:
                with open(file_path, "r", encoding="cp1251") as f:
                    text = f.read()
        except Exception as e:
            self.on_error(f"Не удалось прочитать файл транскрипта: {e}")
            return

        if not text.strip():
            QMessageBox.warning(self, "Пустой файл", "Файл транскрипта пуст.")
            return

        # Если совещание ещё не создано (первый запуск, без записи) — создать «обёртку»
        # под этот транскрипт, чтобы можно было сразу сделать отчёт.
        if not self.current_meeting:
            from domain.entities.meeting import Meeting
            from domain.enums.meeting_status import MeetingStatus

            meeting = Meeting.create()
            meeting.status = MeetingStatus.STOPPED
            self.current_meeting = meeting

            async def _save():
                await self.meeting_service.meeting_repository.save(meeting)
                await self.meeting_service.attach_transcript(meeting.id, file_path, text)
                return meeting

            worker = AsyncWorker(_save())
            worker.finished.connect(lambda _m, p=file_path, t=text: self._on_transcript_attached(p, t))
            worker.finished.connect(lambda: self._remove_worker(worker))
            worker.error.connect(self.on_error)
            worker.error.connect(lambda: self._remove_worker(worker))
            self.workers.append(worker)
            worker.start()
        else:
            worker = AsyncWorker(
                self.meeting_service.attach_transcript(self.current_meeting.id, file_path, text)
            )
            worker.finished.connect(lambda _m, p=file_path, t=text: self._on_transcript_attached(p, t))
            worker.finished.connect(lambda: self._remove_worker(worker))
            worker.error.connect(self.on_error)
            worker.error.connect(lambda: self._remove_worker(worker))
            self.workers.append(worker)
            worker.start()

    def _on_transcript_attached(self, file_path: str, text: str) -> None:
        """Транскрипт успешно привязан к совещанию."""
        self.current_transcript_text = text
        self.current_transcript_path = file_path
        size_kb = len(text) / 1024
        lines = text.count("\n") + 1
        self.logger.info(f"Транскрипт загружен: {file_path}, {len(text)} символов, ~{lines} строк")
        self.label_meeting_status.setText(
            f"Статус: Транскрипт загружен ({size_kb:.1f} КБ, ~{lines} строк) | "
            f"{Path(file_path).name}"
        )
        self._update_generate_report_enabled()
        QMessageBox.information(
            self,
            "Транскрипт загружен",
            f"Файл: {file_path}\nСимволов: {len(text)}\n\n"
            f"Загрузите шаблон отчёта (если ещё не загружен) и нажмите «📄 ОТЧЕТ».",
        )

    def _update_generate_report_enabled(self) -> None:
        """Кнопка ОТЧЁТ доступна, когда есть и транскрипт, и шаблон."""
        ready = bool(self.current_transcript_text) and bool(self.current_template)
        self.btn_generate_report.setEnabled(ready)
    
    def _apply_auto_stop_selection(self):
        """Пересчитать таймер авто-стопа из комбобокса (можно менять на лету)."""
        data = self.combo_auto_stop.currentData()
        if data == -1:  # «Другое…» — запросить минуты у пользователя
            from PyQt6.QtWidgets import QInputDialog
            minutes, ok = QInputDialog.getInt(
                self, "Авто-стоп записи",
                "Остановить запись через (минут):", 60, 1, 24 * 60, 1
            )
            if not ok:
                # Отмена — вернуть комбобокс к «Выкл»
                self.combo_auto_stop.blockSignals(True)
                self.combo_auto_stop.setCurrentIndex(0)
                self.combo_auto_stop.blockSignals(False)
                self.recording_auto_stop_seconds = None
                return
            self.recording_auto_stop_seconds = int(minutes) * 60
            self.combo_auto_stop.setItemText(self.combo_auto_stop.count() - 1, f"Другое ({minutes} мин)")
        else:
            self.recording_auto_stop_seconds = data
        # Смена лимита во время записи «оживляет» проверку заново
        self._auto_stop_triggered = False
        if self.recording_auto_stop_seconds:
            self.logger.info(f"Авто-стоп записи выставлен: {self.recording_auto_stop_seconds} сек")
        else:
            self.logger.info("Авто-стоп записи выключен")

    def update_recording_timer(self):
        """Обновить таймер записи"""
        if self.recording_start_time:
            from datetime import datetime
            elapsed = (datetime.now() - self.recording_start_time).total_seconds()
            hours = int(elapsed // 3600)
            minutes = int((elapsed % 3600) // 60)
            seconds = int(elapsed % 60)
            label = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

            # Авто-стоп по таймеру: сработать один раз при достижении лимита.
            if self.recording_auto_stop_seconds:
                remaining = self.recording_auto_stop_seconds - elapsed
                if remaining <= 0 and not self._auto_stop_triggered:
                    self._auto_stop_triggered = True
                    self.logger.info("Авто-стоп записи по таймеру")
                    self.stop_meeting()
                    return
                if remaining > 0:
                    r = int(remaining)
                    label += f"  ⏹ авто-стоп через {r // 3600:02d}:{(r % 3600) // 60:02d}:{r % 60:02d}"

            self.label_recording_timer.setText(label)
            self.label_recording_timer.setVisible(True)
    
    def generate_report(self):
        """Сгенерировать отчет (кнопка ОТЧЕТ)"""
        if not self.current_meeting:
            QMessageBox.warning(self, "Ошибка", "Нет активного совещания")
            return

        if not self.current_template:
            QMessageBox.warning(self, "Ошибка", "Не загружен шаблон отчета. Загрузите шаблон перед генерацией отчета.")
            return

        if not self.current_transcript_text:
            QMessageBox.warning(
                self,
                "Ошибка",
                "Не загружен текстовый транскрипт совещания.\n\n"
                "Прогоните WAV в Colab и загрузите .txt через кнопку «📝 Загрузить транскрипт».",
            )
            return

        # Получить выбранный язык отчета перед генерацией
        selected_language_code = self.report_language.code
        selected_language_name = self.report_language.display_name

        self.logger.info(
            f"Запрос на генерацию отчета. Выбранный язык: {selected_language_name} (код: {selected_language_code})"
        )
        self.btn_generate_report.setEnabled(False)
        self.label_meeting_status.setText(f"Статус: Генерация отчета на {selected_language_name}...")

        template_content = self.current_template.content
        transcript_text = self.current_transcript_text

        worker = AsyncWorker(
            self.meeting_service.process_meeting(
                self.current_meeting.id,
                selected_language_code,
                template_content,
                transcript_text,
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
        lang_name = self.report_language.display_name
        
        # Сформировать сообщение
        message = f"Отчет сгенерирован на языке: {lang_name}\n\n"
        if report_path:
            message += f"Путь к файлу:\n{report_path}\n\n"
        message += f"Превью отчета:\n{report_content[:200]}..."
        
        QMessageBox.information(self, "Отчет готов", message)
        self.label_meeting_status.setText(f"Статус: Завершено | Язык: {lang_name}")
        self.btn_generate_report.setEnabled(False)
        # Сброс, чтобы тот же транскрипт случайно не пошёл в следующее совещание
        self.current_transcript_text = None
        self.current_transcript_path = None
    
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
        self.logger.info(
            f"Шаблон загружен: {template.file_path}, тип: {template.file_type}, размер: {len(template.content)} символов"
        )
        self.current_template = template
        QMessageBox.information(self, "Шаблон загружен", f"Шаблон загружен из:\n{template.file_path}")
        self._update_generate_report_enabled()
    
    def toggle_translation_recording(self, source_type: AudioSourceType, checked: bool):
        """Переключить запись для перевода (поддержка параллельной записи).

        Источники:
        - MICROPHONE → реальный микрофон через sounddevice
        - STEREO_MIX → системный звук через WASAPI loopback от выбранного выхода
          (работает с BT, проводными и встроенными колонками)
        """
        source_name = "Собеседник (loopback)" if source_type == AudioSourceType.STEREO_MIX else "Микрофон"

        if checked:
            # Проверить, не идет ли уже запись с этого источника
            if source_type in self.translation_recorders:
                self.logger.warning(f"Запись с {source_name} уже идет")
                return

            # Для собеседника (loopback) проверяем, что выбран выход
            if source_type == AudioSourceType.STEREO_MIX and not self.selected_system_output_name:
                QMessageBox.warning(
                    self,
                    "Не выбран выход",
                    "Чтобы слышать собеседника, нужно выбрать устройство вывода в группе\n"
                    "«Управление совещанием» → «Системный звук (выход)».\n\n"
                    "Если только что подключили BT-наушники — нажмите «🔄 Обновить устройства».",
                )
                self.btn_listen_interlocutor.setChecked(False)
                return

            self.logger.info(f"Начало записи для перевода с {source_name}")

            import os as _os
            from infrastructure.storage.storage_service import StorageService
            storage = StorageService()
            prefix_label = "interlocutor" if source_type == AudioSourceType.STEREO_MIX else "us"
            temp_path = storage.get_temp_audio_path(f"translation_{prefix_label}")

            sample_rate = int(_os.getenv("AUDIO_SAMPLE_RATE", "44100"))
            channels = int(_os.getenv("AUDIO_CHANNELS", "2"))

            if source_type == AudioSourceType.STEREO_MIX:
                from infrastructure.external_services.audio.loopback_recorder import LoopbackRecorder
                recorder = LoopbackRecorder(sample_rate=sample_rate, channels=channels)
                start_kwargs = {"system_output_name": self.selected_system_output_name}
            else:
                from infrastructure.external_services.audio.audio_recorder import AudioRecorder
                recorder = AudioRecorder(sample_rate=sample_rate, channels=channels)
                start_kwargs = {
                    "source_type": source_type,
                    "device_index": self.selected_microphone_device,
                }

            try:
                recorder.start_recording(temp_path, **start_kwargs)

                # Сохранить рекордер
                self.translation_recorders[source_type] = recorder
                self.translation_audio_levels[source_type] = 0.0
                
                # Обновить статус
                active_sources = list(self.translation_recorders.keys())
                if len(active_sources) == 1:
                    self.label_translation_status.setText(f"Статус: Запись с {source_name}...")
                else:
                    sources_str = ", ".join(["Собеседник" if s == AudioSourceType.STEREO_MIX else "Микрофон" for s in active_sources])
                    self.label_translation_status.setText(f"Статус: Запись с {sources_str}...")
                
                # Запустить мониторинг уровня звука (если еще не запущен)
                if not self.audio_level_timer.isActive():
                    self.audio_level_timer.start(1000)  # Проверять каждую секунду
                    self.logger.info(f"Мониторинг уровня звука запущен")
                
                self.logger.info(f"Мониторинг уровня звука запущен для {source_name}")
                
                # Обновить текст кнопки
                if source_type == AudioSourceType.STEREO_MIX:
                    self.btn_listen_interlocutor.setText("⏹ Остановить запись")
                else:
                    self.btn_listen_us.setText("⏹ Остановить запись")
            except Exception as e:
                self.logger.error(f"Ошибка начала записи: {str(e)}")
                self.on_error(f"Ошибка начала записи: {str(e)}")
                if source_type in self.translation_recorders:
                    del self.translation_recorders[source_type]
                if source_type in self.translation_audio_levels:
                    del self.translation_audio_levels[source_type]
                if source_type == AudioSourceType.STEREO_MIX:
                    self.btn_listen_interlocutor.setChecked(False)
                else:
                    self.btn_listen_us.setChecked(False)
        else:
            # Остановить запись и обработать
            if source_type in self.translation_recorders:
                self._stop_translation_recording(source_type)
    
    def _stop_translation_recording(self, source_type: AudioSourceType):
        """Остановить запись перевода и обработать"""
        if source_type not in self.translation_recorders:
            return

        source_name = "Собеседник" if source_type == AudioSourceType.STEREO_MIX else "Микрофон"
        recorder = self.translation_recorders[source_type]
        
        try:
            self.logger.info(f"Остановка записи для перевода с {source_name}")
            
            # Обновить статус
            remaining_sources = [s for s in self.translation_recorders.keys() if s != source_type]
            if remaining_sources:
                sources_str = ", ".join(["Собеседник" if s == AudioSourceType.STEREO_MIX else "Микрофон" for s in remaining_sources])
                self.label_translation_status.setText(f"Статус: Запись с {sources_str}... | Обработка {source_name}...")
            else:
                self.label_translation_status.setText(f"Статус: Обработка {source_name}...")
            
            # Уровень звука по последнему чанку (информативно, не критерий ошибки).
            try:
                last_level = recorder.get_audio_level()
                self.logger.info(f"Уровень звука на момент остановки ({source_name}): {last_level:.1f}%")
            except Exception as e:
                self.logger.debug(f"Не удалось вычислить уровень: {e}")
            
            # Остановить запись
            file_path = recorder.stop_recording()
            self.logger.info(f"Запись остановлена, файл: {file_path}")
            
            # Удалить рекордер из словаря
            del self.translation_recorders[source_type]
            if source_type in self.translation_audio_levels:
                del self.translation_audio_levels[source_type]
            
            # Остановить мониторинг уровня звука, если больше нет активных записей
            if not self.translation_recorders:
                self.audio_level_timer.stop()
                self.label_translation_status.setText("Статус: Не записывается")
            
            # Выбрать языки в зависимости от источника
            if source_type == AudioSourceType.STEREO_MIX:
                source_lang = self.stereo_mix_source_language
                target_lang = self.stereo_mix_target_language
            else:  # MICROPHONE
                source_lang = self.microphone_source_language
                target_lang = self.microphone_target_language
            
            # Обработать запись (передать source_type в callback)
            worker = AsyncWorker(
                self.translation_service.translate_from_audio_file(
                    file_path=file_path,
                    source_type=source_type,
                    target_language=target_lang,
                    source_language=source_lang
                )
            )
            # Использовать lambda для передачи source_type в callback
            worker.finished.connect(lambda result, st=source_type: self.on_translation_completed(result, st))
            worker.finished.connect(lambda: self._remove_worker(worker))
            worker.error.connect(self.on_error)
            worker.error.connect(lambda: self._remove_worker(worker))
            self.workers.append(worker)
            worker.start()
            
        except Exception as e:
            self.logger.error(f"Ошибка остановки записи: {str(e)}")
            self.on_error(f"Ошибка остановки записи: {str(e)}")
            # Убедиться, что рекордер удален из словаря
            if source_type in self.translation_recorders:
                del self.translation_recorders[source_type]
            if source_type in self.translation_audio_levels:
                del self.translation_audio_levels[source_type]
        finally:
            # Обновить UI кнопок
            if source_type == AudioSourceType.STEREO_MIX:
                self.btn_listen_interlocutor.setText("Выслушать собеседника")
                self.btn_listen_interlocutor.setChecked(False)
            else:
                self.btn_listen_us.setText("Выслушать нас")
                self.btn_listen_us.setChecked(False)
            
            # Обновить статус, если больше нет активных записей
            if not self.translation_recorders:
                self.label_translation_status.setText("Статус: Не записывается")
    
    def on_translation_completed(self, result, source_type: AudioSourceType):
        """Обработчик завершения перевода с цветовым кодированием"""
        self.logger.info(f"Перевод завершен: {len(result.original_text)} -> {len(result.translated_text)} символов")
        
        from datetime import datetime
        from html import escape
        import re
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # Определить цвет в зависимости от источника
        # Stereo Mix (Выслушать собеседника) - красный
        # Микрофон (Выслушать нас) - зеленый
        if source_type == AudioSourceType.STEREO_MIX:
            text_color = "#DC143C"  # Красный (Crimson)
            source_label = "Собеседник"
        else:
            text_color = "#32CD32"  # Зеленый (LimeGreen)
            source_label = "Мы"
        
        # Экранировать HTML символы
        original_text_escaped = escape(result.original_text)
        translated_text_escaped = escape(result.translated_text)
        
        # Обработать оригинальный текст
        current_html = self.text_original.toHtml()
        # Убрать жирный шрифт из всех существующих сообщений
        current_html = re.sub(r'<b>([^<]*)</b>', r'\1', current_html)
        current_html = re.sub(r'style="font-weight:\s*bold[^"]*"', 'style="margin: 5px 0;"', current_html)
        current_html = re.sub(r'style="[^"]*font-weight:\s*bold[^"]*"', lambda m: m.group(0).replace('font-weight: bold;', '').replace('font-weight:bold;', ''), current_html)
        
        # Добавить новое сообщение с жирным шрифтом и цветом в начало
        new_original_html = f'<div style="font-weight: bold; margin: 5px 0; color: {text_color};"><b>[{timestamp}] [{source_label}]</b> {original_text_escaped}</div>'
        if current_html.strip() and '<body' in current_html:
            current_html = re.sub(r'(<body[^>]*>)', r'\1' + new_original_html + '<br>', current_html, count=1)
        else:
            current_html = f'<html><body>{new_original_html}</body></html>'
        
        self.text_original.setHtml(current_html)
        
        # Обработать переведенный текст
        current_html = self.text_translated.toHtml()
        # Убрать жирный шрифт из всех существующих сообщений
        current_html = re.sub(r'<b>([^<]*)</b>', r'\1', current_html)
        current_html = re.sub(r'style="font-weight:\s*bold[^"]*"', 'style="margin: 5px 0;"', current_html)
        current_html = re.sub(r'style="[^"]*font-weight:\s*bold[^"]*"', lambda m: m.group(0).replace('font-weight: bold;', '').replace('font-weight:bold;', ''), current_html)
        
        # Добавить новое сообщение с жирным шрифтом и цветом в начало
        new_translated_html = f'<div style="font-weight: bold; margin: 5px 0; color: {text_color};"><b>[{timestamp}] [{source_label}]</b> {translated_text_escaped}</div>'
        if current_html.strip() and '<body' in current_html:
            current_html = re.sub(r'(<body[^>]*>)', r'\1' + new_translated_html + '<br>', current_html, count=1)
        else:
            current_html = f'<html><body>{new_translated_html}</body></html>'
        
        self.text_translated.setHtml(current_html)
    
    def on_error(self, error_message: str):
        """Обработчик ошибок"""
        self.logger.error(f"Ошибка: {error_message}", exc_info=True)
        QMessageBox.critical(self, "Ошибка", error_message)
        # Если кнопка ОТЧЁТ была заблокирована перед запросом - вернуть её исходя из состояния
        try:
            self._update_generate_report_enabled()
        except Exception:
            pass

