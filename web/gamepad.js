export class GamepadController {
  constructor(send, onStatus = () => {}) {
    this.send = send;
    this.onStatus = onStatus;
    this.visible = false;
    this.axes = [0, 0, 0, 0];
    this.buttons = new Array(17).fill(0);
    this.physicalIndex = null;
    this.lastSent = '';
    this.timer = setInterval(() => this.tick(), 1000 / 60);
    this._bindTouch();
    window.addEventListener('gamepadconnected', (e) => {
      this.physicalIndex = e.gamepad.index;
      this.onStatus(`Tay cầm: ${e.gamepad.id}`);
    });
    window.addEventListener('gamepaddisconnected', (e) => {
      if (this.physicalIndex === e.gamepad.index) this.physicalIndex = null;
      this.onStatus('Tay cầm đã ngắt');
      this.reset();
    });
  }

  setVisible(v) {
    this.visible = v;
    document.getElementById('gamepad-overlay').classList.toggle('hidden', !v);
    document.querySelector('[data-action="gamepad"]').classList.toggle('active', v);
    if (!v) this.reset();
  }

  _bindTouch() {
    document.querySelectorAll('[data-gp]').forEach(btn => {
      const idx = Number(btn.dataset.gp);
      const down = (e) => { e.preventDefault(); btn.setPointerCapture?.(e.pointerId); this.buttons[idx] = 1; btn.classList.add('active'); this.sendState(true); };
      const up = (e) => { e.preventDefault(); this.buttons[idx] = 0; btn.classList.remove('active'); this.sendState(true); };
      btn.addEventListener('pointerdown', down);
      btn.addEventListener('pointerup', up);
      btn.addEventListener('pointercancel', up);
      btn.addEventListener('pointerleave', (e) => { if (e.buttons) up(e); });
    });
    document.querySelectorAll('.stick').forEach(stick => {
      const side = stick.dataset.stick;
      const knob = stick.querySelector('.stick-knob');
      let pid = null;
      const move = (e) => {
        if (pid !== e.pointerId) return;
        const r = stick.getBoundingClientRect();
        let x = (e.clientX - (r.left + r.width / 2)) / (r.width / 2);
        let y = (e.clientY - (r.top + r.height / 2)) / (r.height / 2);
        const m = Math.hypot(x, y);
        if (m > 1) { x /= m; y /= m; }
        const base = side === 'left' ? 0 : 2;
        this.axes[base] = x; this.axes[base + 1] = y;
        const max = r.width / 2 - knob.offsetWidth / 2;
        knob.style.transform = `translate(${x * max}px, ${y * max}px)`;
        this.sendState();
      };
      const end = (e) => {
        if (pid !== e.pointerId) return;
        pid = null;
        const base = side === 'left' ? 0 : 2;
        this.axes[base] = this.axes[base + 1] = 0;
        knob.style.transform = '';
        this.sendState(true);
      };
      stick.addEventListener('pointerdown', (e) => { e.preventDefault(); pid = e.pointerId; stick.setPointerCapture(pid); move(e); });
      stick.addEventListener('pointermove', move);
      stick.addEventListener('pointerup', end);
      stick.addEventListener('pointercancel', end);
    });
  }

  tick() {
    if (this.physicalIndex !== null && navigator.getGamepads) {
      const gp = navigator.getGamepads()[this.physicalIndex];
      if (gp) {
        this.axes = [gp.axes[0] || 0, gp.axes[1] || 0, gp.axes[2] || 0, gp.axes[3] || 0];
        this.buttons = Array.from({ length: 17 }, (_, i) => gp.buttons[i]?.value || 0);
        this.sendState();
        return;
      }
    }
    if (this.visible) this.sendState();
  }

  sendState(force = false) {
    const state = { axes: this.axes.map(deadzone), buttons: this.buttons.map(v => Math.round(v * 1000) / 1000) };
    const key = JSON.stringify(state);
    if (!force && key === this.lastSent) return;
    this.lastSent = key;
    this.send({ type: 'gamepad', ...state });
  }

  reset() {
    this.axes = [0, 0, 0, 0];
    this.buttons.fill(0);
    document.querySelectorAll('.gp-btn.active').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.stick-knob').forEach(k => k.style.transform = '');
    this.sendState(true);
  }

  destroy() { clearInterval(this.timer); }
}

function deadzone(v) {
  const d = 0.08;
  if (Math.abs(v) < d) return 0;
  return Math.round(Math.sign(v) * ((Math.abs(v) - d) / (1 - d)) * 1000) / 1000;
}
