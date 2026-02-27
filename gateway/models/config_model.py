"""
Config Model — load/save /etc/hvacvibe/config.json
"""
import json
import os
import subprocess
import tempfile

#CONFIG_PATH = '/etc/hvacvibe/config.json'
import platform
CONFIG_PATH = (r'C:\hvacvibe\config.json' if platform.system() == 'Windows'
               else '/etc/hvacvibe/config.json')

DEFAULT = {
    "wifi": {"ssid": "", "connected": False, "ip": ""},
    "ble_sensors": [],          # [{name, address, paired}]
    "alarm_threshold": 0.6,
}

def load() -> dict:
    try:
        with open(CONFIG_PATH) as f:
            data = json.load(f)
        for k, v in DEFAULT.items():
            data.setdefault(k, v)
        return data
    except Exception:
        return dict(DEFAULT)

def save(cfg: dict) -> bool:
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, 'w') as f:
            json.dump(cfg, f, indent=2)
        return True
    except PermissionError:
        tmp = tempfile.mktemp(suffix='.json')
        try:
            with open(tmp, 'w') as f:
                json.dump(cfg, f, indent=2)
            subprocess.run(['sudo', 'cp', tmp, CONFIG_PATH], check=True)
            subprocess.run(['sudo', 'chmod', '644', CONFIG_PATH], check=True)
            return True
        except Exception:
            return False
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    except Exception:
        return False
