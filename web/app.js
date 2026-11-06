import { Player } from './player.js';
import { AudioPlayer } from './audio.js';
import { InputController } from './input.js';
import { GamepadController } from './gamepad.js';

const $ = (id) => document.getElementById(id);
const state = {
  meta: null, ws: null, player: null, audio: null, input: null, gamepad: null,
  connected: false, control: false, manualClose: false, reconnectTimer: null, reconnectDelay: 1000,
  rtt: 0, lastStats: {}, settings: {}, wakeLock: null, pingTimer: null, statsTimer: null,
};

const local = {
  mouse: localStorage.getItem('pp_mouse') || (matchMedia('(pointer: coarse)').matches ? 'trackpad' : 'direct'),
  sens: Number(localStorage.getItem('pp_sens') || 100) / 100,
  natural: localStorage.getItem('pp_natural') === '1',
  volume: Number(localStorage.getItem('pp_volume') || 80),
  stats: localStorage.getItem('pp_stats') !== '0',
  wakelock: localStorage.getItem('pp_wakelock') !== '0',
  gamepadMode: localStorage.getItem('pp_gp_mode') || 'virtual',
};

init();

async function init() {
  bindLogin();
  bindUI();
  try {
    state.meta = await api('/api/meta');
    $('login-host').textContent = state.meta.hostname;
    $('demo-badge').classList.toggle('hidden', !state.meta.demo);
    const sess = await fetch('/api/session');
    if (sess.ok) await startApp();
  } catch (e) {
    $('login-host').textContent = 'Không liên lạc được host';
  }
}

async function api(path, body) {
  const r = await fetch(path, {
    method: body ? 'POST' : 'GET',
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(d.error || r.statusText), { status: r.status, data: d });
  return d;
}

function bindLogin() {
  $('login-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = $('login-btn');
    btn.disabled = true;
    $('login-error').textContent = '';
    try {
      await api('/api/login', { password: $('password').value });
      $('password').value = '';
      await startApp();
    } catch (err) {
      $('login-error').textContent = err.status === 429 ? `Thử lại sau ${err.data.retry_after || 60}s` : (err.message || 'Không kết nối được');
    } finally {
      btn.disabled = false;
    }
  });
  $('retry-btn').addEventListener('click', () => connectWS());
}

async function startApp() {
  $('login-view').classList.add('hidden');
  $('app-view').classList.remove('hidden');
  $('host-name').textContent = state.meta?.hostname || 'host';
  $('demo-badge-app').classList.toggle('hidden', !state.meta?.demo);
  state.player = new Player($('screen'), onPlayerStats);
  state.player.onError = (e) => toast(e.message, true);
  state.audio = new AudioPlayer();
  state.audio.setVolume(local.volume / 100);
  state.input = new InputController(send, {
    getMode: () => $('set-mouse').value,
    getSensitivity: () => Number($('set-sens').value) / 100,
    getNatural: () => $('set-natural').checked,
    isActive: () => state.connected && state.control,
  });
  state.gamepad = new GamepadController(send, (m) => toast(m));
  applyLocalUI();
  state.input.setMode($('set-mouse').value);
  connectWS();
  state.pingTimer = setInterval(() => send({ type: 'ping', t: performance.now() }), 2000);
  state.statsTimer = setInterval(() => {
    send({ type: 'stats', rtt: state.rtt, decode_queue: state.lastStats.decodeQueue || 0, fps: state.lastStats.decodeFps || 0 });
  }, 2000);
  requestWakeLock();
  // Unlock audio inside the user gesture that submitted login when possible.
  try { await state.audio.unlock(); state.audio.setMuted(false); updateAudioBtn(); } catch {}
}

function connectWS() {
  clearTimeout(state.reconnectTimer);
  if (state.ws) { state.manualClose = true; try { state.ws.close(); } catch {} }
  state.manualClose = false;
  showOverlay('Đang kết nối stream…', 'Đang mở WebSocket và chờ keyframe.');
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${proto}//${location.host}/ws`);
  ws.binaryType = 'arraybuffer';
  state.ws = ws;
  ws.onopen = () => {
    state.connected = true;
    state.reconnectDelay = 1000;
    $('status-text').textContent = 'Đã kết nối';
    $('transport-text').textContent = location.hostname.endsWith('trycloudflare.com') ? 'Cloudflare Quick Tunnel' : 'WebSocket';
  };
  ws.onmessage = async (ev) => {
    if (typeof ev.data === 'string') return handleJson(JSON.parse(ev.data));
    const res = await state.player.handleBinary(ev.data);
    if (res?.audio) state.audio.push(res.audio);
  };
  ws.onclose = (ev) => {
    state.connected = false;
    state.control = false;
    state.input?.releaseAll();
    state.gamepad?.reset();
    updateControlBadge();
    if (state.manualClose) return;
    if (ev.code === 4001) {
      showOverlay('Phiên nhàn rỗi', 'Host đã đóng kết nối do không hoạt động.', true);
      return;
    }
    showOverlay('Mất kết nối', `Đang thử lại sau ${Math.round(state.reconnectDelay / 1000)}s…`, true);
    state.reconnectTimer = setTimeout(connectWS, state.reconnectDelay);
    state.reconnectDelay = Math.min(10000, state.reconnectDelay * 1.7);
  };
  ws.onerror = () => { $('status-text').textContent = 'Lỗi kết nối'; };
}

function handleJson(m) {
  switch (m.type) {
    case 'hello':
      state.settings = m.settings;
      state.viewerId = m.viewer_id;
      state.control = m.control;
      state.player.setCodec(m.settings.codec);
      state.audio.sampleRate = m.audio.sample_rate;
      state.audio.channels = m.audio.channels;
      $('set-audio').checked = m.audio.enabled;
      fillQuality(m.settings);
      $('capability-note').textContent = `Input: ${m.input.name} — ${m.input.detail}\nGamepad: ${m.gamepad.name} — ${m.gamepad.detail}`;
      updateControlBadge();
      hideOverlay();
      toast(m.settings.demo ? 'Chế độ DEMO an toàn' : 'Đã vào phiên remote');
      break;
    case 'control':
      state.control = !!m.owner && m.owner === state.viewerId && !m.view_only;
      if (!state.control) { state.input?.releaseAll(); state.gamepad?.reset(); }
      updateControlBadge();
      break;
    case 'quality':
      state.settings = m.settings;
      fillQuality(m.settings);
      state.player.setCodec(m.settings.codec);
      toast(m.reason === 'adaptive-down' ? 'Đã giảm bitrate cho mạng yếu' : 'Đã đổi chất lượng');
      break;
    case 'audio_status':
      $('set-audio').checked = m.audio.enabled;
      if (!m.audio.enabled) state.audio.setMuted(true);
      updateAudioBtn();
      break;
    case 'gamepad_status':
      $('capability-note').textContent = `Gamepad: ${m.gamepad.name} — ${m.gamepad.detail}`;
      toast(`Gamepad: ${m.gamepad.name}`);
      break;
    case 'pong':
      state.rtt = Math.round(performance.now() - m.t);
      $('stat-rtt').textContent = state.rtt;
      break;
    case 'stream_reset':
      state.player.reset();
      showOverlay('Đang đồng bộ lại…', m.reason || 'Chờ keyframe.');
      setTimeout(hideOverlay, 1500);
      break;
    case 'stream_error':
      showOverlay('Lỗi stream', m.message, true);
      break;
    case 'error':
    case 'input_error':
      toast(m.message, true);
      break;
  }
}

function currentViewerId() { return state.viewerId; }

function send(msg) {
  const inputTypes = new Set(['mouse', 'mouse_button', 'wheel', 'key', 'text', 'gamepad', 'clipboard']);
  if (inputTypes.has(msg.type) && !state.control) return;
  if (state.ws?.readyState === WebSocket.OPEN) state.ws.send(JSON.stringify(msg));
}

function onPlayerStats(s) {
  state.lastStats = s;
  $('stat-fps').textContent = Math.round(s.renderFps || s.decodeFps || 0);
  $('stat-mbps').textContent = (s.mbps || 0).toFixed(1);
  $('stat-res').textContent = `${s.width}×${s.height}`;
  $('stat-enc').textContent = (s.codec || 'h264').toUpperCase();
  if (s.width && !s.waitingKey) hideOverlay();
  renderStatsPanel();
}

function renderStatsPanel() {
  if (!$('set-stats').checked) return;
  const s = state.lastStats;
  const rows = {
    'Codec': s.codec, 'FPS render': Math.round(s.renderFps || 0), 'FPS decode': Math.round(s.decodeFps || 0),
    'Mbps': (s.mbps || 0).toFixed(2), 'RTT': state.rtt + ' ms', 'Decode queue': s.decodeQueue || 0,
    'Dropped': s.dropped || 0, 'Độ phân giải': `${s.width}×${s.height}`, 'Quyền': state.control ? 'Điều khiển' : 'Chỉ xem',
  };
  $('stats-list').innerHTML = Object.entries(rows).map(([k, v]) => `<dt>${k}</dt><dd>${v ?? '–'}</dd>`).join('');
}

function fillQuality(s) {
  $('set-preset').value = s.preset in { data_saver: 1, balanced: 1, ultra: 1, lan: 1 } ? s.preset : 'custom';
  $('set-width').value = s.width; $('set-height').value = s.height;
  $('set-fps').value = s.fps; $('set-bitrate').value = s.bitrate;
  $('set-codec').value = s.codec; $('set-adaptive').checked = !!s.adaptive;
}

function updateControlBadge() {
  const b = $('control-badge');
  b.textContent = state.control ? 'Đang điều khiển' : 'Chỉ xem';
  b.classList.toggle('view', !state.control);
  $('take-control').disabled = state.control;
}

function showOverlay(title, detail, retry = false) {
  $('connect-title').textContent = title;
  $('connect-detail').textContent = detail;
  $('retry-btn').classList.toggle('hidden', !retry);
  $('connect-overlay').classList.remove('hidden');
}
function hideOverlay() { $('connect-overlay').classList.add('hidden'); }

function toast(msg, error = false) {
  const el = document.createElement('div');
  el.className = 'toast' + (error ? ' error' : '');
  el.textContent = msg;
  $('toasts').appendChild(el);
  setTimeout(() => el.remove(), 4200);
}

function applyLocalUI() {
  $('set-mouse').value = local.mouse;
  $('set-sens').value = Math.round(local.sens * 100);
  $('set-natural').checked = local.natural;
  $('set-volume').value = local.volume;
  $('set-stats').checked = local.stats;
  $('set-wakelock').checked = local.wakelock;
  $('set-gamepad').value = local.gamepadMode;
  $('stats-panel').classList.toggle('hidden', !local.stats);
}

function bindUI() {
  document.querySelectorAll('[data-action]').forEach(btn => btn.addEventListener('click', () => action(btn.dataset.action)));
  $('apply-quality').addEventListener('click', () => {
    send({
      type: 'quality', preset: $('set-preset').value,
      width: Number($('set-width').value), height: Number($('set-height').value),
      fps: Number($('set-fps').value), bitrate: Number($('set-bitrate').value),
      codec: $('set-codec').value, adaptive: $('set-adaptive').checked,
    });
  });
  $('set-preset').addEventListener('change', () => {
    const p = state.meta?.presets?.[$('set-preset').value];
    if (p) { $('set-width').value = p.width; $('set-height').value = p.height; $('set-fps').value = p.fps; $('set-bitrate').value = p.bitrate; }
  });
  $('set-mouse').addEventListener('change', () => {
    local.mouse = $('set-mouse').value; localStorage.setItem('pp_mouse', local.mouse);
    state.input?.setMode(local.mouse);
    if (local.mouse === 'pointerlock') toast('Click vào màn hình để khóa chuột');
  });
  $('set-sens').addEventListener('input', () => localStorage.setItem('pp_sens', $('set-sens').value));
  $('set-natural').addEventListener('change', () => localStorage.setItem('pp_natural', $('set-natural').checked ? '1' : '0'));
  $('set-volume').addEventListener('input', () => {
    local.volume = Number($('set-volume').value); localStorage.setItem('pp_volume', local.volume);
    state.audio?.setVolume(local.volume / 100);
  });
  $('set-audio').addEventListener('change', () => send({ type: 'audio', enabled: $('set-audio').checked }));
  $('set-stats').addEventListener('change', () => {
    local.stats = $('set-stats').checked; localStorage.setItem('pp_stats', local.stats ? '1' : '0');
    $('stats-panel').classList.toggle('hidden', !local.stats);
  });
  $('set-wakelock').addEventListener('change', () => {
    local.wakelock = $('set-wakelock').checked; localStorage.setItem('pp_wakelock', local.wakelock ? '1' : '0');
    if (local.wakelock) requestWakeLock(); else state.wakeLock?.release?.();
  });
  $('set-gamepad').addEventListener('change', () => {
    local.gamepadMode = $('set-gamepad').value; localStorage.setItem('pp_gp_mode', local.gamepadMode);
    send({ type: 'gamepad_mode', mode: local.gamepadMode });
  });
  $('take-control').addEventListener('click', () => send({ type: 'control', action: 'take' }));
  document.addEventListener('fullscreenchange', () => {
    if (document.fullscreenElement) { state.input?.lockKeyboard(); lockOrientation(); }
    else state.input?.unlockKeyboard();
  });
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') requestWakeLock(); });
}

async function action(name) {
  switch (name) {
    case 'keyboard': {
      const el = $('special-keys');
      el.classList.toggle('hidden');
      document.querySelector('[data-action="keyboard"]').classList.toggle('active', !el.classList.contains('hidden'));
      if (!el.classList.contains('hidden')) state.input?.focusMobileKeyboard();
      break;
    }
    case 'gamepad':
      state.gamepad?.setVisible(!state.gamepad.visible);
      if (state.gamepad?.visible) send({ type: 'gamepad_mode', mode: $('set-gamepad').value });
      break;
    case 'trackpad': {
      const panel = $('trackpad-panel');
      const show = panel.classList.contains('hidden');
      panel.classList.toggle('hidden', !show);
      $('touch-hint').classList.toggle('hidden', !show);
      document.querySelector('[data-action="trackpad"]').classList.toggle('active', show);
      if (show) { $('set-mouse').value = 'trackpad'; state.input?.setMode('trackpad'); }
      break;
    }
    case 'trackpad-close':
      $('trackpad-panel').classList.add('hidden');
      $('touch-hint').classList.add('hidden');
      break;
    case 'audio':
      try {
        await state.audio?.unlock(state.audio.sampleRate, state.audio.channels);
        state.audio?.setMuted(!state.audio.muted);
        updateAudioBtn();
      } catch (e) { toast('Không bật được âm thanh: ' + e.message, true); }
      break;
    case 'screenshot': state.player?.screenshot(); toast('Đã chụp màn hình'); break;
    case 'fullscreen': await toggleFullscreen(); break;
    case 'settings': $('settings').classList.toggle('hidden'); break;
    case 'settings-close': $('settings').classList.add('hidden'); break;
    case 'help': $('help-modal').classList.remove('hidden'); break;
    case 'help-close': $('help-modal').classList.add('hidden'); break;
    case 'disconnect': await disconnect(); break;
  }
}

function updateAudioBtn() {
  const active = state.audio && !state.audio.muted;
  document.querySelector('[data-action="audio"]').classList.toggle('active', !!active);
}

async function toggleFullscreen() {
  try {
    if (!document.fullscreenElement) {
      await $('app-view').requestFullscreen();
      await lockOrientation();
      await state.input?.lockKeyboard();
    } else await document.exitFullscreen();
  } catch (e) { toast('Fullscreen không được hỗ trợ: ' + e.message, true); }
}
async function lockOrientation() {
  try { await screen.orientation?.lock?.('landscape'); } catch {}
}
async function requestWakeLock() {
  if (!local.wakelock || !('wakeLock' in navigator)) return;
  try { state.wakeLock = await navigator.wakeLock.request('screen'); } catch {}
}

async function disconnect() {
  state.manualClose = true;
  send({ type: 'control', action: 'release' });
  state.input?.releaseAll();
  state.gamepad?.reset();
  try { state.ws?.close(); } catch {}
  try { await api('/api/logout', {}); } catch {}
  clearInterval(state.pingTimer); clearInterval(state.statsTimer);
  state.player?.destroy(); state.audio?.close(); state.gamepad?.destroy();
  state.wakeLock?.release?.();
  location.reload();
}
