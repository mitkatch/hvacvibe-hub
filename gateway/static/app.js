/* ============================================================
   app.js  —  WebSocket client + view router
   ============================================================ */

const App = (() => {
  let ws = null;
  let currentView = 'main';
  const listeners = {};

  // ── WebSocket ──────────────────────────────────────────────
  function connect() {
    const url = `ws://${location.host}/ws`;
    ws = new WebSocket(url);

    ws.onopen = () => {
      console.log('WS connected');
      clockTick();
    };

    ws.onmessage = (evt) => {
      let msg;
      try { msg = JSON.parse(evt.data); } catch { return; }
      dispatch(msg);
    };

    ws.onclose = () => {
      console.warn('WS closed — retrying in 2s');
      setTimeout(connect, 2000);
    };

    ws.onerror = (e) => {
      console.error('WS error', e);
    };
  }

  function send(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(obj));
    }
  }

  // ── Message dispatcher ─────────────────────────────────────
  function dispatch(msg) {
    const type = msg.type;
    if (type === 'toggle_view') {
      currentView === 'main' ? showSetup() : showMain();
      return;
    }
    (listeners[type] || []).forEach(fn => fn(msg));
    (listeners['*']  || []).forEach(fn => fn(msg));
  }

  function on(type, fn) {
    (listeners[type] = listeners[type] || []).push(fn);
  }

  // ── View routing ───────────────────────────────────────────
  function showMain() {
    currentView = 'main';
    document.getElementById('view-main').classList.add('active');
    document.getElementById('view-setup').classList.remove('active');
  }

  function showSetup() {
    currentView = 'setup';
    document.getElementById('view-setup').classList.add('active');
    document.getElementById('view-main').classList.remove('active');
    // request fresh status when entering setup
    send({ cmd: 'get_status' });
  }

  // ── Clock ──────────────────────────────────────────────────
  function clockTick() {
    const el = document.getElementById('clock');
    if (el) {
      const now = new Date();
      el.textContent = now.toTimeString().slice(0, 8);
    }
    setTimeout(clockTick, 1000);
  }

  // ── Init ───────────────────────────────────────────────────
  window.addEventListener('DOMContentLoaded', connect);

  return { send, on, showMain, showSetup };
})();
