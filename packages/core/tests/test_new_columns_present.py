from setvault_core.models.ingest_sources import IngestSourceState
from setvault_core.models.system_config import SystemConfig


def test_ingest_source_state_has_rate_limit_columns():
    cols = IngestSourceState.__table__.columns
    assert "rate_limit_max" in cols
    assert "rate_limit_window_seconds" in cols


def test_system_config_has_monitor_settings():
    cols = SystemConfig.__table__.columns
    assert "monitors_allow_all_users" in cols
    assert "monitor_interval_seconds" in cols


def test_p2a_columns_present():
    from setvault_core.models.catalog import LiveSet
    from setvault_core.models.monitors import Monitor

    assert {"catalog_kind", "catalog_id"} <= set(Monitor.__table__.columns.keys())
    assert "ix_monitors_catalog" in {i.name for i in Monitor.__table__.indexes}
    assert {
        "loudness_target_lufs", "backup_enabled", "backup_time", "backup_keep",
        "backup_dir", "last_backup_at", "last_backup_status", "last_backup_error",
        "last_backup_bytes",
    } <= set(SystemConfig.__table__.columns.keys())
    assert "stream_gain_db" in LiveSet.__table__.columns
