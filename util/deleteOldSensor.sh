#!/bin/bash
# deleteOldSensor.sh
# Removes a sensor and all its associated history from the HVAC-Vibe SQLite database.
# Usage: ./deleteOldSensor.sh <sensor_mac>
# Example: ./deleteOldSensor.sh AA:BB:CC:DD:EE:FF

set -e

DB="${HVAC_DB:-/home/pi/hvac-engine/hvac.db}"

# ---- args ----
if [ -z "$1" ]; then
  echo "Usage: $0 <sensor_mac>"
  echo "       e.g. $0 AA:BB:CC:DD:EE:FF"
  echo ""
  echo "List of sensors currently in DB:"
  sqlite3 "$DB" "SELECT sensor_id, name, last_seen FROM sensors;"
  exit 1
fi

MAC="$1"

# ---- confirm sensor exists ----
ROW=$(sqlite3 "$DB" "SELECT sensor_id, name, last_seen FROM sensors WHERE sensor_id='$MAC';")
if [ -z "$ROW" ]; then
  echo "ERROR: No sensor found with MAC '$MAC' in $DB"
  echo ""
  echo "Sensors currently in DB:"
  sqlite3 "$DB" "SELECT sensor_id, name, last_seen FROM sensors;"
  exit 1
fi

echo ""
echo "Sensor found:"
echo "  $ROW" | column -t -s '|'
echo ""

# ---- show row counts about to be deleted ----
echo "Records that will be deleted:"
for TABLE in history_time history_fft history_spectrum; do
  COUNT=$(sqlite3 "$DB" "SELECT COUNT(*) FROM $TABLE WHERE sensor_id='$MAC';" 2>/dev/null || echo "table not found")
  printf "  %-20s %s rows\n" "$TABLE" "$COUNT"
done
echo ""

# ---- confirm ----
read -rp "Delete sensor '$MAC' and all its history? [y/N]: " CONFIRM
if [[ "$CONFIRM" != "y" && "$CONFIRM" != "Y" ]]; then
  echo "Aborted — nothing deleted."
  exit 0
fi

# ---- delete ----
echo ""
echo "Deleting..."

sqlite3 "$DB" <<SQL
BEGIN;

DELETE FROM history_time      WHERE sensor_id='$MAC';
DELETE FROM history_fft       WHERE sensor_id='$MAC';
DELETE FROM history_spectrum  WHERE sensor_id='$MAC';
DELETE FROM sensors           WHERE sensor_id='$MAC';

COMMIT;
SQL

echo "Done. Rows remaining in sensors table:"
sqlite3 "$DB" "SELECT sensor_id, name, last_seen FROM sensors;"
