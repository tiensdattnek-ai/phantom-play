export class AudioPlayer {
  constructor() {
    this.ctx = null;
    this.node = null;
    this.gain = null;
    this.enabled = false;
    this.muted = true;
    this.volume = 0.8;
    this.sampleRate = 48000;
    this.channels = 2;
  }

  async unlock(sampleRate = 48000, channels = 2) {
    this.sampleRate = sampleRate || 48000;
    this.channels = channels || 2;
    if (this.ctx && this.ctx.sampleRate !== this.sampleRate) {
      await this.close();
    }
    if (!this.ctx) {
      this.ctx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: this.sampleRate, latencyHint: 'interactive' });
      await this.ctx.audioWorklet.addModule('/static/audio-worklet.js');
      this.node = new AudioWorkletNode(this.ctx, 'phantom-pcm', { outputChannelCount: [2] });
      this.gain = this.ctx.createGain();
      this.gain.gain.value = this.muted ? 0 : this.volume;
      this.node.connect(this.gain).connect(this.ctx.destination);
    }
    if (this.ctx.state === 'suspended') await this.ctx.resume();
    this.enabled = true;
  }

  push(pcm) {
    if (!this.enabled || !this.node || this.muted) return;
    const i16 = new Int16Array(pcm);
    const f32 = new Float32Array(i16.length);
    for (let i = 0; i < i16.length; i++) f32[i] = i16[i] / 32768;
    this.node.port.postMessage({ type: 'pcm', data: f32, channels: this.channels }, [f32.buffer]);
  }

  setMuted(m) {
    this.muted = m;
    if (this.gain) this.gain.gain.value = m ? 0 : this.volume;
    if (m && this.node) this.node.port.postMessage({ type: 'reset' });
  }

  setVolume(v) {
    this.volume = Math.max(0, Math.min(1, v));
    if (this.gain && !this.muted) this.gain.gain.value = this.volume;
  }

  reset() {
    if (this.node) this.node.port.postMessage({ type: 'reset' });
  }

  async close() {
    this.enabled = false;
    if (this.ctx) { try { await this.ctx.close(); } catch {} }
    this.ctx = this.node = this.gain = null;
  }
}
