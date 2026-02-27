/* ============================================================
   dashboard.js  —  Live dashboard: tiles + Canvas chart
   ============================================================ */

const Dashboard = (() => {

  // ── DOM refs (resolved after DOMContentLoaded) ─────────────
  let canvas, ctx;
  let chartW, chartH;

  // ── State ──────────────────────────────────────────────────
  let sensorData = null;
  const MINUTES  = 1440;   // 00:00 → 23:59

  // ── Init ───────────────────────────────────────────────────
  window.addEventListener('DOMContentLoaded', () => {
    canvas = document.getElementById('chart-canvas');
    if (!canvas) return;
    ctx = canvas.getContext('2d');

    // Size canvas to its CSS container — defer to after layout paint
    // Scale by devicePixelRatio to fix blurry text on HiDPI/scaled displays
    function resize() {
      const wrap = canvas.parentElement;
      const w = wrap.clientWidth  || wrap.offsetWidth;
      const h = wrap.clientHeight || wrap.offsetHeight;
      if (w > 0 && h > 0) {
        const dpr = window.devicePixelRatio || 1;
        canvas.width  = w * dpr;
        canvas.height = h * dpr;
        canvas.style.width  = w + 'px';
        canvas.style.height = h + 'px';
        ctx.scale(dpr, dpr);
        chartW = w;
        chartH = h;
        if (sensorData) renderChart(sensorData);
      }
    }
    // Try immediately, then again after paint to catch flex-resolved sizes
    resize();
    requestAnimationFrame(() => { resize(); });
    setTimeout(resize, 100);
    window.addEventListener('resize', resize);

    // Listen for sensor updates
    App.on('sensor_update', msg => {
      sensorData = msg.data;
      updateTiles(msg.data);
      renderChart(msg.data);
    });
  });

  // ── Tile updates ───────────────────────────────────────────
  function updateTiles(d) {
    setText('val-rms',  d.vib_rms.toFixed(3));
    setText('val-peak', d.vib_peak.toFixed(2));
    setText('val-temp', d.temp.toFixed(1));
    setText('val-hum',  d.humidity.toFixed(1));

    // Alarm
    const badge = document.getElementById('alarm-badge');
    const clock = document.getElementById('clock');
    if (d.alarm) {
      badge && badge.classList.remove('hidden');
      clock && clock.classList.add('hidden');
      document.getElementById('tile-rms')
              .querySelector('.tile-value').style.color = 'var(--red)';
    } else {
      badge && badge.classList.add('hidden');
      clock && clock.classList.remove('hidden');
      document.getElementById('tile-rms')
              .querySelector('.tile-value').style.color = 'var(--accent)';
    }

    // Connection dot
    const dot   = document.getElementById('conn-dot');
    const label = document.getElementById('conn-label');
    if (d.connected) {
      if (dot) dot.className = 'conn-dot connected';
      if (label) label.textContent = 'Connected';
      if (label) label.style.color = 'var(--green)';
    } else {
      if (dot) dot.className = 'conn-dot disconnected';
      if (label) label.textContent = 'No Signal';
      if (label) label.style.color = 'var(--red)';
    }

    // Signal bars
    const bars = rssiToBars(d.rssi);
    document.querySelectorAll('.signal-bars .bar').forEach((el, i) => {
      el.classList.toggle('on', i < bars);
    });
    setText('rssi-val', `${d.rssi}dBm`);

    // Battery
    const pct    = d.battery;
    const fill   = document.getElementById('bat-fill');
    const batPct = document.getElementById('bat-pct');
    if (fill) {
      fill.style.width      = `${pct}%`;
      fill.style.background = pct > 50 ? 'var(--green)' : pct > 20 ? 'var(--yellow)' : 'var(--red)';
    }
    if (batPct) {
      batPct.textContent  = `${pct}%`;
      batPct.style.color  = pct > 50 ? 'var(--green)' : pct > 20 ? 'var(--yellow)' : 'var(--red)';
    }

    // Y-axis labels
    updateYAxis(d.history);
  }

  function updateYAxis(history) {
    const yMax  = computeYMax(history.map(p => Array.isArray(p) ? p[1] : p));
    const el    = document.getElementById('chart-yaxis');
    if (!el) return;
    el.innerHTML = '';
    for (let i = 4; i >= 0; i--) {
      const v    = (yMax * i / 4).toFixed(2);
      const span = document.createElement('span');
      span.textContent = v;
      el.appendChild(span);
    }
  }

  // ── Chart ──────────────────────────────────────────────────
  function renderChart(d) {
    if (!ctx || !chartW || !chartH) return;

    const history = d.history || [];   // [[minute, rms], ...]
    const now     = new Date();
    const curMin  = now.getHours() * 60 + now.getMinutes();

    const PAD_T = 20, PAD_B = 18, PAD_L = 6, PAD_R = 8;
    const pw = chartW - PAD_L - PAD_R;
    const ph = chartH - PAD_T - PAD_B;
    const px = PAD_L;
    const py = PAD_T;

    const yMax = computeYMax(history.map(p => p[1]));

    ctx.clearRect(0, 0, chartW, chartH);

    // ---- Title ----
    ctx.fillStyle = '#64707d';
    ctx.font      = '10px Courier New';
    ctx.fillText(`VIB RMS — ${now.toLocaleDateString()}`, px + 4, 12);

    // ---- Grid lines + X-axis labels ----
    const timeLabels = [[0,'00:00'],[360,'06:00'],[720,'12:00'],[1080,'18:00'],[1439,'24:00']];
    ctx.strokeStyle = '#232f3a';
    ctx.lineWidth   = 1;

    for (let i = 0; i <= 4; i++) {
      const gy = py + ph - Math.round(ph * i / 4);
      ctx.beginPath(); ctx.moveTo(px, gy); ctx.lineTo(px + pw, gy); ctx.stroke();
    }

    ctx.fillStyle = '#64707d';
    ctx.font      = '10px Courier New';
    timeLabels.forEach(([min, label]) => {
      const lx = px + Math.round(min * pw / (MINUTES - 1));
      ctx.beginPath(); ctx.moveTo(lx, py + ph); ctx.lineTo(lx, py + ph + 3); ctx.stroke();
      const tw = ctx.measureText(label).width;
      const fx = Math.max(px, Math.min(lx - tw / 2, px + pw - tw));
      ctx.fillText(label, fx, chartH - 3);
    });

    // ---- Alarm threshold ----
    const thresh = 0.6;
    if (thresh <= yMax) {
      const ay = py + ph - Math.round(ph * thresh / yMax);
      ctx.strokeStyle = 'rgba(220,50,50,0.7)';
      ctx.lineWidth   = 1;
      ctx.setLineDash([4, 3]);
      ctx.beginPath(); ctx.moveTo(px, ay); ctx.lineTo(px + pw, ay); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = '#dc3232';
      ctx.fillText('ALM', px + pw - 22, ay - 3);
    }

    // ---- Future dimmed zone ----
    const nowX = px + Math.round(curMin * pw / (MINUTES - 1));
    if (nowX < px + pw) {
      ctx.fillStyle = 'rgba(255,255,255,0.04)';
      ctx.fillRect(nowX + 1, py, px + pw - nowX - 1, ph);
    }

    // ---- NOW line ----
    ctx.strokeStyle = '#ffdc3c';
    ctx.lineWidth   = 1;
    ctx.beginPath(); ctx.moveTo(nowX, py); ctx.lineTo(nowX, py + ph); ctx.stroke();
    ctx.fillStyle   = '#ffdc3c';
    const nowLbl    = 'NOW';
    const nowTw     = ctx.measureText(nowLbl).width;
    const nowLx     = nowX + nowTw + 6 < px + pw ? nowX + 3 : nowX - nowTw - 3;
    ctx.fillText(nowLbl, nowLx, py + 10);

    // ---- Data points ----
    if (history.length < 2) return;

    const points = history.map(([min, rms]) => {
      const x = px + Math.round(min * pw / (MINUTES - 1));
      const y = py + ph - Math.round(ph * rms / yMax);
      return [x, Math.max(py, Math.min(py + ph, y))];
    });

    // Filled area
    ctx.beginPath();
    ctx.moveTo(px, py + ph);
    points.forEach(([x, y]) => ctx.lineTo(x, y));
    ctx.lineTo(points[points.length - 1][0], py + ph);
    ctx.closePath();
    ctx.fillStyle = 'rgba(0,72,130,0.55)';
    ctx.fill();

    // Line
    ctx.beginPath();
    points.forEach(([x, y], i) => i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y));
    ctx.strokeStyle = '#00b4ff';
    ctx.lineWidth   = 2;
    ctx.stroke();

    // Current value dot
    const [lx, ly] = points[points.length - 1];
    ctx.beginPath(); ctx.arc(lx, ly, 5, 0, Math.PI * 2);
    ctx.fillStyle = '#12161c'; ctx.fill();
    ctx.beginPath(); ctx.arc(lx, ly, 4, 0, Math.PI * 2);
    ctx.strokeStyle = '#00b4ff'; ctx.lineWidth = 2; ctx.stroke();
    ctx.beginPath(); ctx.arc(lx, ly, 2, 0, Math.PI * 2);
    ctx.fillStyle = '#fff'; ctx.fill();

    // Current value label
    const curRms = history[history.length - 1][1];
    const lbl    = curRms.toFixed(3) + 'g';
    const lblW   = ctx.measureText(lbl).width;
    const lblX   = lx + lblW + 8 < px + pw ? lx + 6 : lx - lblW - 4;
    ctx.fillStyle = '#dce1e6';
    ctx.fillText(lbl, lblX, ly - 5);
  }

  // ── Helpers ────────────────────────────────────────────────
  function computeYMax(values) {
    const arr = Array.isArray(values) ? values : [];
    const mx  = arr.length ? Math.max(...arr) : 0;
    const raw = Math.max(1.0, mx * 1.15);
    return Math.ceil(raw * 4) / 4;   // round up to nearest 0.25
  }

  function rssiToBars(rssi) {
    if (rssi >= -60) return 4;
    if (rssi >= -70) return 3;
    if (rssi >= -80) return 2;
    if (rssi >= -90) return 1;
    return 0;
  }

  function setText(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  }

  return {};
})();
