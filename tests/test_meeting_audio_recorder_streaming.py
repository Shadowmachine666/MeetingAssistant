"""Тесты потокового движка записи совещания (сведение сырых PCM в WAV).

Проверяют регресс по инциденту 2026-07-11: 4-часовая запись терялась при
сохранении (одиночная запись >2 ГБ → [Errno 22]). Новый движок пишет PCM на
диск по ходу записи и сводит его в WAV поблочно.
"""
import os
import wave

import numpy as np
import pytest

import infrastructure.external_services.audio.meeting_audio_recorder as mar
from infrastructure.external_services.audio.meeting_audio_recorder import (
    MeetingAudioRecorder,
    mix_mono_blocks_to_stereo_int16,
    mix_sources_to_stereo_int16,
)
from core.exceptions.translation_exception import AudioCaptureException


def _write_mono_pcm(path, samples: np.ndarray) -> None:
    with open(path, "wb") as f:
        f.write(samples.astype(np.int16).reshape(-1).tobytes())


def _read_wav_stereo(path):
    with wave.open(path, "rb") as wf:
        assert wf.getnchannels() == 2
        assert wf.getsampwidth() == 2
        frames = wf.readframes(wf.getnframes())
    return np.frombuffer(frames, dtype=np.int16).reshape(-1, 2)


def _make_recorder():
    return MeetingAudioRecorder(sample_rate=44100, channels=2)


def test_block_mixer_matches_list_mixer():
    """Ядро (блочный микшер) эквивалентно списочной обёртке на тех же данных."""
    mic = (np.arange(100, dtype=np.int16) * 100).reshape(-1, 1)
    sys = (np.arange(100, dtype=np.int16) * 50).reshape(-1, 1)
    from_blocks = mix_mono_blocks_to_stereo_int16(mic, sys)
    from_lists = mix_sources_to_stereo_int16([mic], [sys])
    assert np.array_equal(from_blocks, from_lists)


def test_streaming_equals_monolithic(tmp_path, monkeypatch):
    """Поблочное сведение даёт тот же результат, что монолитное (эквивалентность рефакторинга)."""
    # Мелкий блок → заведомо много итераций.
    monkeypatch.setattr(mar, "_MIX_BLOCK_FRAMES", 7)
    rng = np.random.default_rng(0)
    mic = rng.integers(-30000, 30000, size=500).astype(np.int16)
    sys = rng.integers(-30000, 30000, size=500).astype(np.int16)

    mic_raw = str(tmp_path / "a.mic.pcm")
    sys_raw = str(tmp_path / "a.sys.pcm")
    out = str(tmp_path / "a.wav")
    _write_mono_pcm(mic_raw, mic)
    _write_mono_pcm(sys_raw, sys)

    rec = _make_recorder()
    truncated = rec._stream_mix_to_wav(out, mic_raw, sys_raw)
    assert truncated is False

    got = _read_wav_stereo(out)
    expected = mix_sources_to_stereo_int16([mic.reshape(-1, 1)], [sys.reshape(-1, 1)])
    assert np.array_equal(got, expected)


def test_streaming_never_writes_giant_block(tmp_path, monkeypatch):
    """Регресс [Errno 22]: каждая запись в WAV ограничена размером блока, не >2 ГБ."""
    monkeypatch.setattr(mar, "_MIX_BLOCK_FRAMES", 4)
    calls = []
    orig = wave.Wave_write.writeframes

    def spy(self, data):
        calls.append(len(data))
        return orig(self, data)

    monkeypatch.setattr(wave.Wave_write, "writeframes", spy)

    mic = np.ones(50, dtype=np.int16) * 1000
    sys = np.ones(50, dtype=np.int16) * 1000
    mic_raw = str(tmp_path / "b.mic.pcm")
    sys_raw = str(tmp_path / "b.sys.pcm")
    out = str(tmp_path / "b.wav")
    _write_mono_pcm(mic_raw, mic)
    _write_mono_pcm(sys_raw, sys)

    _make_recorder()._stream_mix_to_wav(out, mic_raw, sys_raw)

    max_block_bytes = 4 * 2 * 2  # frames * stereo * int16
    assert calls, "ожидались вызовы writeframes"
    assert all(n <= max_block_bytes for n in calls)


def test_streaming_pads_shorter_source_with_silence(tmp_path):
    """Более короткий источник дополняется тишиной; длина = длине большего."""
    mic = np.ones(10, dtype=np.int16) * 5000  # короче
    sys = np.ones(25, dtype=np.int16) * 5000
    mic_raw = str(tmp_path / "c.mic.pcm")
    sys_raw = str(tmp_path / "c.sys.pcm")
    out = str(tmp_path / "c.wav")
    _write_mono_pcm(mic_raw, mic)
    _write_mono_pcm(sys_raw, sys)

    _make_recorder()._stream_mix_to_wav(out, mic_raw, sys_raw)
    got = _read_wav_stereo(out)
    assert got.shape == (25, 2)
    # Первые 10 кадров: вклад обоих источников; последние — только system, но
    # значение не нулевое (микрофон-тишина + system).
    assert np.all(got[:, 0] > 0)


def test_streaming_truncates_at_wav_limit(tmp_path, monkeypatch):
    """Защита лимита WAV: запись усечена, файл валиден и не превышает предел."""
    monkeypatch.setattr(mar, "_MIX_BLOCK_FRAMES", 8)
    monkeypatch.setattr(mar, "_WAV_MAX_DATA_BYTES", 40)  # 10 стерео-кадров

    mic = np.ones(100, dtype=np.int16) * 1000
    sys = np.ones(100, dtype=np.int16) * 1000
    mic_raw = str(tmp_path / "d.mic.pcm")
    sys_raw = str(tmp_path / "d.sys.pcm")
    out = str(tmp_path / "d.wav")
    _write_mono_pcm(mic_raw, mic)
    _write_mono_pcm(sys_raw, sys)

    truncated = _make_recorder()._stream_mix_to_wav(out, mic_raw, sys_raw)
    assert truncated is True

    got = _read_wav_stereo(out)
    assert got.nbytes <= 40  # не превышает лимит
    with wave.open(out, "rb") as wf:  # файл остаётся валидным/открываемым
        assert wf.getnframes() <= 10


def test_stop_recording_saves_and_cleans_temp(tmp_path):
    """Полный stop_recording: WAV сохранён, временные .pcm удалены при успехе."""
    out = str(tmp_path / "meeting.wav")
    mic_raw = out + ".mic.pcm"
    sys_raw = out + ".sys.pcm"
    _write_mono_pcm(mic_raw, np.ones(200, dtype=np.int16) * 1234)
    _write_mono_pcm(sys_raw, np.ones(200, dtype=np.int16) * 1234)

    rec = _make_recorder()
    rec._output_path = out
    rec._mic_raw_path = mic_raw
    rec._sys_raw_path = sys_raw
    rec.is_recording = True

    result = rec.stop_recording()
    assert result == out
    assert os.path.exists(out)
    assert not os.path.exists(mic_raw)
    assert not os.path.exists(sys_raw)
    assert _read_wav_stereo(out).shape == (200, 2)


def test_stop_recording_keeps_raw_on_save_error(tmp_path, monkeypatch):
    """При ошибке финализации сырые .pcm сохраняются (данные восстановимы)."""
    out = str(tmp_path / "meeting.wav")
    mic_raw = out + ".mic.pcm"
    sys_raw = out + ".sys.pcm"
    _write_mono_pcm(mic_raw, np.ones(50, dtype=np.int16) * 999)
    _write_mono_pcm(sys_raw, np.ones(50, dtype=np.int16) * 999)

    rec = _make_recorder()
    rec._output_path = out
    rec._mic_raw_path = mic_raw
    rec._sys_raw_path = sys_raw
    rec.is_recording = True

    def boom(self, output_path, m, s):
        raise OSError(22, "Invalid argument")

    monkeypatch.setattr(MeetingAudioRecorder, "_stream_mix_to_wav", boom)

    with pytest.raises(AudioCaptureException) as exc:
        rec.stop_recording()
    # Сырые файлы не удалены, путь упомянут в сообщении.
    assert os.path.exists(mic_raw)
    assert os.path.exists(sys_raw)
    assert ".pcm" in str(exc.value)
