/* ============================================================
   setup.js  —  Setup screen: WiFi, BLE, Status tabs
   ============================================================ */

const Setup = (() => {

  // ── State ──────────────────────────────────────────────────
  let currentTab     = 'wifi';
  let wifiNetworks   = [];
  let bleDevices     = [];
  let selectedSSID   = null;
  let kbdText        = '';
  let kbdMode        = 'lower';   // lower | upper | num
  let systemStatus   = { wifi: {}, sensors: [] };

  // ── Keyboard layouts ───────────────────────────────────────
  const LAYOUTS = {
    lower: [
      ['q','w','e','r','t','y','u','i','o','p'],
      ['a','s','d','f','g','h','j','k','l'],
      ['SHF','z','x','c','v','b','n','m','DEL'],
      ['123','@','.','SPACE','OK'],
    ],
    upper: [
      ['Q','W','E','R','T','Y','U','I','O','P'],
      ['A','S','D','F','G','H','J','K','L'],
      ['shf','Z','X','C','V','B','N','M','DEL'],
      ['123','@','.','SPACE','OK'],
    ],
    num: [
      ['1','2','3','4','5','6','7','8','9','0'],
      ['-','_','!','@','#','$','%','&','*','DEL'],
      ['.', ',', '=', '+', '[', ']', '(', ')', ';', ':'],
      ['ABC','SPACE','OK'],
    ],
  };

  // ── Tab switching ──────────────────────────────────────────
  function switchTab(name) {
    currentTab = name;
    document.querySelectorAll('.tab').forEach(el =>
      el.classList.toggle('active', el.dataset.tab === name));
    document.querySelectorAll('.tab-content').forEach(el =>
      el.classList.toggle('active', el.id === `tab-${name}`));
    if (name === 'status') refreshStatus();
  }

  // ── WiFi ───────────────────────────────────────────────────
  function wifiScan() {
    setWifiStatus('Scanning...', 'warn');
    document.getElementById('wifi-list').innerHTML = '<div class="list-empty">Scanning...</div>';
    App.send({ cmd: 'wifi_scan' });
  }

  function renderWifiList(networks) {
    wifiNetworks = networks;
    const list = document.getElementById('wifi-list');
    if (!networks.length) {
      list.innerHTML = '<div class="list-empty">No networks found</div>';
      return;
    }
    list.innerHTML = networks.map((n, i) => {
      const bars    = Math.max(1, Math.min(4, Math.round(n.signal / 25)));
      const barHtml = [3,6,9,12].map((h, b) =>
        `<span class="${b < bars ? 'on' : ''}" style="height:${h}px"></span>`).join('');
      const isConn  = systemStatus.wifi?.ssid === n.ssid && systemStatus.wifi?.connected;
      const lock    = n.secured ? '🔒' : '';
      return `
        <div class="wifi-row" onclick="Setup.wifiSelect(${i})">
          <span class="w-ssid ${isConn ? 'connected' : ''}">${escHtml(n.ssid)}</span>
          ${isConn ? '<span class="w-check">✓</span>' : ''}
          <span class="w-lock">${lock}</span>
          <span class="w-bars">${barHtml}</span>
        </div>`;
    }).join('');
  }

  function wifiSelect(idx) {
    selectedSSID = wifiNetworks[idx].ssid;
    const secured = wifiNetworks[idx].secured;
    if (!secured) {
      // open network — connect directly
      App.send({ cmd: 'wifi_connect', ssid: selectedSSID, password: '' });
      setWifiStatus(`Connecting to ${selectedSSID}...`, 'warn');
      return;
    }
    // show keyboard
    kbdText = '';
    kbdMode = 'lower';
    document.getElementById('kbd-ssid-label').textContent = selectedSSID;
    updateKbdDisplay();
    buildKeyboard();
    document.getElementById('keyboard-overlay').classList.remove('hidden');
  }

  // ── Keyboard ───────────────────────────────────────────────
  function buildKeyboard() {
    const kbd  = document.getElementById('keyboard');
    const rows = LAYOUTS[kbdMode];
    kbd.innerHTML = rows.map(row => {
      const keys = row.map(k => {
        let cls = 'kbd-key';
        let lbl = k;
        if (k === 'SPACE')  { cls += ' key-space'; lbl = ''; }
        if (k === 'OK')     { cls += ' key-ok'; }
        if (['SHF','shf','DEL','123','ABC'].includes(k)) cls += ' special';
        const disp = {SHF:'⇧', shf:'⇧', DEL:'⌫', SPACE:'', '123':'123', ABC:'ABC'};
        lbl = disp[k] !== undefined ? disp[k] : k;
        return `<button class="${cls}" ontouchstart="Setup.kbdPress('${k}')" onclick="Setup.kbdPress('${k}')">${lbl}</button>`;
      }).join('');
      return `<div class="kbd-row">${keys}</div>`;
    }).join('');
  }

  function kbdPress(key) {
    if (key === 'DEL')  { kbdText = kbdText.slice(0, -1); }
    else if (key === 'SPACE') { kbdText += ' '; }
    else if (key === 'SHF')  { kbdMode = 'upper'; buildKeyboard(); return; }
    else if (key === 'shf')  { kbdMode = 'lower'; buildKeyboard(); return; }
    else if (key === '123')  { kbdMode = 'num';   buildKeyboard(); return; }
    else if (key === 'ABC')  { kbdMode = 'lower'; buildKeyboard(); return; }
    else if (key === 'OK') {
      document.getElementById('keyboard-overlay').classList.add('hidden');
      App.send({ cmd: 'wifi_connect', ssid: selectedSSID, password: kbdText });
      setWifiStatus(`Connecting to ${selectedSSID}...`, 'warn');
      return;
    } else {
      kbdText += key;
      if (kbdMode === 'upper') { kbdMode = 'lower'; buildKeyboard(); }
    }
    updateKbdDisplay();
  }

  function updateKbdDisplay() {
    const el = document.getElementById('kbd-input-display');
    if (el) el.textContent = '*'.repeat(kbdText.length);
  }

  // ── BLE ────────────────────────────────────────────────────
  function bleScan() {
    setBleStatus('Scanning for HVACVIBE-* ...', 'warn');
    document.getElementById('ble-list').innerHTML = '<div class="list-empty">Scanning... (5s)</div>';
    App.send({ cmd: 'ble_scan' });
  }

  function renderBleList(devices) {
    bleDevices = devices;
    const list = document.getElementById('ble-list');
    if (!devices.length) {
      list.innerHTML = '<div class="list-empty">No HVACVIBE sensors found</div>';
      return;
    }
    list.innerHTML = devices.map((d, i) => `
      <div class="ble-row ${d.paired ? 'paired' : ''}">
        <div class="b-info">
          <div class="b-name">${escHtml(d.name)}</div>
          <div class="b-addr">${d.address} &nbsp;<span class="b-rssi">${d.rssi}dBm</span></div>
        </div>
        ${d.paired
          ? `<button class="btn-unpair" onclick="Setup.bleUnpair('${d.address}')">Unpair</button>`
          : `<button class="btn-pair"   onclick="Setup.blePair('${d.address}','${escHtml(d.name)}')">Pair</button>`
        }
      </div>`).join('');
  }

  function blePair(address, name) {
    App.send({ cmd: 'ble_pair', address, name });
  }

  function bleUnpair(address) {
    App.send({ cmd: 'ble_unpair', address });
  }

  // ── Status tab ─────────────────────────────────────────────
  function refreshStatus() {
    App.send({ cmd: 'get_status' });
  }

  function renderStatus(data) {
    systemStatus = data;

    // WiFi
    const wRow = document.getElementById('status-wifi');
    if (wRow) {
      const w = data.wifi || {};
      if (w.connected) {
        wRow.innerHTML = `
          <span class="status-dot green"></span>
          <div>
            <div class="status-text">${escHtml(w.ssid || '')}</div>
            <div class="status-sub">IP: ${w.ip || '—'}  &nbsp; Signal: ${w.signal || '—'}%</div>
          </div>`;
      } else {
        wRow.innerHTML = `
          <span class="status-dot red"></span>
          <span class="status-text">Not connected</span>`;
      }
    }

    // BLE
    const bList = document.getElementById('status-ble-list');
    if (bList) {
      const sensors = data.sensors || [];
      if (!sensors.length) {
        bList.innerHTML = '<div class="status-sub">No sensors configured</div>';
      } else {
        bList.innerHTML = sensors.map(s => `
          <div class="status-row">
            <span class="status-dot ${s.paired ? 'green' : 'grey'}"></span>
            <div>
              <div class="status-text">${escHtml(s.name)}</div>
              <div class="status-sub">${s.address}</div>
            </div>
          </div>`).join('');
      }
    }
  }

  // ── Message listeners ──────────────────────────────────────
  window.addEventListener('DOMContentLoaded', () => {
    App.on('wifi_scan_result', msg => {
      renderWifiList(msg.data.networks || []);
      setWifiStatus(`Found ${(msg.data.networks||[]).length} networks`, '');
    });

    App.on('ble_scan_result', msg => {
      renderBleList(msg.data.devices || []);
      setBleStatus(`Found ${(msg.data.devices||[]).length} sensor(s)`, '');
    });

    App.on('system_status', msg => {
      renderStatus(msg.data);
      // refresh wifi list connected state
      if (wifiNetworks.length) renderWifiList(wifiNetworks);
      // refresh ble list paired state
      if (bleDevices.length) {
        const pairedAddrs = new Set((msg.data.sensors||[]).map(s => s.address));
        bleDevices.forEach(d => d.paired = pairedAddrs.has(d.address));
        renderBleList(bleDevices);
      }
    });

    App.on('cmd_result', msg => {
      if (msg.cmd === 'wifi_connect') {
        setWifiStatus(msg.message, msg.success ? 'ok' : 'err');
      }
      if (msg.cmd === 'ble_pair' || msg.cmd === 'ble_unpair') {
        setBleStatus(msg.message, msg.success ? 'ok' : 'err');
      }
    });

    App.on('cmd_ack', msg => {
      if (msg.cmd === 'wifi_scan')    setWifiStatus('Scanning...', 'warn');
      if (msg.cmd === 'ble_scan')     setBleStatus('Scanning... (5s)', 'warn');
      if (msg.cmd === 'wifi_connect') setWifiStatus(`Connecting...`, 'warn');
    });
  });

  // ── Helpers ────────────────────────────────────────────────
  function setWifiStatus(msg, cls) {
    const el = document.getElementById('wifi-status');
    if (!el) return;
    el.textContent  = msg;
    el.className    = `status-msg ${cls}`;
  }

  function setBleStatus(msg, cls) {
    const el = document.getElementById('ble-status');
    if (!el) return;
    el.textContent = msg;
    el.className   = `status-msg ${cls}`;
  }

  function escHtml(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  return { switchTab, wifiScan, wifiSelect, kbdPress, bleScan, blePair, bleUnpair };
})();
