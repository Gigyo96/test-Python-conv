/**
 * The exam room.
 *
 * The browser is a terminal: it captures audio, plays audio, and renders the
 * state the server tells it about. It takes no decisions about the exam.
 *
 * It is here rather than in Python for one reason: WebRTC's echo canceller.
 * Without it, speakers feed the examiner's voice straight back into the
 * microphone and the turn detector fires on the examiner's own words. There is
 * no comparable echo canceller available to a Python process, which is why the
 * audio front end lives in a browser tab. See docs/ARCHITECTURE.md, decision D1.
 */

const SAMPLE_RATE = 16000;

const ui = {
  status: document.querySelector('#status'),
  phase: document.querySelector('#phase'),
  examiner: document.querySelector('#examiner'),
  meter: document.querySelector('#meter-level'),
  start: document.querySelector('#start'),
};

let socket = null;
let context = null;
let playbackCursor = 0;
let queuedSources = [];
let pendingUtterance = null;
let sessionFinished = false;

ui.start.addEventListener('click', start, { once: true });

async function start() {
  ui.start.disabled = true;
  setStatus('connecting…');
  try {
    await openMicrophone();
    openSocket();
  } catch (error) {
    fail(error.message ?? String(error));
  }
}

async function openMicrophone() {
  // Echo cancellation is mandatory -- it is why this page exists.
  //
  // Noise suppression and automatic gain control are deliberately OFF. They
  // alter exactly the spectral detail the pronunciation assessment reads, and
  // unlike echo cancellation they buy nothing here: during the candidate's turn
  // there is no far-end signal, so the canceller is effectively pass-through
  // and leaves the voice untouched.
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      echoCancellation: true,
      noiseSuppression: false,
      autoGainControl: false,
      channelCount: 1,
    },
  });

  // Asking for 16 kHz makes the browser resample once, well, instead of us
  // doing it badly in the worklet.
  context = new AudioContext({ sampleRate: SAMPLE_RATE });
  await context.audioWorklet.addModule('capture-worklet.js');

  const source = context.createMediaStreamSource(stream);
  const capture = new AudioWorkletNode(context, 'capture');
  capture.port.onmessage = (event) => onCapturedFrame(event.data);
  source.connect(capture);
}

function openSocket() {
  socket = new WebSocket(`ws://${location.host}/ws`);
  socket.binaryType = 'arraybuffer';
  socket.onopen = () => {
    socket.send(JSON.stringify({ type: 'hello', sample_rate: SAMPLE_RATE }));
    setStatus('listening');
  };
  socket.onmessage = (event) =>
    typeof event.data === 'string' ? onServerEvent(JSON.parse(event.data)) : onAudio(event.data);
  socket.onerror = () => fail('connection error');
  // A closed socket after the closing formula is the exam ending, not a
  // failure: overwriting the final status here would erase the outcome.
  socket.onclose = () => {
    if (!sessionFinished) setStatus('disconnected');
  };
}

function onCapturedFrame(frame) {
  if (socket?.readyState === WebSocket.OPEN) socket.send(frame.buffer);
  updateMeter(frame);
  // Published so the browser test can assert the capture contract from inside
  // the page: the server assumes 20 ms frames at 16 kHz and nothing else checks.
  window.__frames = { sampleRate: context.sampleRate, samplesPerFrame: frame.length };
}

function onServerEvent(event) {
  switch (event.type) {
    case 'ready':
      setStatus('listening');
      break;
    case 'phase':
      ui.phase.textContent = event.phase.replace(/_/g, ' ');
      break;
    case 'utterance_begin':
      pendingUtterance = event.utterance_id;
      ui.examiner.textContent = event.text;
      setStatus('examiner speaking');
      break;
    case 'utterance_end':
      // All the audio has arrived; report back once the queue drains.
      reportWhenDrained(event.utterance_id);
      break;
    case 'stop_playback':
      stopPlayback();
      break;
    case 'session_end':
      sessionFinished = true;
      setStatus(`finished (${event.reason})`);
      socket.close();
      break;
  }
}

function onAudio(buffer) {
  const samples = new Int16Array(buffer);
  const audio = context.createBuffer(1, samples.length, SAMPLE_RATE);
  const channel = audio.getChannelData(0);
  for (let i = 0; i < samples.length; i++) channel[i] = samples[i] / 0x8000;

  const source = context.createBufferSource();
  source.buffer = audio;
  source.connect(context.destination);
  // Schedule back to back. Starting each chunk at `currentTime` instead would
  // leave audible gaps whenever a chunk arrives late.
  playbackCursor = Math.max(playbackCursor, context.currentTime);
  source.start(playbackCursor);
  playbackCursor += audio.duration;

  queuedSources.push(source);
  source.onended = () => {
    queuedSources = queuedSources.filter((queued) => queued !== source);
    drained();
  };
}

function reportWhenDrained(utteranceId) {
  pendingUtterance = utteranceId;
  drained();
}

function drained() {
  if (pendingUtterance === null || queuedSources.length > 0) return;
  socket.send(JSON.stringify({ type: 'playback_finished', utterance_id: pendingUtterance }));
  pendingUtterance = null;
  setStatus('listening');
}

function stopPlayback() {
  queuedSources.forEach((source) => {
    source.onended = null;
    source.stop();
  });
  queuedSources = [];
  playbackCursor = 0;
  pendingUtterance = null;
  setStatus('listening');
}

function updateMeter(frame) {
  let sum = 0;
  for (let i = 0; i < frame.length; i++) sum += frame[i] * frame[i];
  const level = Math.sqrt(sum / frame.length) / 0x8000;
  ui.meter.style.width = `${Math.min(100, level * 400)}%`;
}

function setStatus(text) {
  ui.status.textContent = text;
}

function fail(message) {
  setStatus(`error: ${message}`);
  socket?.send?.(JSON.stringify({ type: 'client_error', message }));
}
