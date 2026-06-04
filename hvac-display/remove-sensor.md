# Removing a Sensor from HVAC-Vibe

When a sensor is replaced, retired, or re-flashed with a new firmware ID, its
old identity persists in three places: the Mosquitto retained message store,
the SQLite engine database, and the in-memory display state. All three must be
cleared or the ghost sensor will reappear after every restart.

---

## 1. Identify the Sensor ID

Every sensor has a unique ID derived from its BLE MAC address, e.g.
`hvac-vibe-9aa63d`. Find it by listing active MQTT traffic:

```bash
mosquitto_sub -t "hvac/#" -v -C 20
```

Look for lines like:
```
hvac/roof-unit-a4b2c3/hvac-vibe-9aa63d/status {...}
```

The segment between the gateway ID and the topic type is the sensor ID.
Note both the **gateway ID** (`roof-unit-a4b2c3`) and the **sensor ID**
(`hvac-vibe-9aa63d`) — you need both for the commands below.

---

## 2. Stop the Engine (Prevents Re-Publishing)

Stop `hvac-engine` before clearing so it cannot re-publish retained messages
while you work:

```bash
sudo systemctl stop hvac-engine
```

---

## 3. Clear Retained MQTT Messages

Mosquitto stores the last message on each retained topic permanently. Publishing
an empty payload with the retain flag clears it. Run for every topic the sensor
publishes to:

```bash
GATEWAY="roof-unit-a4b2c3"
SENSOR="hvac-vibe-9aa63d"

mosquitto_pub -h localhost -t "hvac/$GATEWAY/$SENSOR/status"                  -n -r
mosquitto_pub -h localhost -t "hvac/$GATEWAY/$SENSOR/alert"                   -n -r
mosquitto_pub -h localhost -t "hvac/$GATEWAY/$SENSOR/environment"             -n -r
mosquitto_pub -h localhost -t "hvac/$GATEWAY/$SENSOR/vibration/features"      -n -r
mosquitto_pub -h localhost -t "hvac/$GATEWAY/$SENSOR/vibration/fft"           -n -r
mosquitto_pub -h localhost -t "hvac/$GATEWAY/$SENSOR/vibration/fft_stats"     -n -r
mosquitto_pub -h localhost -t "hvac/$GATEWAY/$SENSOR/vibration/time_stats"    -n -r
```

### Verify retained messages are gone

```bash
mosquitto_sub -t "hvac/#" -v -C 10
```

The old sensor ID should no longer appear in any message.

---

## 4. Remove from SQLite Database

Find the database location (default `/var/lib/hvac-vibe/engine.db`):

```bash
ls /var/lib/hvac-vibe/engine.db
# or if running from home directory:
ls ~/hvac-engine/engine.db
```

Check what tables exist before running deletes:

```bash
sqlite3 /var/lib/hvac-vibe/engine.db ".tables"
```

Expected tables (names may vary by version):

| Table | Contains |
|---|---|
| `sensors` | Latest state per sensor |
| `history_time` | Per-minute RMS aggregates |
| `history_fft` | Per-burst FFT energies |

Delete the sensor from all tables:

```bash
SENSOR="hvac-vibe-9aa63d"
DB="/var/lib/hvac-vibe/engine.db"

sqlite3 $DB "DELETE FROM sensors     WHERE sensor_id='$SENSOR';"
sqlite3 $DB "DELETE FROM history_time WHERE sensor_id='$SENSOR';"
sqlite3 $DB "DELETE FROM history_fft  WHERE sensor_id='$SENSOR';"
```

### Verify deletion

```bash
sqlite3 $DB "SELECT sensor_id, name FROM sensors;"
```

The old sensor ID should not appear.

---

## 5. Restart Services

Restart both services so the in-memory display state is rebuilt from scratch
without the ghost sensor:

```bash
sudo systemctl start  hvac-engine
sudo systemctl restart hvac-display
```

Wait ~10 seconds for `hvac-engine` to reconnect to BLE and begin publishing,
then verify:

```bash
mosquitto_sub -t "hvac/#" -v -C 10
```

Only the active sensor should appear.

---

## 6. Verify on Dashboard

Open `https://mitkatch.github.io/dashboard/` and confirm:

- Only one sensor card is shown
- Status shows **Connected** with a green dot
- VIB RMS, TEMP, HUMIDITY, PRESSURE tiles show live values
- Chart is plotting data points

---

## Troubleshooting

**Ghost sensor reappears after restart**
The engine restored it from the database. Re-run Step 4 — ensure all three
tables are cleared, not just `sensors`.

**`No such table: history` error**
The table was renamed in a later schema version. Run `.tables` to find the
correct name and substitute it in the DELETE command.

**Retained messages still visible after clearing**
Mosquitto may have persistence enabled — the retain store is saved to disk.
Restart Mosquitto after clearing to flush the on-disk store:
```bash
sudo systemctl restart mosquitto
```

**Sensor reappears with a new ID after re-flash**
A re-flashed XIAO gets a new BLE MAC-derived sensor ID. The old ID is a
separate ghost — follow this guide for the old ID, then let the new ID
register normally.

---

## Quick Reference

```bash
# One-shot removal (substitute your values)
GATEWAY="roof-unit-a4b2c3"
SENSOR="hvac-vibe-9aa63d"
DB="/var/lib/hvac-vibe/engine.db"

sudo systemctl stop hvac-engine

for TOPIC in status alert environment \
             vibration/features vibration/fft \
             vibration/fft_stats vibration/time_stats; do
  mosquitto_pub -h localhost -t "hvac/$GATEWAY/$SENSOR/$TOPIC" -n -r
done

sqlite3 $DB "DELETE FROM sensors      WHERE sensor_id='$SENSOR';"
sqlite3 $DB "DELETE FROM history_time WHERE sensor_id='$SENSOR';"
sqlite3 $DB "DELETE FROM history_fft  WHERE sensor_id='$SENSOR';"

sudo systemctl start   hvac-engine
sudo systemctl restart hvac-display
```
