#!/usr/bin/env bash
# init_db.sh — Create a fresh engine.db with the full schema.
#
# Usage:
#   cd ~/hvac-engine
#   bash init_db.sh
#   bash init_db.sh /custom/path/engine.db
#
# IMPORTANT: Deletes engine.db AND sidecar files (-shm, -wal) if they exist.

set -euo pipefail

DB="${1:-$(dirname "$0")/engine.db}"

# Remove existing DB and WAL sidecar files together — never delete one without the others
if [[ -f "$DB" ]]; then
    echo "Removing existing: $DB (and sidecars)"
    rm -f "$DB" "${DB}-shm" "${DB}-wal"
fi

echo "Creating $DB ..."

sqlite3 "$DB" <<'SQL'

-- ── sensors: one row per sensor, live state ───────────────────────────────
CREATE TABLE sensors (
    sensor_id    TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    address      TEXT NOT NULL,
    connected    INTEGER DEFAULT 0,
    -- Time-domain
    vib_rms      REAL    DEFAULT 0,
    vib_peak     REAL    DEFAULT 0,
    dominant_hz  REAL    DEFAULT 0,
    alarm        INTEGER DEFAULT 0,
    warn         INTEGER DEFAULT 0,
    crest_x      REAL    DEFAULT 0,
    crest_y      REAL    DEFAULT 0,
    crest_z      REAL    DEFAULT 0,
    kurtosis_x   REAL    DEFAULT 0,
    kurtosis_y   REAL    DEFAULT 0,
    kurtosis_z   REAL    DEFAULT 0,
    -- FFT (last burst values)
    x_bpfo       REAL    DEFAULT 0,
    x_bpfi       REAL    DEFAULT 0,
    x_bsf        REAL    DEFAULT 0,
    x_ftf        REAL    DEFAULT 0,
    x_snr_bpfo   REAL    DEFAULT 0,
    max_snr_bpfo REAL    DEFAULT 0,
    -- Environmental
    temp_c       REAL    DEFAULT 0,
    humidity     REAL    DEFAULT 0,
    pressure     INTEGER DEFAULT 0,
    -- Device
    battery      INTEGER DEFAULT 0,
    rssi         INTEGER DEFAULT -99,
    last_seen    REAL    DEFAULT 0,
    updated_at   TEXT    DEFAULT (datetime('now'))
);

-- ── history_time: per-minute time-domain aggregates ───────────────────────
-- One row per sensor per minute (last-write-wins within the minute).
-- Written by PKT_TYPE_TIME_STATS path independently of FFT.
CREATE TABLE history_time (
    sensor_id     TEXT    NOT NULL,
    minute_of_day INTEGER NOT NULL,   -- 0-1439
    date          TEXT    NOT NULL,   -- YYYY-MM-DD
    -- Vibration summary
    vib_rms       REAL,
    vib_peak      REAL,
    dominant_hz   REAL,
    -- Time-domain features
    crest_x       REAL,
    crest_y       REAL,
    crest_z       REAL,
    kurtosis_x    REAL,               -- 3.0=normal, >4=early fault, >10=severe
    kurtosis_y    REAL,
    kurtosis_z    REAL,
    -- Environmental snapshot
    temp_c        REAL,
    humidity      REAL,
    -- Alarm state
    alarm         INTEGER DEFAULT 0,
    warn          INTEGER DEFAULT 0,
    -- Cloud sync flag (0=pending upload to S3)
    synced        INTEGER DEFAULT 0,
    PRIMARY KEY (sensor_id, date, minute_of_day)
);

-- ── history_fft: per-burst FFT fault features ─────────────────────────────
-- One row per burst (unix timestamp resolution).
-- Written by PKT_TYPE_FFT_STATS path independently of time_stats.
-- Join to history_time via (sensor_id, date, minute_of_day).
CREATE TABLE history_fft (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    sensor_id     TEXT    NOT NULL,
    ts            INTEGER NOT NULL,   -- unix timestamp (seconds)
    date          TEXT    NOT NULL,   -- YYYY-MM-DD
    minute_of_day INTEGER NOT NULL,   -- 0-1439 (for JOIN with history_time)
    seq           INTEGER,            -- firmware burst seq number
    -- Bearing fault energies (x-axis dominant)
    x_bpfo        REAL,               -- Ball Pass Freq Outer race
    x_bpfi        REAL,               -- Ball Pass Freq Inner race
    x_bsf         REAL,               -- Ball Spin Frequency
    x_ftf         REAL,               -- Fundamental Train Frequency
    x_snr_bpfo    REAL,               -- SNR at BPFO bin (>2.0 = outer race suspect)
    max_snr_bpfo  REAL,               -- max SNR across all 3 axes
    -- Cloud sync flag
    synced        INTEGER DEFAULT 0
);

-- ── indexes ───────────────────────────────────────────────────────────────
CREATE INDEX idx_time_sensor_date ON history_time(sensor_id, date);
CREATE INDEX idx_time_unsynced    ON history_time(synced, date);
CREATE INDEX idx_fft_sensor_date  ON history_fft(sensor_id, date);
CREATE INDEX idx_fft_ts           ON history_fft(sensor_id, ts);
CREATE INDEX idx_fft_unsynced     ON history_fft(synced, date);

SQL

# WAL mode must be set outside DDL transaction
sqlite3 "$DB" "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;"

echo ""
echo "Tables created:"
sqlite3 "$DB" "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
echo ""
echo "WAL mode:"
sqlite3 "$DB" "PRAGMA journal_mode;"
echo ""
echo "Done. $DB is ready."
