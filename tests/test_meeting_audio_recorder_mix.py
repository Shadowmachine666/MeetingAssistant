import numpy as np

from infrastructure.external_services.audio.meeting_audio_recorder import mix_sources_to_stereo_int16


def test_mix_empty_returns_empty_stereo():
    mixed = mix_sources_to_stereo_int16([], [])
    assert mixed.dtype == np.int16
    assert mixed.shape == (0, 2)


def test_mix_aligns_lengths_and_outputs_stereo():
    mic = [np.ones((3, 1), dtype=np.int16) * 1000]
    sys = [np.ones((5, 1), dtype=np.int16) * 2000]
    mixed = mix_sources_to_stereo_int16(mic, sys)
    assert mixed.shape == (5, 2)
    # первые 3 сэмпла должны содержать вклад обоих источников
    assert np.all(mixed[:3, 0] > 0)
    # последние 2 сэмпла: микрофон дополняется тишиной, остаётся вклад system
    assert np.all(mixed[3:, 0] > 0)
    # стерео-каналы одинаковые (дублирование моно)
    assert np.array_equal(mixed[:, 0], mixed[:, 1])


def test_mix_applies_gains():
    mic = [np.ones((4, 1), dtype=np.int16) * 1000]
    sys = [np.ones((4, 1), dtype=np.int16) * 1000]
    mixed_mic_only = mix_sources_to_stereo_int16(mic, sys, microphone_gain=1.0, system_gain=0.0)
    mixed_both = mix_sources_to_stereo_int16(mic, sys, microphone_gain=1.0, system_gain=1.0)
    assert np.all(mixed_both[:, 0] > mixed_mic_only[:, 0])


def test_mix_clips_to_int16_range():
    # Сумма должна клиппироваться, а не переполняться.
    max_int16 = np.iinfo(np.int16).max
    mic = [np.ones((10, 1), dtype=np.int16) * max_int16]
    sys = [np.ones((10, 1), dtype=np.int16) * max_int16]
    mixed = mix_sources_to_stereo_int16(mic, sys, microphone_gain=2.0, system_gain=2.0)
    assert mixed.shape == (10, 2)
    assert mixed.max() == max_int16
