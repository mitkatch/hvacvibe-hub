"""
HTTP POST publisher.
Sends batches of readings to a REST endpoint as JSON.

POST /api/readings
Body: { "batch": [ {sensor_id, sensor_name, ts, vib_rms, ...}, ... ] }

Response: 200 OK = success, anything else = failure (will retry next cycle).
"""
import json
import logging
import datetime
import urllib.request
import urllib.error

from publisher.base import BasePublisher, PublishRecord, PublishResult

log = logging.getLogger("http_publisher")


class HttpPublisher(BasePublisher):

    def init(self) -> bool:
        endpoint = self._cfg.get("endpoint", "")
        if not endpoint:
            self._last_error = "No endpoint configured"
            log.warning("HTTP publisher: no endpoint configured")
            return False
        log.info(f"HTTP publisher ready → {endpoint}")
        self._connected = True
        return True

    def publish_batch(self, records: list[PublishRecord]) -> PublishResult:
        if not records:
            return PublishResult(success=True, records_sent=0)

        endpoint = self._cfg.get("endpoint", "")
        timeout  = self._cfg.get("timeout", 10)
        headers  = self._cfg.get("headers", {})

        payload  = json.dumps({
            "batch": [r.to_dict() for r in records]
        }).encode("utf-8")

        req = urllib.request.Request(
            url     = endpoint,
            data    = payload,
            method  = "POST",
            headers = {"Content-Type": "application/json", **headers},
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status in (200, 201, 202, 204):
                    self._connected  = True
                    self._last_sent  = datetime.datetime.now()
                    self._last_error = None
                    log.info(f"Published {len(records)} records → HTTP {resp.status}")
                    return PublishResult(success=True, records_sent=len(records))
                else:
                    err = f"HTTP {resp.status}"
                    self._last_error = err
                    log.warning(f"Publish failed: {err}")
                    return PublishResult(success=False, error=err)

        except urllib.error.URLError as e:
            err = str(e.reason)
            self._connected  = False
            self._last_error = err
            log.warning(f"Publish error: {err}")
            return PublishResult(success=False, error=err)

        except Exception as e:
            err = str(e)
            self._connected  = False
            self._last_error = err
            log.warning(f"Publish exception: {err}")
            return PublishResult(success=False, error=err)

    def close(self):
        self._connected = False
        log.info("HTTP publisher closed")
