const T = { KEY: 1, DELTA: 2, CONFIG: 3, AUDIO: 4, JPEG: 5 };
const HEADER = 13;

export class Player {
  constructor(canvas, onStats = () => {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d', { alpha: false, desynchronized: true });
    this.onStats = onStats;
    this.decoder = null;
    this.config = null;
    this.codec = 'h264';
    this.waitingKey = true;
    this.pending = null;
    this.decoded = 0;
    this.rendered = 0;
    this.dropped = 0;
    this.bytes = 0;
    this.lastStats = performance.now();
    this.lastFrameAt = 0;
    this.running = true;
    this._renderLoop = this._renderLoop.bind(this);
    requestAnimationFrame(this._renderLoop);
    this._statsTimer = setInterval(() => this._emitStats(), 1000);
  }

  setCodec(codec) {
    this.codec = codec;
    this.reset();
  }

  reset() {
    this.waitingKey = true;
    if (this.decoder) {
      try { this.decoder.close(); } catch {}
      this.decoder = null;
    }
    if (this.pending) {
      try { this.pending.close(); } catch {}
      this.pending = null;
    }
  }

  destroy() {
    this.running = false;
    clearInterval(this._statsTimer);
    this.reset();
  }

  _ensureDecoder() {
    if (this.decoder || !this.config) return;
    if (!('VideoDecoder' in window)) throw new Error('Trình duyệt không có WebCodecs. Hãy chuyển sang MJPEG trong Cài đặt.');
    const c = this.config;
    const codec = 'avc1.' + [...c.slice(1, 4)].map(x => x.toString(16).padStart(2, '0')).join('').toUpperCase();
    this.decoder = new VideoDecoder({
      output: (frame) => {
        if (this.pending) { try { this.pending.close(); } catch {} }
        this.pending = frame;
        this.decoded++;
        this.lastFrameAt = performance.now();
      },
      error: (e) => {
        console.warn('decoder error', e);
        this.dropped++;
        this.reset();
      },
    });
    this.decoder.configure({
      codec,
      description: c,
      optimizeForLatency: true,
      hardwareAcceleration: 'prefer-hardware',
    });
  }

  async handleBinary(buf) {
    if (buf.byteLength < HEADER) return;
    const view = new DataView(buf);
    const type = view.getUint8(0);
    const seq = view.getUint32(1, true);
    const pts = Number(view.getBigUint64(5, true));
    const payload = buf.slice(HEADER);
    this.bytes += payload.byteLength;
    if (type === T.AUDIO) return { audio: payload };
    if (type === T.CONFIG) {
      const changed = !this.config || !bytesEqual(this.config, new Uint8Array(payload));
      this.config = new Uint8Array(payload);
      if (changed) {
        this.reset();
        this._ensureDecoder();
      }
      return null;
    }
    if (type === T.JPEG) {
      try {
        const bmp = await createImageBitmap(new Blob([payload], { type: 'image/jpeg' }));
        if (this.pending) { try { this.pending.close(); } catch {} }
        this.pending = bmp;
        this.decoded++;
        this.waitingKey = false;
      } catch { this.dropped++; }
      return null;
    }
    if (this.codec !== 'h264') return null;
    if (type === T.KEY) {
      try { this._ensureDecoder(); } catch (e) { this.onError?.(e); return null; }
      this.waitingKey = false;
    }
    if (!this.decoder || this.decoder.state === 'closed') return null;
    if (this.waitingKey && type !== T.KEY) { this.dropped++; return null; }
    if (this.decoder.decodeQueueSize > 10) {
      this.dropped++;
      this.waitingKey = true;
      return null;
    }
    try {
      this.decoder.decode(new EncodedVideoChunk({
        type: type === T.KEY ? 'key' : 'delta',
        timestamp: pts,
        data: payload,
      }));
    } catch (e) {
      this.dropped++;
      this.reset();
    }
    return null;
  }

  _renderLoop() {
    if (!this.running) return;
    const f = this.pending;
    if (f) {
      const w = f.displayWidth || f.width;
      const h = f.displayHeight || f.height;
      if (w && h) {
        if (this.canvas.width !== w || this.canvas.height !== h) {
          this.canvas.width = w;
          this.canvas.height = h;
        }
        try {
          this.ctx.drawImage(f, 0, 0, w, h);
          this.rendered++;
        } catch {}
      }
      try { f.close(); } catch {}
      this.pending = null;
    }
    requestAnimationFrame(this._renderLoop);
  }

  _emitStats() {
    const now = performance.now();
    const dt = (now - this.lastStats) / 1000;
    this.lastStats = now;
    this.onStats({
      decodeFps: this.decoded / dt,
      renderFps: this.rendered / dt,
      mbps: this.bytes * 8 / dt / 1e6,
      dropped: this.dropped,
      decodeQueue: this.decoder?.decodeQueueSize || 0,
      width: this.canvas.width,
      height: this.canvas.height,
      waitingKey: this.waitingKey,
      codec: this.codec,
    });
    this.decoded = 0;
    this.rendered = 0;
    this.bytes = 0;
  }

  screenshot() {
    const a = document.createElement('a');
    a.download = `phantomplay-${Date.now()}.png`;
    a.href = this.canvas.toDataURL('image/png');
    a.click();
  }
}

function bytesEqual(a, b) {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
  return true;
}
