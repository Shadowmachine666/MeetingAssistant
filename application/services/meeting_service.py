"""Сервис управления совещаниями"""
import os
from uuid import UUID

from core.exceptions.meeting_exception import (
    MeetingAlreadyStartedException,
    MeetingNotStartedException,
    MeetingNotStoppedException
)
from core.logging.logger import get_logger
from domain.entities.meeting import Meeting
from domain.entities.meeting_recording import MeetingRecording
from domain.interfaces.audio_recorder import IAudioRecorder
from domain.interfaces.meeting_repository import IMeetingRepository
from domain.interfaces.recording_repository import IRecordingRepository
from infrastructure.external_services.openai.openai_client import OpenAIClient
from infrastructure.storage.storage_service import StorageService
from application.services.cost_estimator_service import CostEstimatorService


class MeetingService:
    """Сервис для управления совещаниями"""

    def __init__(self,
                 meeting_repository: IMeetingRepository,
                 recording_repository: IRecordingRepository,
                 audio_recorder: IAudioRecorder,
                 storage_service: StorageService,
                 openai_client: OpenAIClient):
        self.meeting_repository = meeting_repository
        self.recording_repository = recording_repository
        self.audio_recorder = audio_recorder
        self.storage_service = storage_service
        self.openai_client = openai_client
        self.logger = get_logger()

    async def start_meeting(self) -> Meeting:
        """Начать совещание"""
        self.logger.info("Запуск start_meeting")
        current = await self.meeting_repository.get_current()
        if current and current.status.value == "Recording":
            self.logger.warning("Попытка начать совещание, когда уже идет запись")
            raise MeetingAlreadyStartedException("Совещание уже идет")

        meeting = Meeting.create()
        meeting.start()
        await self.meeting_repository.save(meeting)
        self.logger.info(f"Совещание создано: ID={meeting.id}")
        self.logger.info("Запись будет начата с путем из UI")
        return meeting

    async def stop_meeting(self) -> Meeting:
        """Остановить совещание"""
        self.logger.info("Запуск stop_meeting")
        meeting = await self.meeting_repository.get_current()
        if not meeting or meeting.status.value != "Recording":
            self.logger.warning("Попытка остановить совещание, которое не идет")
            raise MeetingNotStartedException("Совещание не идет")

        self.logger.info("Остановка записи...")
        try:
            file_path = self.audio_recorder.stop_recording()
        except Exception as e:
            # Не оставляем совещание в залипшем статусе "Recording": помечаем его
            # остановленным, чтобы пользователь мог начать новую запись. Исходные
            # данные (.pcm) остаются на диске и восстановимы (см. рекордер).
            self.logger.error(f"Ошибка остановки записи: {e}")
            meeting.stop()
            await self.meeting_repository.save(meeting)
            raise
        self.logger.info(f"Запись остановлена, файл: {file_path}")

        file_size = os.path.getsize(file_path)
        bytes_per_sample = 2  # 16-bit PCM
        channels = int(getattr(self.audio_recorder, "channels", 2))
        sample_rate = int(getattr(self.audio_recorder, "sample_rate", 44100))
        duration = file_size / (sample_rate * channels * bytes_per_sample)
        self.logger.info(f"Размер файла: {file_size} байт, примерная длительность: {duration:.1f} сек")

        recording = MeetingRecording.create(
            meeting_id=meeting.id,
            file_path=file_path,
            duration_seconds=duration,
            file_size_bytes=file_size,
            sample_rate=sample_rate,
            channels=channels,
        )
        await self.recording_repository.save(recording)
        self.logger.info(f"Запись сохранена: ID={recording.id}")

        meeting.stop()
        await self.meeting_repository.save(meeting)
        self.logger.info("Совещание остановлено")
        return meeting

    async def attach_transcript(self, meeting_id: UUID, transcript_path: str, transcript_text: str) -> Meeting:
        """Привязать к совещанию готовый текстовый транскрипт (из Colab)."""
        meeting = await self.meeting_repository.get_by_id(meeting_id)
        if not meeting:
            raise MeetingNotStartedException("Совещание не найдено")
        meeting.transcription_path = transcript_path
        await self.meeting_repository.save(meeting)
        self.logger.info(
            f"Транскрипт привязан к совещанию ID={str(meeting_id)[:8]}: {transcript_path} "
            f"({len(transcript_text)} символов)"
        )
        return meeting

    async def process_meeting(self, meeting_id: UUID, target_language: str,
                              template_content: str, transcript_text: str) -> str:
        """Сгенерировать отчёт по готовому транскрипту и шаблону.

        Транскрибация делается отдельно (вручную в Colab) — в приложении остаётся
        только этап «текст + шаблон → GPT».
        """
        meeting_id_str = str(meeting_id)[:8]
        self.logger.info(f"Обработка совещания: ID={meeting_id_str}, язык={target_language}")

        meeting = await self.meeting_repository.get_by_id(meeting_id)
        if not meeting:
            raise MeetingNotStartedException("Совещание не найдено")
        if meeting.status.value not in ("Stopped", "Completed"):
            raise MeetingNotStoppedException("Совещание должно быть остановлено")
        if not transcript_text or not transcript_text.strip():
            raise MeetingNotStoppedException("Не загружен текст транскрипта")

        meeting.mark_processing()
        await self.meeting_repository.save(meeting)

        template_len = len(template_content) if template_content else 0
        estimator = CostEstimatorService()
        token_est = estimator.estimate(
            input_text=f"{template_content}\n\n{transcript_text}",
            expected_output_tokens=int(getattr(self.openai_client, "max_tokens", 4000)),
        )
        self.logger.info(
            f"[Совещание ID={meeting_id_str}] Оценка токенов: "
            f"input={token_est.input_tokens}, output={token_est.output_tokens}, total={token_est.total_tokens}"
        )
        self.logger.info(
            f"[Совещание ID={meeting_id_str}] Генерация отчёта на '{target_language}', "
            f"шаблон: {template_len} символов, транскрипт: {len(transcript_text)} символов"
        )

        report_content = await self.openai_client.generate_report(
            transcription=transcript_text,
            template=template_content,
            language=target_language,
            is_multipart=False,
        )
        self.logger.info(
            f"[Совещание ID={meeting_id_str}] Отчёт сгенерирован, длина: {len(report_content)} символов"
        )

        report_path = self.storage_service.save_report(str(meeting_id), report_content)
        meeting.report_path = report_path
        self.logger.info(f"Отчёт сохранён: {report_path}")

        final_json_payload = {
            "report": report_content,
            "meeting_id": str(meeting_id),
            "language": target_language,
        }
        try:
            import json
            parsed = json.loads(report_content)
            final_json_payload = parsed if isinstance(parsed, dict) else {"report": parsed}
        except Exception:
            pass
        final_json_path = self.storage_service.save_final_report_json(str(meeting_id), final_json_payload)
        self.logger.info(f"final_report.json сохранён: {final_json_path}")

        meeting.mark_completed()
        await self.meeting_repository.save(meeting)
        self.logger.info("Обработка совещания завершена")
        return report_content
