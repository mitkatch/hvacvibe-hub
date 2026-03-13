"""
MQTT publisher stub.
Same interface as HttpPublisher — swap by setting CLOUD.publisher = "mqtt".
Requires: pip install paho-mqtt
"""
import json
import logging
import datetime

from publisher.base import BasePublisher, PublishRecord, PublishResult

log = logging.getLogger("mqtt_publisher")


class MqttPublisher(BasePublisher):

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self._client = None

    def init(self) -> bool:
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            self._last_error = "paho-mqtt not installed. Run: pip install paho-mqtt"
            log.error(self._last_error)
            return False

        broker   = self._cfg.get("broker",   "localhost")
        port     = self._cfg.get("port",     1883)
        username = self._cfg.get("username", "")
        password = self._cfg.get("password", "")

        self._client = mqtt.Client(client_id="hvacvibe-gateway")
        if username:
            self._client.username_pw_set(username, password)

        self._client.on_connect    = self._on_connect
        self._client.on_disconnect = self._on_disconnect

        try:
            self._client.connect(broker, port, keepalive=60)
            self._client.loop_start()
            log.info(f"MQTT publisher connecting → {broker}:{port}")
            return True
        except Exception as e:
            self._last_error = str(e)
            log.error(f"MQTT connect failed: {e}")
            return False

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self._connected  = True
            self._last_error = None
            log.info("MQTT connected")
        else:
            self._connected  = False
            self._last_error = f"MQTT rc={rc}"
            log.warning(f"MQTT connect error rc={rc}")

    def _on_disconnect(self, client, userdata, rc):
        self._connected = False
        log.warning(f"MQTT disconnected rc={rc}")

    def publish_batch(self, records: list[PublishRecord]) -> PublishResult:
        if not self._client or not self._connected:
            return PublishResult(success=False, error="MQTT not connected")

        topic_fmt = self._cfg.get("topic_fmt", "hvacvibe/{sensor_id}/data")
        qos       = self._cfg.get("qos", 1)
        sent      = 0

        for record in records:
            topic   = topic_fmt.format(sensor_id=record.sensor_id)
            payload = json.dumps(record.to_dict())
            result  = self._client.publish(topic, payload, qos=qos)
            if result.rc == 0:
                sent += 1
            else:
                log.warning(f"MQTT publish failed rc={result.rc} topic={topic}")

        if sent == len(records):
            self._last_sent  = datetime.datetime.now()
            self._last_error = None
            log.info(f"Published {sent} records via MQTT")
            return PublishResult(success=True, records_sent=sent)
        else:
            err = f"Only {sent}/{len(records)} published"
            self._last_error = err
            return PublishResult(success=False, records_sent=sent, error=err)

    def close(self):
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
        self._connected = False
        log.info("MQTT publisher closed")
