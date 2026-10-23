from setvault_core.services.loudness import BOGUS_LUFS, audio_filter, gain_for


def test_gain_is_target_minus_measured():
    assert gain_for(-8.0, -14.0) == -6.0


def test_gain_is_clamped():
    assert gain_for(-30.0, -14.0) == 10.0
    assert gain_for(0.0, -30.0) == -20.0


def test_gain_is_rounded_to_one_decimal():
    assert gain_for(-8.04, -14.0) == -6.0
    assert gain_for(-8.36, -14.0) == -5.6


def test_bogus_measurement_gives_no_gain():
    assert BOGUS_LUFS == -70.0
    assert gain_for(-70.0, -14.0) == 0.0


def test_missing_measurement_or_target_gives_no_gain():
    assert gain_for(None, -14.0) == 0.0
    assert gain_for(-8.0, None) == 0.0


def test_no_filter_for_zero_gain():
    assert audio_filter(0.0) is None


def test_negative_gain_has_no_limiter():
    f = audio_filter(-6.0)
    assert f == "volume=-6.0dB"
    assert "alimiter" not in f


def test_positive_gain_adds_true_peak_limiter():
    f = audio_filter(4.5)
    assert f == "volume=4.5dB,alimiter=limit=0.891:level=false"
    assert "alimiter=limit=0.891" in f
