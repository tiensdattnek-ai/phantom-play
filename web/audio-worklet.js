class PcmRing extends AudioWorkletProcessor {
  constructor() {
    super();
    this.channels = 2;
    this.cap = Math.ceil(sampleRate * 0.6);
    this.buffers = [new Float32Array(this.cap), new Float32Array(this.cap)];
    this.r = 0; this.w = 0; this.count = 0;
    this.started = false;
    this.target = Math.ceil(sampleRate * 0.06);
    this.max = Math.ceil(sampleRate * 0.25);
    this.port.onmessage = (e) => {
      const d = e.data;
      if (d.type === 'pcm') {
        const data = d.data;
        const ch = d.channels || 2;
        this.channels = ch;
        const frames = data.length / ch;
        for (let i = 0; i < frames; i++) {
          for (let c = 0; c < 2; c++) {
            const v = data[i * ch + (c < ch ? c : 0)] || 0;
            this.buffers[c][this.w] = v;
          }
          this.w = (this.w + 1) % this.cap;
          if (this.count < this.cap) this.count++;
          else this.r = (this.r + 1) % this.cap;
        }
        if (this.count > this.max) {
          const drop = this.count - this.target;
          this.r = (this.r + drop) % this.cap;
          this.count -= drop;
        }
        if (!this.started && this.count >= this.target) this.started = true;
      } else if (d.type === 'reset') {
        this.r = this.w = this.count = 0; this.started = false;
      }
    };
  }
  process(inputs, outputs) {
    const out = outputs[0];
    const n = out[0].length;
    if (!this.started || this.count < n) {
      for (let c = 0; c < out.length; c++) out[c].fill(0);
      return true;
    }
    for (let i = 0; i < n; i++) {
      for (let c = 0; c < out.length; c++) {
        out[c][i] = this.buffers[c < 2 ? c : 0][this.r];
      }
      this.r = (this.r + 1) % this.cap;
      this.count--;
    }
    if (this.count < this.target * 0.5) this.started = false;
    return true;
  }
}
registerProcessor('phantom-pcm', PcmRing);
