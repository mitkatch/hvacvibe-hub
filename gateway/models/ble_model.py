"""
BLE Model — bleak scanner, filters HVACVIBE-* devices
"""
import asyncio
from bleak import BleakScanner
from models import config_model as cfg


async def scan(duration: float = 5.0) -> list[dict]:
    """Scan for HVACVIBE-* BLE devices. Returns list of {name, address, rssi}."""
    found = {}
    def cb(device, adv):
        name = device.name or ''
        if name.upper().startswith('HVACVIBE'):
            found[device.address] = {
                'name':    name,
                'address': device.address,
                'rssi':    adv.rssi,
                'paired':  _is_paired(device.address),
            }
    try:
        async with BleakScanner(detection_callback=cb):
            await asyncio.sleep(duration)
    except Exception as e:
        pass
    return sorted(found.values(), key=lambda x: -x.get('rssi', -99))


def _is_paired(address: str) -> bool:
    c = cfg.load()
    return any(s['address'] == address for s in c.get('ble_sensors', []))


def pair(address: str, name: str) -> dict:
    """Save sensor to config."""
    c = cfg.load()
    sensors = c.get('ble_sensors', [])
    for s in sensors:
        if s['address'] == address:
            s['paired'] = True
            s['name']   = name
            break
    else:
        sensors.append({'name': name, 'address': address, 'paired': True})
    c['ble_sensors'] = sensors
    cfg.save(c)
    return {'success': True, 'message': f'Paired {name}'}


def unpair(address: str) -> dict:
    """Remove sensor from config."""
    c = cfg.load()
    before = len(c.get('ble_sensors', []))
    c['ble_sensors'] = [s for s in c.get('ble_sensors', [])
                        if s['address'] != address]
    cfg.save(c)
    removed = before - len(c['ble_sensors'])
    return {'success': removed > 0, 'message': f'Removed {address}' if removed else 'Not found'}


def get_paired() -> list[dict]:
    c = cfg.load()
    return c.get('ble_sensors', [])
