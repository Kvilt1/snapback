import { playSVG, pauseSVG, fmtAudio } from './utils.js';

const BAR_COUNT = 38;
const BAR_WIDTH = 6;
const BAR_GAP   = 4;
const CANVAS_H  = 64;
const CANVAS_W  = BAR_COUNT * (BAR_WIDTH + BAR_GAP);
const SPEED_OPS = [1, 1.5, 2];

export const audioPlayers = [];

export class AudioPlayer {
  constructor({ audioSrc, color, container }) {
    this.audioSrc = audioSrc;
    this.color    = color;

    this.isPlaying     = false;
    this.currentTime   = 0;
    this.duration      = 0;
    this.playbackRate  = 1;
    this.isReady       = false;
    this.waveformData  = [];
    this.hoverProgress = null;
    this.isDragging    = false;

    this._animId    = null;
    this._lastFrame = 0;

    this._buildDOM(container);
    this._setupAudio();
    this._startLoop();
    
    audioPlayers.push(this);
  }

  _buildDOM(container) {
    const card = document.createElement('div');
    card.className = 'audio-player';

    const playBtn = document.createElement('button');
    playBtn.className = 'play-btn';
    playBtn.disabled  = true;
    playBtn.innerHTML = playSVG(this.color);
    playBtn.addEventListener('click', () => this._togglePlay());
    this._playBtn = playBtn;

    const canvas = document.createElement('canvas');
    canvas.className = 'waveform-canvas';
    canvas.width  = CANVAS_W;
    canvas.height = CANVAS_H;
    canvas.addEventListener('mousedown',  e => this._onMouseDown(e));
    canvas.addEventListener('mousemove',  e => this._onMouseMove(e));
    canvas.addEventListener('mouseup',    ()  => this._onMouseUp());
    canvas.addEventListener('mouseleave', ()  => this._onMouseLeave());
    this._canvas = canvas;
    this._ctx    = canvas.getContext('2d');

    const speedBtn = document.createElement('button');
    speedBtn.className = 'speed-btn';
    speedBtn.disabled  = true;
    speedBtn.innerHTML = '<span>1x</span>';
    speedBtn.addEventListener('click', () => this._cycleSpeed());
    this._speedBtn  = speedBtn;
    this._speedSpan = speedBtn.querySelector('span');

    const timeEl = document.createElement('span');
    timeEl.className   = 'time-display';
    timeEl.textContent = '0:00';
    this._timeEl = timeEl;

    card.append(playBtn, canvas, speedBtn, timeEl);
    container.appendChild(card);

    this._drawPlaceholder();
  }

  _drawPlaceholder() {
    const ctx = this._ctx;
    ctx.clearRect(0, 0, CANVAS_W, CANVAS_H);
    for (let i = 0; i < BAR_COUNT; i++) {
      const x = i * (BAR_WIDTH + BAR_GAP);
      const h = BAR_WIDTH;
      const y = (CANVAS_H - h) / 2;
      const r = BAR_WIDTH / 2;
      ctx.fillStyle = '#3A3A3C';
      ctx.beginPath();
      ctx.arc(x + r, y + r, r, Math.PI, 0, false);
      ctx.arc(x + r, y + h - r, r, 0, Math.PI, false);
      ctx.closePath();
      ctx.fill();
    }
  }

  _setupAudio() {
    const audio = new Audio(this.audioSrc);
    this._audio = audio;

    audio.addEventListener('loadedmetadata', () => {
      this.duration = audio.duration;
      this._updateTime();
      this._buildWaveform();
    });

    audio.addEventListener('timeupdate', () => {
      this.currentTime = audio.currentTime;
      this._updateTime();
    });

    audio.addEventListener('play',  () => { this.isPlaying = true;  this._updatePlayBtn(); });
    audio.addEventListener('pause', () => { this.isPlaying = false; this._updatePlayBtn(); });
    audio.addEventListener('ended', () => { this.isPlaying = false; this._updatePlayBtn(); });
  }

  async _buildWaveform() {
    try {
      const actx    = new (window.AudioContext || window.webkitAudioContext)();
      const resp    = await fetch(this.audioSrc);
      const buf     = await resp.arrayBuffer();
      const decoded = await actx.decodeAudioData(buf);
      actx.close();

      const raw       = decoded.getChannelData(0);
      const blockSize = Math.floor(raw.length / BAR_COUNT);
      const rawBars   = [];

      for (let i = 0; i < BAR_COUNT; i++) {
        let sum = 0;
        for (let j = 0; j < blockSize; j++) sum += Math.abs(raw[i * blockSize + j]);
        rawBars.push(sum / blockSize);
      }

      const max = Math.max(...rawBars);
      this.waveformData = rawBars.map(v => Math.max(BAR_WIDTH, (v / max) * CANVAS_H));
      this._markReady();
    } catch (err) {
      console.error('Waveform error:', err);
      this.waveformData = Array.from({ length: BAR_COUNT }, (_, i) =>
        Math.max(BAR_WIDTH, (0.3 + 0.5 * Math.sin(i / BAR_COUNT * Math.PI * 4 + 1)) * CANVAS_H)
      );
      this._markReady();
    }
  }

  _markReady() {
    this.isReady = true;
    this._playBtn.disabled  = false;
    this._speedBtn.disabled = false;
  }

  _startLoop() {
    const tick = ts => {
      if (ts - this._lastFrame >= 1000 / 24) {
        this._lastFrame = ts;
        this._draw();
      }
      this._animId = requestAnimationFrame(tick);
    };
    this._animId = requestAnimationFrame(tick);
  }

  _draw() {
    if (!this._ctx || this.waveformData.length === 0) return;
    const ctx  = this._ctx;
    const data = this.waveformData;

    ctx.clearRect(0, 0, CANVAS_W, CANVAS_H);

    const t        = this._audio ? this._audio.currentTime : 0;
    const progress = this.duration > 0 ? t / this.duration : 0;
    const pBars    = progress * data.length;

    const dragBars    = (this.hoverProgress !== null && this.isDragging) ? this.hoverProgress * data.length : null;
    const displayBars = dragBars !== null ? dragBars : pBars;

    data.forEach((h, i) => {
      const x = i * (BAR_WIDTH + BAR_GAP);
      const y = (CANVAS_H - h) / 2;
      const r = BAR_WIDTH / 2;

      if (i < Math.floor(displayBars)) {
        ctx.fillStyle = this.color;
        ctx.beginPath();
        ctx.arc(x + r, y + r,     r, Math.PI, 0,       false);
        ctx.arc(x + r, y + h - r, r, 0,        Math.PI, false);
        ctx.closePath();
        ctx.fill();
      } else if (i === Math.floor(displayBars)) {
        const splitX = (displayBars - Math.floor(displayBars)) * BAR_WIDTH;

        ctx.save();
        ctx.beginPath(); ctx.rect(x + splitX, 0, BAR_WIDTH - splitX, CANVAS_H); ctx.clip();
        ctx.fillStyle = '#48484A';
        ctx.beginPath();
        ctx.arc(x + r, y + r,     r, Math.PI, 0,       false);
        ctx.arc(x + r, y + h - r, r, 0,        Math.PI, false);
        ctx.closePath(); ctx.fill();
        ctx.restore();

        ctx.save();
        ctx.beginPath(); ctx.rect(x, 0, splitX, CANVAS_H); ctx.clip();
        ctx.fillStyle = this.color;
        ctx.beginPath();
        ctx.arc(x + r, y + r,     r, Math.PI, 0,       false);
        ctx.arc(x + r, y + h - r, r, 0,        Math.PI, false);
        ctx.closePath(); ctx.fill();
        ctx.restore();
      } else {
        ctx.fillStyle = '#48484A';
        ctx.beginPath();
        ctx.arc(x + r, y + r,     r, Math.PI, 0,       false);
        ctx.arc(x + r, y + h - r, r, 0,        Math.PI, false);
        ctx.closePath();
        ctx.fill();
      }
    });
  }

  _togglePlay() {
    if (!this._audio || !this.isReady) return;
    if (this.isPlaying) {
      this._audio.pause();
      if (this._audio.currentTime < this._audio.duration) {
        this._audio.currentTime = 0;
      }
    } else {
      if (this._audio.currentTime >= this._audio.duration && this._audio.duration > 0) {
        this._audio.currentTime = 0;
      }
      this._audio.play().catch(err => console.error('Play error:', err));
    }
  }

  _cycleSpeed() {
    if (!this._audio || !this.isReady) return;
    const next = (SPEED_OPS.indexOf(this.playbackRate) + 1) % SPEED_OPS.length;
    this.playbackRate = SPEED_OPS[next];
    this._audio.playbackRate = this.playbackRate;
    this._speedSpan.textContent = this.playbackRate + 'x';
  }

  _onMouseDown(e) {
    this.isDragging    = true;
    const x            = e.clientX - this._canvas.getBoundingClientRect().left;
    this.hoverProgress = Math.max(0, Math.min(1, x / CANVAS_W));
  }

  _onMouseMove(e) {
    if (!this.isDragging) return;
    const x = e.clientX - this._canvas.getBoundingClientRect().left;
    this.hoverProgress = Math.max(0, Math.min(1, x / CANVAS_W));
  }

  _onMouseUp() {
    if (!this.isDragging) return;
    if (this.hoverProgress !== null && this._audio) {
      this._audio.currentTime = this.hoverProgress * this.duration;
    }
    this.isDragging    = false;
    this.hoverProgress = null;
  }

  _onMouseLeave() {
    if (this.isDragging) { this.isDragging = false; this.hoverProgress = null; }
  }

  _updatePlayBtn() {
    this._playBtn.innerHTML = this.isPlaying ? pauseSVG(this.color) : playSVG(this.color);
  }

  _updateTime() {
    const remaining = this.duration - this.currentTime;
    const display   = this.currentTime > 0 ? remaining : this.duration;
    this._timeEl.textContent = fmtAudio(display);
  }

  destroy() {
    if (this._animId) cancelAnimationFrame(this._animId);
    if (this._audio) { this._audio.pause(); this._audio.src = ''; }
  }
}

document.addEventListener('mouseup', () => audioPlayers.forEach(p => p._onMouseUp()));

export function initAudioPlayers() {
  document.querySelectorAll('[data-vn-pending]').forEach(el => {
    el.removeAttribute('data-vn-pending');
    new AudioPlayer({
      audioSrc:  el.dataset.audioSrc,
      color:     el.dataset.audioColor,
      container: el,
    });
  });
}

export function stopAllAudioPlayers() {
  audioPlayers.forEach(p => p.destroy());
  audioPlayers.length = 0;
}