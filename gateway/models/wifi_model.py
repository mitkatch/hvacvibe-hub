"""
WiFi Model — nmcli wrapper
"""
import subprocess
import asyncio
from models import config_model as cfg


async def scan() -> list[dict]:
    """Return list of {ssid, signal, secured}."""
    try:
        await asyncio.create_subprocess_exec(
            'nmcli', 'dev', 'wifi', 'rescan',
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL)
        await asyncio.sleep(2)

        proc = await asyncio.create_subprocess_exec(
            'nmcli', '-t', '-f', 'SSID,SIGNAL,SECURITY', 'dev', 'wifi', 'list',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL)
        stdout, _ = await proc.communicate()

        nets = {}
        for line in stdout.decode().splitlines():
            parts = line.split(':')
            if len(parts) >= 3 and parts[0]:
                ssid   = parts[0]
                try:    sig = int(parts[1])
                except: sig = 0
                sec    = parts[2] != '--'
                if ssid not in nets or sig > nets[ssid]['signal']:
                    nets[ssid] = {'ssid': ssid, 'signal': sig, 'secured': sec}
        return sorted(nets.values(), key=lambda x: -x['signal'])
    except Exception as e:
        return []


async def connect(ssid: str, password: str) -> dict:
    """Connect to WiFi. Returns {success, message}."""
    try:
        proc = await asyncio.create_subprocess_exec(
            'nmcli', 'dev', 'wifi', 'connect', ssid, 'password', password,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        out = stdout.decode().lower()
        if 'successfully activated' in out:
            c = cfg.load()
            c['wifi']['ssid']      = ssid
            c['wifi']['connected'] = True
            c['wifi']['ip']        = await get_ip()
            cfg.save(c)
            return {'success': True, 'message': f'Connected to {ssid}'}
        else:
            err = stderr.decode().strip() or stdout.decode().strip()
            return {'success': False, 'message': err[:80]}
    except asyncio.TimeoutError:
        return {'success': False, 'message': 'Connection timed out'}
    except Exception as e:
        return {'success': False, 'message': str(e)}


async def get_status() -> dict:
    """Return current WiFi connection status."""
    try:
        proc = await asyncio.create_subprocess_exec(
            'nmcli', '-t', '-f', 'ACTIVE,SSID,SIGNAL', 'dev', 'wifi',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL)
        stdout, _ = await proc.communicate()
        for line in stdout.decode().splitlines():
            if line.startswith('yes:'):
                parts = line.split(':')
                return {
                    'connected': True,
                    'ssid':      parts[1] if len(parts) > 1 else '',
                    'signal':    int(parts[2]) if len(parts) > 2 else 0,
                    'ip':        await get_ip(),
                }
    except Exception:
        pass
    return {'connected': False, 'ssid': '', 'signal': 0, 'ip': ''}


async def get_ip() -> str:
    try:
        proc = await asyncio.create_subprocess_exec(
            'hostname', '-I',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL)
        stdout, _ = await proc.communicate()
        return stdout.decode().split()[0]
    except Exception:
        return ''
