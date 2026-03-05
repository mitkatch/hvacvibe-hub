"""
Publisher factory — returns the configured publisher instance.
Change CLOUD.publisher in config.py to swap transport.
"""
from publisher.base import BasePublisher


def get_publisher(cloud_cfg: dict) -> BasePublisher:
    kind = cloud_cfg.get("publisher", "http").lower()

    if kind == "http":
        from publisher.http_publisher import HttpPublisher
        return HttpPublisher(cloud_cfg["http"])

    elif kind == "mqtt":
        from publisher.mqtt_publisher import MqttPublisher
        return MqttPublisher(cloud_cfg["mqtt"])

    else:
        raise ValueError(f"Unknown publisher type: {kind!r}. Use 'http' or 'mqtt'.")
