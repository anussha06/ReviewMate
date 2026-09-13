/**
 * React Bits — LetterGlitch Background Component
 * Pure JavaScript canvas implementation matching the official React Bits component.
 *
 * Config:
 * - glitchSpeed: 50
 * - centerVignette: true
 * - outerVignette: false
 * - smooth: true
 * - colors: ["#2b4539", "#61dca3", "#61b3dc"]
 */

(function () {
  'use strict';

  class LetterGlitch {
    constructor(options = {}) {
      this.container = options.container || document.getElementById('letterGlitchBackground');
      this.canvas = options.canvas || document.getElementById('letterGlitchCanvas');
      if (!this.canvas) return;

      this.glitchColors = options.colors || options.glitchColors || ['#2b4539', '#61dca3', '#61b3dc'];
      this.glitchSpeed = options.glitchSpeed !== undefined ? options.glitchSpeed : 50;
      this.centerVignette = options.centerVignette !== undefined ? options.centerVignette : true;
      this.outerVignette = options.outerVignette !== undefined ? options.outerVignette : false;
      this.smooth = options.smooth !== undefined ? options.smooth : true;
      this.characters = options.characters || 'ABCDEFGHIJKLMNOPQRSTUVWXYZ!@#$&*()-_+=/[]{};:<>.,0123456789';

      this.context = null;
      this.animationFrameId = null;
      this.letters = [];
      this.grid = { columns: 0, rows: 0 };
      this.lastGlitchTime = Date.now();

      this.lettersAndSymbols = Array.from(this.characters);
      this.fontSize = 15;
      this.charWidth = 11;
      this.charHeight = 22;

      this.init();
    }

    getRandomChar() {
      return this.lettersAndSymbols[Math.floor(Math.random() * this.lettersAndSymbols.length)];
    }

    getRandomColor() {
      return this.glitchColors[Math.floor(Math.random() * this.glitchColors.length)];
    }

    hexToRgb(hex) {
      if (!hex) return null;
      const shorthandRegex = /^#?([a-f\d])([a-f\d])([a-f\d])$/i;
      const cleanHex = hex.replace(shorthandRegex, (m, r, g, b) => r + r + g + g + b + b);
      const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(cleanHex);
      return result
        ? {
            r: parseInt(result[1], 16),
            g: parseInt(result[2], 16),
            b: parseInt(result[3], 16),
          }
        : null;
    }

    interpolateColor(start, end, factor) {
      const r = Math.round(start.r + (end.r - start.r) * factor);
      const g = Math.round(start.g + (end.g - start.g) * factor);
      const b = Math.round(start.b + (end.b - start.b) * factor);
      return `rgb(${r}, ${g}, ${b})`;
    }

    calculateGrid(width, height) {
      const columns = Math.ceil(width / this.charWidth);
      const rows = Math.ceil(height / this.charHeight);
      return { columns, rows };
    }

    initializeLetters(columns, rows) {
      this.grid = { columns, rows };
      const totalLetters = columns * rows;
      this.letters = Array.from({ length: totalLetters }, () => ({
        char: this.getRandomChar(),
        color: this.getRandomColor(),
        targetColor: this.getRandomColor(),
        colorProgress: 1,
      }));
    }

    resizeCanvas() {
      if (!this.canvas) return;
      const parent = this.container || this.canvas.parentElement;
      if (!parent) return;

      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const rect = parent.getBoundingClientRect();
      const width = rect.width || window.innerWidth;
      const height = rect.height || window.innerHeight;

      this.canvas.width = width * dpr;
      this.canvas.height = height * dpr;
      this.canvas.style.width = `${width}px`;
      this.canvas.style.height = `${height}px`;

      if (this.context) {
        this.context.setTransform(dpr, 0, 0, dpr, 0, 0);
      }

      const { columns, rows } = this.calculateGrid(width, height);
      this.initializeLetters(columns, rows);
      this.drawLetters();
    }

    drawLetters() {
      if (!this.context || this.letters.length === 0) return;
      const ctx = this.context;
      const rect = this.canvas.getBoundingClientRect();
      ctx.clearRect(0, 0, rect.width, rect.height);
      ctx.font = `${this.fontSize}px 'JetBrains Mono', monospace`;
      ctx.textBaseline = 'top';

      for (let index = 0; index < this.letters.length; index++) {
        const letter = this.letters[index];
        const x = (index % this.grid.columns) * this.charWidth;
        const y = Math.floor(index / this.grid.columns) * this.charHeight;
        ctx.fillStyle = letter.color;
        ctx.fillText(letter.char, x, y);
      }
    }

    updateLetters() {
      if (!this.letters || this.letters.length === 0) return;
      // Glitch ~4% of letters on each update tick
      const updateCount = Math.max(1, Math.floor(this.letters.length * 0.04));

      for (let i = 0; i < updateCount; i++) {
        const index = Math.floor(Math.random() * this.letters.length);
        if (!this.letters[index]) continue;

        this.letters[index].char = this.getRandomChar();
        this.letters[index].targetColor = this.getRandomColor();

        if (!this.smooth) {
          this.letters[index].color = this.letters[index].targetColor;
          this.letters[index].colorProgress = 1;
        } else {
          this.letters[index].colorProgress = 0;
        }
      }
    }

    handleSmoothTransitions() {
      let needsRedraw = false;
      for (let i = 0; i < this.letters.length; i++) {
        const letter = this.letters[i];
        if (letter.colorProgress < 1) {
          letter.colorProgress += 0.05;
          if (letter.colorProgress > 1) letter.colorProgress = 1;

          const startRgb = this.hexToRgb(letter.color);
          const endRgb = this.hexToRgb(letter.targetColor);
          if (startRgb && endRgb) {
            letter.color = this.interpolateColor(startRgb, endRgb, letter.colorProgress);
            needsRedraw = true;
          }
        }
      }

      if (needsRedraw) {
        this.drawLetters();
      }
    }

    animate() {
      const now = Date.now();
      if (now - this.lastGlitchTime >= this.glitchSpeed) {
        this.updateLetters();
        this.drawLetters();
        this.lastGlitchTime = now;
      }

      if (this.smooth) {
        this.handleSmoothTransitions();
      }

      this.animationFrameId = requestAnimationFrame(() => this.animate());
    }

    init() {
      this.context = this.canvas.getContext('2d');
      this.resizeCanvas();
      this.animate();

      let resizeTimeout;
      window.addEventListener('resize', () => {
        clearTimeout(resizeTimeout);
        resizeTimeout = setTimeout(() => {
          if (this.animationFrameId) {
            cancelAnimationFrame(this.animationFrameId);
          }
          this.resizeCanvas();
          this.animate();
        }, 120);
      });
    }

    destroy() {
      if (this.animationFrameId) {
        cancelAnimationFrame(this.animationFrameId);
      }
    }
  }

  // Auto-initialize when DOM is ready
  function startGlitchBackground() {
    const canvas = document.getElementById('letterGlitchCanvas');
    if (!canvas) return;

    window.reviewMateLetterGlitch = new LetterGlitch({
      glitchSpeed: 50,
      centerVignette: true,
      outerVignette: false,
      smooth: true,
      speed: 10,
      colors: ['#2b4539', '#61dca3', '#61b3dc'],
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', startGlitchBackground);
  } else {
    startGlitchBackground();
  }
})();
