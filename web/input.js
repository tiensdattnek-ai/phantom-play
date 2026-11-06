const BUTTON_BIT = { 0: 1, 1: 4, 2: 2 };
const KEY_RE = /^(?:Key[A-Z]|Digit[0-9]|F(?:[1-9]|1[0-2])|Escape|Tab|CapsLock|ShiftLeft|ShiftRight|ControlLeft|ControlRight|AltLeft|AltRight|MetaLeft|MetaRight|Space|Enter|Backspace|Delete|Insert|Home|End|PageUp|PageDown|ArrowUp|ArrowDown|ArrowLeft|ArrowRight|PrintScreen|ScrollLock|Pause|NumLock|Numpad(?:[0-9]|Add|Subtract|Multiply|Divide|Decimal|Enter)|Minus|Equal|BracketLeft|BracketRight|Backslash|Semicolon|Quote|Comma|Period|Slash|Backquote|ContextMenu)$/;

export class InputController {
  constructor(send, opts) {
    this.send = send;
    this.opts = opts;
    this.canvas = document.getElementById('screen');
    this.trackpad = document.getElementById('trackpad');
    this.mobileInput = document.getElementById('mobile-input');
    this.pressed = new Set();
    this.mouseButtons = 0;
    this.dragLock = false;
    this.pointerLocked = false;
    this.lastTap = 0;
    this._bind();
  }

  get mode() { return this.opts.getMode(); }
  get sens() { return this.opts.getSensitivity(); }
  get natural() { return this.opts.getNatural(); }
  get active() { return this.opts.isActive(); }

  _bind() {
    const c = this.canvas;
    c.addEventListener('pointerdown', (e) => this._canvasDown(e));
    c.addEventListener('pointermove', (e) => this._canvasMove(e));
    c.addEventListener('pointerup', (e) => this._canvasUp(e));
    c.addEventListener('pointercancel', (e) => this._canvasUp(e));
    c.addEventListener('wheel', (e) => this._wheel(e), { passive: false });
    c.addEventListener('contextmenu', (e) => e.preventDefault());
    document.addEventListener('pointerlockchange', () => {
      this.pointerLocked = document.pointerLockElement === c;
      document.getElementById('pointer-lock-hint').classList.toggle('hidden', !this.pointerLocked);
    });
    document.addEventListener('mousemove', (e) => {
      if (this.pointerLocked && this.active) {
        this.send({ type: 'mouse', mode: 'relative', dx: e.movementX * this.sens, dy: e.movementY * this.sens, buttons: this.mouseButtons });
      }
    });
    document.addEventListener('mousedown', (e) => {
      if (this.pointerLocked && this.active) this._mouseButton(e.button, true);
    });
    document.addEventListener('mouseup', (e) => {
      if (this.pointerLocked && this.active) this._mouseButton(e.button, false);
    });
    window.addEventListener('keydown', (e) => this._key(e, true));
    window.addEventListener('keyup', (e) => this._key(e, false));
    window.addEventListener('blur', () => this.releaseAll());
    this._bindTrackpad(this.trackpad);
    this._bindSpecialKeys();
    this._bindMobileInput();
    document.getElementById('tp-left').addEventListener('pointerdown', (e) => { e.preventDefault(); this._mouseButton(0, true); });
    document.getElementById('tp-left').addEventListener('pointerup', (e) => { e.preventDefault(); this._mouseButton(0, false); });
    document.getElementById('tp-right').addEventListener('pointerdown', (e) => { e.preventDefault(); this._mouseButton(2, true); });
    document.getElementById('tp-right').addEventListener('pointerup', (e) => { e.preventDefault(); this._mouseButton(2, false); });
    document.getElementById('tp-drag').addEventListener('click', (e) => {
      this.dragLock = !this.dragLock;
      e.currentTarget.classList.toggle('active', this.dragLock);
      this._mouseButton(0, this.dragLock);
    });
  }

  _mapPoint(e) {
    const r = this.canvas.getBoundingClientRect();
    const cw = this.canvas.width || 1, ch = this.canvas.height || 1;
    const scale = Math.min(r.width / cw, r.height / ch);
    const dw = cw * scale, dh = ch * scale;
    const ox = (r.width - dw) / 2, oy = (r.height - dh) / 2;
    const x = Math.max(0, Math.min(1, (e.clientX - r.left - ox) / dw));
    const y = Math.max(0, Math.min(1, (e.clientY - r.top - oy) / dh));
    return { x, y };
  }

  _canvasDown(e) {
    if (!this.active) return;
    e.preventDefault();
    this.canvas.focus?.();
    if (this.mode === 'pointerlock') {
      if (!this.pointerLocked) this.canvas.requestPointerLock?.();
      return;
    }
    if (this.mode === 'direct') {
      this.canvas.setPointerCapture?.(e.pointerId);
      const p = this._mapPoint(e);
      const bit = BUTTON_BIT[e.button] || 1;
      this.mouseButtons |= bit;
      this.send({ type: 'mouse', mode: 'absolute', x: p.x, y: p.y, buttons: this.mouseButtons });
    }
  }

  _canvasMove(e) {
    if (!this.active || this.mode !== 'direct' || this.pointerLocked) return;
    const p = this._mapPoint(e);
    this.send({ type: 'mouse', mode: 'absolute', x: p.x, y: p.y, buttons: this.mouseButtons });
  }

  _canvasUp(e) {
    if (!this.active || this.mode !== 'direct') return;
    const bit = BUTTON_BIT[e.button] || 1;
    this.mouseButtons &= ~bit;
    const p = this._mapPoint(e);
    this.send({ type: 'mouse', mode: 'absolute', x: p.x, y: p.y, buttons: this.mouseButtons });
  }

  _mouseButton(button, down) {
    const name = button === 2 ? 'right' : button === 1 ? 'middle' : 'left';
    const bit = BUTTON_BIT[button] || 1;
    this.mouseButtons = down ? (this.mouseButtons | bit) : (this.mouseButtons & ~bit);
    this.send({ type: 'mouse_button', button: name, down });
  }

  _wheel(e) {
    if (!this.active) return;
    e.preventDefault();
    const sign = this.natural ? -1 : 1;
    const dy = Math.max(-10, Math.min(10, (-e.deltaY / 100) * sign));
    const dx = Math.max(-10, Math.min(10, (e.deltaX / 100) * sign));
    this.send({ type: 'wheel', dx, dy });
  }

  _bindTrackpad(el) {
    const pointers = new Map();
    let twoStart = null;
    let twoMoved = false;
    let dragActive = false;
    let tapCandidate = false;

    const down = (e) => {
      if (!this.active) return;
      e.preventDefault();
      el.setPointerCapture?.(e.pointerId);
      const now = performance.now();
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY, sx: e.clientX, sy: e.clientY, t: now, moved: 0 });
      if (pointers.size === 1) {
        tapCandidate = now - this.lastTap < 300;
        if (tapCandidate) dragActive = false;
      } else if (pointers.size === 2) {
        twoStart = { t: now, y: avgY(pointers) };
        twoMoved = false;
        if (dragActive) { this._mouseButton(0, false); dragActive = false; }
      }
    };
    const move = (e) => {
      const p = pointers.get(e.pointerId);
      if (!p || !this.active) return;
      e.preventDefault();
      const dx = e.clientX - p.x, dy = e.clientY - p.y;
      p.x = e.clientX; p.y = e.clientY;
      p.moved += Math.abs(dx) + Math.abs(dy);
      if (pointers.size === 1) {
        if (tapCandidate && p.moved > 8 && !dragActive) {
          dragActive = true;
          this._mouseButton(0, true);
        }
        this.send({ type: 'mouse', mode: 'relative', dx: dx * this.sens, dy: dy * this.sens, buttons: this.mouseButtons });
      } else if (pointers.size >= 2) {
        twoMoved = true;
        const y = avgY(pointers);
        const delta = (y - (twoStart?.y ?? y)) / 30;
        if (twoStart) twoStart.y = y;
        const sign = this.natural ? 1 : -1;
        if (Math.abs(delta) > 0.05) this.send({ type: 'wheel', dx: 0, dy: Math.max(-5, Math.min(5, delta * sign)) });
      }
    };
    const up = (e) => {
      const p = pointers.get(e.pointerId);
      if (!p) return;
      e.preventDefault();
      const dt = performance.now() - p.t;
      const wasSize = pointers.size;
      pointers.delete(e.pointerId);
      if (dragActive && wasSize === 1) {
        this._mouseButton(0, false);
        dragActive = false;
      } else if (wasSize === 1 && dt < 260 && p.moved < 10) {
        this._click('left');
        this.lastTap = performance.now();
      } else if (wasSize === 2 && !twoMoved && dt < 300) {
        this._click('right');
      } else if (wasSize === 3 && !twoMoved && dt < 300) {
        this._click('middle');
      }
      if (pointers.size === 0) { tapCandidate = false; twoStart = null; }
    };
    el.addEventListener('pointerdown', down);
    el.addEventListener('pointermove', move);
    el.addEventListener('pointerup', up);
    el.addEventListener('pointercancel', up);
    el.addEventListener('contextmenu', (e) => e.preventDefault());
  }

  _click(name) {
    this.send({ type: 'mouse_button', button: name, down: true });
    setTimeout(() => this.send({ type: 'mouse_button', button: name, down: false }), 40);
  }

  _bindSpecialKeys() {
    document.querySelectorAll('#special-keys [data-key]').forEach(btn => {
      const code = btn.dataset.key;
      const down = (e) => { e.preventDefault(); this._sendKey(code, true); };
      const up = (e) => { e.preventDefault(); this._sendKey(code, false); };
      btn.addEventListener('pointerdown', down);
      btn.addEventListener('pointerup', up);
      btn.addEventListener('pointercancel', up);
    });
    document.querySelectorAll('#special-keys [data-text]').forEach(btn => {
      btn.addEventListener('click', () => this.send({ type: 'text', text: btn.dataset.text }));
    });
  }

  _bindMobileInput() {
    const inp = this.mobileInput;
    inp.addEventListener('input', () => {
      if (!this.active) return;
      const text = inp.value;
      if (text) this.send({ type: 'text', text: text.slice(0, 256) });
      inp.value = '';
    });
    inp.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); this._sendKey('Enter', true); this._sendKey('Enter', false); }
      if (e.key === 'Backspace') { e.preventDefault(); this._sendKey('Backspace', true); this._sendKey('Backspace', false); }
    });
  }

  focusMobileKeyboard() {
    this.mobileInput.style.pointerEvents = 'auto';
    this.mobileInput.focus({ preventScroll: true });
    setTimeout(() => { this.mobileInput.style.pointerEvents = 'none'; }, 100);
  }

  _key(e, down) {
    if (!this.active) return;
    const tag = (e.target?.tagName || '').toLowerCase();
    if (['input', 'select', 'textarea'].includes(tag) && e.target !== this.mobileInput) return;
    if (e.target === this.mobileInput && down && !['Enter', 'Backspace'].includes(e.key)) return;
    const code = e.code;
    if (!code || !KEY_RE.test(code)) return;
    if (down) {
      if (['Tab', 'Escape', 'Space', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'MetaLeft', 'MetaRight'].includes(code) || this.pointerLocked) e.preventDefault();
      this.pressed.add(code);
    } else {
      this.pressed.delete(code);
    }
    this._sendKey(code, down);
  }

  _sendKey(code, down) {
    this.send({ type: 'key', code, down });
  }

  async lockKeyboard() {
    try { await navigator.keyboard?.lock?.(); } catch {}
  }
  unlockKeyboard() {
    try { navigator.keyboard?.unlock?.(); } catch {}
  }

  setMode(mode) {
    if (mode !== 'pointerlock' && this.pointerLocked) document.exitPointerLock?.();
    if (mode === 'trackpad') {
      document.getElementById('trackpad-panel').classList.remove('hidden');
      document.getElementById('touch-hint').classList.remove('hidden');
    } else {
      document.getElementById('trackpad-panel').classList.add('hidden');
      document.getElementById('touch-hint').classList.add('hidden');
    }
  }

  releaseAll() {
    for (const code of this.pressed) this._sendKey(code, false);
    this.pressed.clear();
    for (const b of ['left', 'right', 'middle']) this.send({ type: 'mouse_button', button: b, down: false });
    this.mouseButtons = 0;
    this.dragLock = false;
    document.getElementById('tp-drag')?.classList.remove('active');
  }
}

function avgY(pointers) {
  let s = 0; for (const p of pointers.values()) s += p.y;
  return s / pointers.size;
}
