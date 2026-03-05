"""
Publisher base class — defines the interface all publishers must implement.
Swap transport by changing config CLOUD.publisher without touching other code.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
import datetime


@dataclass
class PublishRecord:
    """One record to publish — transport-agnostic."""
    sensor_id:  str
    sensor_name: str
    ts:         datetime.datetime
    vib_rms:    float
    vib_peak:   float
    temp:       float
    humidity:   float
    battery:    int
    rssi:       int

    def to_dict(self) -> dict:
        return {
            "sensor_id":   self.sensor_id,
            "sensor_name": self.sensor_name,
            "ts":          self.ts.isoformat(),
            "vib_rms":     round(self.vib_rms,  4),
            "vib_peak":    round(self.vib_peak, 4),
            "temp":        round(self.temp,      2),
            "humidity":    round(self.humidity,  2),
            "battery":     self.battery,
            "rssi":        self.rssi,
        }


@dataclass
class PublishResult:
    success:   bool
    records_sent: int = 0
    error:     Optional[str] = None


class BasePublisher(ABC):
    """
    Abstract publisher. All implementations must provide:
      init()           — connect/configure, called once at startup
      publish_batch()  — send a list of records, return result
      status()         — current connection state for display
      close()          — clean shutdown
    """

    def __init__(self, cfg: dict):
        self._cfg        = cfg
        self._connected  = False
        self._last_sent: Optional[datetime.datetime] = None
        self._last_error: Optional[str] = None

    @abstractmethod
    def init(self) -> bool:
        """Initialize connection. Return True if ready."""
        ...

    @abstractmethod
    def publish_batch(self, records: list[PublishRecord]) -> PublishResult:
        """
        Publish a batch of records.
        Must be idempotent — safe to retry on failure.
        """
        ...

    @abstractmethod
    def close(self):
        """Clean up connections."""
        ...

    def status(self) -> dict:
        return {
            "connected":  self._connected,
            "last_sent":  self._last_sent.isoformat() if self._last_sent else None,
            "last_error": self._last_error,
        }
