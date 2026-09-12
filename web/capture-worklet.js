/**
 * Microphone capture worklet.
 *
 * Runs on the audio thread, so it does the least possible work: convert the
 * render quantum to 16-bit and hand over whole frames. Resampling is not done
 * here -- the AudioContext is created at 16 kHz, so the browser has already
 * resampled with better quality than we could manage in a few lines.
 */

const SAMPLES_PER_FRAME = 320; // 20 ms at 16 kHz, matching the server

class CaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer = new Int16Array(SAMPLES_PER_FRAME);
    this.filled = 0;
  }

  process(inputs) {
    const channel = inputs[0]?.[0];
    if (!channel) return true;

    for (let i = 0; i < channel.length; i++) {
      // Clamp before scaling: values outside [-1, 1] would wrap around.
      const sample = Math.max(-1, Math.min(1, channel[i]));
      this.buffer[this.filled++] = sample * 0x7fff;
      if (this.filled === SAMPLES_PER_FRAME) {
        this.port.postMessage(this.buffer.slice());
        this.filled = 0;
      }
    }
    return true;
  }
}

registerProcessor('capture', CaptureProcessor);
