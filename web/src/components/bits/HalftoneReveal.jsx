// From React Bits (reactbits.dev, HalftoneReveal, JavaScript + CSS variant), changed for laghu-voice:
// - it shows two finished pictures instead of printing one: `src` is what the page shows, `revealSrc` is what the
//   cursor's trail opens up, through the same screen of swelling dots (the component's own reveal);
// - the trail follows the pointer anywhere over the component, even over text laid on top of it (window events);
// - the print options (mode, inks, contrast, roughness...) are gone: the pictures come already printed.
// - `ignoreReducedMotion` keeps the intro and the wander when the system asks for less motion.
// The trail, its linger, the click ripple, the wander and the intro are the original's.
'use client';

import { useEffect, useRef } from 'react';

import './HalftoneReveal.css';

const VERTEX = `#version 300 es
in vec2 aPosition;
void main() {
  gl_Position = vec4(aPosition, 0.0, 1.0);
}`;

const MASK = `#version 300 es
precision highp float;
uniform sampler2D uPrevious;
uniform vec2 uTexture;
uniform vec2 uView;
uniform vec2 uFrom;
uniform vec2 uTo;
uniform float uRadius;
uniform float uSoftness;
uniform float uStrength;
uniform float uFade;
out vec4 outColor;

float segment(vec2 p, vec2 a, vec2 b) {
  vec2 ab = b - a;
  float h = clamp(dot(p - a, ab) / max(dot(ab, ab), 0.0001), 0.0, 1.0);
  return length(p - a - ab * h);
}

void main() {
  vec2 uv = gl_FragCoord.xy / uTexture;
  vec2 p = vec2(uv.x, 1.0 - uv.y) * uView;
  float trail = max(texture(uPrevious, uv).r - uFade, 0.0);
  float band = max(uRadius * uSoftness, 1.0);
  float brush = clamp((uRadius - segment(p, uFrom, uTo)) / band, 0.0, 1.0);
  brush = brush * brush * (3.0 - 2.0 * brush);
  outColor = vec4(max(trail, brush * uStrength), 0.0, 0.0, 1.0);
}`;

const VIEW = `#version 300 es
precision highp float;
uniform sampler2D uImage;
uniform sampler2D uReveal;
uniform sampler2D uMask;
uniform vec2 uResolution;
uniform vec2 uView;
uniform float uDpr;
uniform vec4 uFrame;
uniform float uShape;
uniform float uCell;
uniform float uAngle;
uniform vec3 uPaper;
uniform float uReverse;
uniform float uIntro;
uniform float uHasReveal;
uniform vec4 uBursts[4];
uniform float uBurstWidth;
out vec4 outColor;

mat2 rotate(float a) {
  float c = cos(a);
  float s = sin(a);
  return mat2(c, -s, s, c);
}

float hash(vec2 p) {
  p = fract(p * vec2(123.34, 456.21));
  p += dot(p, p + 45.32);
  return fract(p.x * p.y);
}

float metric(vec2 f) {
  if (uShape < 0.5) return length(f);
  if (uShape < 1.5) return length(f * vec2(0.8, 1.15));
  if (uShape < 2.5) return max(abs(f.x), abs(f.y));
  if (uShape < 3.5) return abs(f.x) + abs(f.y);
  if (uShape < 4.5) return abs(f.y);
  return min(abs(f.x), abs(f.y));
}

float reach(float t) {
  t = clamp(t, 0.0, 1.0);
  if (uShape < 0.5) return t < 0.785 ? sqrt(t / 3.14159) : mix(0.5, 0.72, (t - 0.785) / 0.215);
  if (uShape < 1.5) return t < 0.7 ? sqrt(t * 0.92 / 3.14159) : mix(0.4497, 0.72, (t - 0.7) / 0.3);
  if (uShape < 2.5) return 0.5 * sqrt(t) + 0.02 * t;
  if (uShape < 3.5) return t < 0.5 ? sqrt(t * 0.5) : 1.0 - sqrt((1.0 - t) * 0.5);
  if (uShape < 4.5) return 0.52 * t;
  return (1.0 - sqrt(1.0 - t)) * 0.5 + 0.02 * t;
}

vec3 picture(sampler2D image, vec2 p) {
  vec2 uv = (p - uFrame.xy) / uFrame.zw;
  vec4 c = texture(image, clamp(uv, 0.0, 1.0));
  vec2 inside = step(0.0, uv) * step(uv, vec2(1.0));
  return mix(uPaper, c.rgb, inside.x * inside.y * c.a);
}

float burst(vec2 p) {
  float value = 0.0;
  for (int i = 0; i < 4; i++) {
    vec4 b = uBursts[i];
    if (b.w <= 0.0) continue;
    float offset = distance(p, b.xy) - b.z;
    float edge = offset > 0.0 ? offset / (uBurstWidth * 0.35) : -offset / uBurstWidth;
    value = max(value, clamp(1.0 - edge, 0.0, 1.0) * b.w);
  }
  return value;
}

// how much of a cell's dot covers this pixel, for a dot grown to 'amount' (0 none, 1 the whole cell)
float cover(vec2 p, float amount) {
  vec2 q = rotate(uAngle) * p / uCell;
  float d = metric(fract(q) - 0.5);
  float r = reach(1.0) * 1.08 * amount;
  float w = max(fwidth(d), 0.0001) * 0.75;
  return smoothstep(r + w, r - w, d) * clamp(r / (w * 2.0), 0.0, 1.0);
}

void main() {
  vec2 p = vec2(gl_FragCoord.x, uResolution.y - gl_FragCoord.y) / uDpr;

  // the intro: the picture grows in from the centre, dot by dot
  vec2 field = p / max(uView.x, uView.y) - uView / max(uView.x, uView.y) * 0.5;
  float delay = length(field) * 1.15 + hash(floor(p / uCell)) * 0.06;
  float grow = smoothstep(0.0, 1.0, clamp((uIntro * 1.7 - delay) / 0.45, 0.0, 1.0));
  vec3 base = mix(uPaper, picture(uImage, p), cover(p, grow));

  // the trail: the second picture shows through dots that swell under the cursor and shrink back after it
  vec2 maskUv = vec2(p.x / uView.x, 1.0 - p.y / uView.y);
  float shown = max(texture(uMask, maskUv).r, burst(p));
  shown = mix(shown, 1.0 - shown, uReverse);
  shown = shown * shown * (3.0 - 2.0 * shown) * uHasReveal * grow;
  outColor = vec4(mix(base, picture(uReveal, p), cover(p, shown)), 1.0);
}`;

const SHAPES = { dot: 0, ellipse: 1, square: 2, diamond: 3, line: 4, cross: 5 };
const MAX_BURSTS = 4;
const BURST_SECONDS = 1.3;
const INTRO_SECONDS = 1.4;
const MASK_SCALE = 0.5;

const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

const compile = (gl, type, source) => {
  const shader = gl.createShader(type);
  if (!shader) return null;
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (gl.getShaderParameter(shader, gl.COMPILE_STATUS)) return shader;
  console.error(gl.getShaderInfoLog(shader));
  gl.deleteShader(shader);
  return null;
};

const link = (gl, fragmentSource) => {
  const vertex = compile(gl, gl.VERTEX_SHADER, VERTEX);
  const fragment = compile(gl, gl.FRAGMENT_SHADER, fragmentSource);
  const program = gl.createProgram();
  if (!vertex || !fragment || !program) return null;
  gl.attachShader(program, vertex);
  gl.attachShader(program, fragment);
  gl.bindAttribLocation(program, 0, 'aPosition');
  gl.linkProgram(program);
  gl.deleteShader(vertex);
  gl.deleteShader(fragment);
  if (gl.getProgramParameter(program, gl.LINK_STATUS)) return program;
  gl.deleteProgram(program);
  return null;
};

const locate = (gl, program, names) => {
  const result = {};
  for (const name of names) result[name] = gl.getUniformLocation(program, name);
  return result;
};

const wanderAt = (t, w, h) => [
  w * (0.5 + 0.32 * Math.sin(t * 0.53) + 0.08 * Math.sin(t * 1.31 + 0.6)),
  h * (0.5 + 0.27 * Math.sin(t * 0.71 + 1.1) + 0.07 * Math.cos(t * 1.57))
];

const HalftoneReveal = ({
  src,
  revealSrc,
  fit = 'cover',
  shape = 'dot',
  cellSize = 6,
  angle = 45,
  paperColor = '#ffffff',
  revealRadius = 160,
  softness = 0.6,
  linger = 1.2,
  reverse = false,
  wander = false,
  clickBurst = true,
  intro = true,
  ignoreReducedMotion = false,
  className = '',
  style
}) => {
  const containerRef = useRef(null);
  const canvasRef = useRef(null);
  const wakeRef = useRef(null);
  const settings = {
    fit,
    shape: SHAPES[shape] ?? 0,
    cellSize: clamp(cellSize, 2, 80),
    angle,
    paperColor: String(paperColor),
    revealRadius: Math.max(0, revealRadius),
    softness: clamp(softness, 0, 1),
    linger: Math.max(0, linger),
    reverse,
    wander,
    clickBurst,
    intro
  };
  const settingsRef = useRef(settings);
  settingsRef.current = settings;

  useEffect(() => {
    const container = containerRef.current;
    const canvas = canvasRef.current;
    const gl = canvas?.getContext('webgl2', {
      alpha: false,
      antialias: false,
      depth: false,
      stencil: false,
      preserveDrawingBuffer: false
    });
    if (!container || !canvas || !gl) return undefined;

    const maskProgram = link(gl, MASK);
    const viewProgram = link(gl, VIEW);
    if (!maskProgram || !viewProgram) return undefined;
    const maskUniforms = locate(gl, maskProgram, [
      'uPrevious', 'uTexture', 'uView', 'uFrom', 'uTo', 'uRadius', 'uSoftness', 'uStrength', 'uFade'
    ]);
    const viewUniforms = locate(gl, viewProgram, [
      'uImage', 'uReveal', 'uMask', 'uResolution', 'uView', 'uDpr', 'uFrame', 'uShape', 'uCell', 'uAngle',
      'uPaper', 'uReverse', 'uIntro', 'uHasReveal', 'uBursts', 'uBurstWidth'
    ]);

    const vao = gl.createVertexArray();
    const buffer = gl.createBuffer();
    gl.bindVertexArray(vao);
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
    gl.bindVertexArray(null);

    const floatMask = !!gl.getExtension('EXT_color_buffer_float');
    const makeTexture = () => {
      const texture = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, texture);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array(4));
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      return texture;
    };
    const imageTexture = makeTexture();
    const revealTexture = makeTexture();

    const createMask = (width, height) => {
      const texture = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, texture);
      if (floatMask) gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA16F, width, height, 0, gl.RGBA, gl.HALF_FLOAT, null);
      else gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, width, height, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      const framebuffer = gl.createFramebuffer();
      gl.bindFramebuffer(gl.FRAMEBUFFER, framebuffer);
      gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, texture, 0);
      gl.clearColor(0, 0, 0, 1);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.bindFramebuffer(gl.FRAMEBUFFER, null);
      return { texture, framebuffer, width, height };
    };
    const destroyMask = target => {
      gl.deleteFramebuffer(target.framebuffer);
      gl.deleteTexture(target.texture);
    };
    let masks = [createMask(2, 2), createMask(2, 2)];

    const probe = document.createElement('canvas').getContext('2d', { willReadFrequently: true });
    const reduce = !ignoreReducedMotion && (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false);
    const colorCache = new Map();
    const bursts = [];
    const burstData = new Float32Array(MAX_BURSTS * 4);
    const pointer = { x: 0, y: 0, inside: false, fresh: true, placed: false };
    const brush = { x: 0, y: 0, px: 0, py: 0 };
    const state = {
      width: 1,
      height: 1,
      dpr: 1,
      image: null,
      revealed: false,
      introStart: 0,
      presence: 0,
      drift: 0,
      trailUntil: 0
    };
    let raf = 0;
    let last = 0;
    let visible = true;
    let alive = true;

    const toRgb = value => {
      if (colorCache.has(value)) return colorCache.get(value);
      let rgb = [0, 0, 0];
      if (probe && value) {
        probe.clearRect(0, 0, 1, 1);
        probe.fillStyle = '#000000';
        probe.fillStyle = /^[0-9a-f]{3,8}$/i.test(value) ? `#${value}` : value;
        probe.fillRect(0, 0, 1, 1);
        const [r, g, b] = probe.getImageData(0, 0, 1, 1).data;
        rgb = [r / 255, g / 255, b / 255];
      }
      colorCache.set(value, rgb);
      return rgb;
    };

    const frameRect = s => {
      const { image, width, height } = state;
      if (!image) return [0, 0, width, height];
      const scale = (s.fit === 'cover' ? Math.max : Math.min)(width / image.naturalWidth, height / image.naturalHeight);
      const w = image.naturalWidth * scale;
      const h = image.naturalHeight * scale;
      return [(width - w) / 2, (height - h) / 2, w, h];
    };

    let resizePending = false;
    const applyResize = () => {
      const width = Math.max(1, container.clientWidth);
      const height = Math.max(1, container.clientHeight);
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      state.width = width;
      state.height = height;
      state.dpr = dpr;
      canvas.width = Math.max(1, Math.round(width * dpr));
      canvas.height = Math.max(1, Math.round(height * dpr));
      const mw = Math.max(2, Math.round(width * MASK_SCALE));
      const mh = Math.max(2, Math.round(height * MASK_SCALE));
      if (mw !== masks[0].width || mh !== masks[0].height) {
        const previous = masks;
        masks = [createMask(mw, mh), createMask(mw, mh)];
        gl.bindFramebuffer(gl.READ_FRAMEBUFFER, previous[0].framebuffer);
        gl.bindFramebuffer(gl.DRAW_FRAMEBUFFER, masks[0].framebuffer);
        gl.blitFramebuffer(0, 0, previous[0].width, previous[0].height, 0, 0, mw, mh, gl.COLOR_BUFFER_BIT, gl.NEAREST);
        gl.bindFramebuffer(gl.FRAMEBUFFER, null);
        previous.forEach(destroyMask);
      }
      if (!pointer.placed) {
        pointer.x = width / 2;
        pointer.y = height / 2;
      }
    };

    const resize = () => {
      resizePending = true;
      wake();
    };

    const drawMask = (s, dt) => {
      const minimum = floatMask ? 0 : 1.5 / 255;
      gl.bindFramebuffer(gl.FRAMEBUFFER, masks[1].framebuffer);
      gl.viewport(0, 0, masks[1].width, masks[1].height);
      gl.useProgram(maskProgram);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, masks[0].texture);
      gl.uniform1i(maskUniforms.uPrevious, 0);
      gl.uniform2f(maskUniforms.uTexture, masks[1].width, masks[1].height);
      gl.uniform2f(maskUniforms.uView, state.width, state.height);
      gl.uniform2f(maskUniforms.uFrom, brush.px, brush.py);
      gl.uniform2f(maskUniforms.uTo, brush.x, brush.y);
      gl.uniform1f(maskUniforms.uRadius, s.revealRadius * (0.45 + 0.55 * state.presence));
      gl.uniform1f(maskUniforms.uSoftness, s.softness);
      gl.uniform1f(maskUniforms.uStrength, state.presence);
      gl.uniform1f(maskUniforms.uFade, Math.max(s.linger > 0 ? dt / s.linger : 1, minimum));
      gl.bindVertexArray(vao);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
      gl.bindFramebuffer(gl.FRAMEBUFFER, null);
      masks.reverse();
    };

    const drawView = (s, now) => {
      const [fx, fy, fw, fh] = frameRect(s);
      const image = state.image;
      const intro = !image ? 0 : !s.intro || reduce ? 1 : Math.min(1, (now - state.introStart) / 1000 / INTRO_SECONDS);
      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.useProgram(viewProgram);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, imageTexture);
      gl.uniform1i(viewUniforms.uImage, 0);
      gl.activeTexture(gl.TEXTURE1);
      gl.bindTexture(gl.TEXTURE_2D, masks[0].texture);
      gl.uniform1i(viewUniforms.uMask, 1);
      gl.activeTexture(gl.TEXTURE2);
      gl.bindTexture(gl.TEXTURE_2D, revealTexture);
      gl.uniform1i(viewUniforms.uReveal, 2);
      gl.uniform2f(viewUniforms.uResolution, canvas.width, canvas.height);
      gl.uniform2f(viewUniforms.uView, state.width, state.height);
      gl.uniform1f(viewUniforms.uDpr, canvas.width / state.width);
      gl.uniform4f(viewUniforms.uFrame, fx, fy, fw, fh);
      gl.uniform1f(viewUniforms.uShape, s.shape);
      gl.uniform1f(viewUniforms.uCell, s.cellSize);
      gl.uniform1f(viewUniforms.uAngle, (s.angle * Math.PI) / 180);
      gl.uniform3fv(viewUniforms.uPaper, toRgb(s.paperColor));
      gl.uniform1f(viewUniforms.uReverse, s.reverse ? 1 : 0);
      gl.uniform1f(viewUniforms.uIntro, 1 - (1 - intro) * (1 - intro));
      gl.uniform1f(viewUniforms.uHasReveal, state.revealed ? 1 : 0);
      gl.uniform4fv(viewUniforms.uBursts, burstData);
      gl.uniform1f(viewUniforms.uBurstWidth, Math.max(60, s.revealRadius * 0.9));
      gl.bindVertexArray(vao);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
      gl.bindVertexArray(null);
      return intro;
    };

    const frame = now => {
      raf = 0;
      if (resizePending) {
        resizePending = false;
        applyResize();
      }
      if (!alive || !visible || document.hidden) return;
      const s = settingsRef.current;
      const dt = last ? Math.min(0.05, Math.max(0, (now - last) / 1000)) : 1 / 60;
      last = now;

      const wandering = s.wander && !reduce;
      let targetX = pointer.x;
      let targetY = pointer.y;
      if (!pointer.inside && wandering) {
        state.drift = Math.min(1, state.drift + dt / 1.2);
        const [wx, wy] = wanderAt(now / 1000, state.width, state.height);
        const k = state.drift * state.drift * (3 - 2 * state.drift);
        targetX += (wx - targetX) * k;
        targetY += (wy - targetY) * k;
      } else {
        state.drift = 0;
      }
      const engaged = pointer.inside || wandering;
      state.presence += ((engaged ? 1 : 0) - state.presence) * (1 - Math.exp(-dt / 0.16));
      if (pointer.fresh) {
        brush.x = brush.px = targetX;
        brush.y = brush.py = targetY;
        pointer.fresh = false;
      } else {
        const follow = 1 - Math.exp(-dt / 0.035);
        brush.x += (targetX - brush.x) * follow;
        brush.y += (targetY - brush.y) * follow;
      }

      burstData.fill(0);
      for (let i = bursts.length - 1; i >= 0; i--) {
        if ((now - bursts[i].start) / 1000 >= BURST_SECONDS) bursts.splice(i, 1);
      }
      bursts.forEach((b, i) => {
        const k = Math.max(0, (now - b.start) / 1000 / BURST_SECONDS);
        const reach = Math.hypot(Math.max(b.x, state.width - b.x), Math.max(b.y, state.height - b.y)) + 80;
        burstData[i * 4] = b.x;
        burstData[i * 4 + 1] = b.y;
        burstData[i * 4 + 2] = reach * Math.sin((k * Math.PI) / 2);
        burstData[i * 4 + 3] = 1 - k * k * k;
      });

      if (state.presence > 0.002) state.trailUntil = now + s.linger * 1000 + 200;
      drawMask(s, dt);
      brush.px = brush.x;
      brush.py = brush.y;
      const intro = drawView(s, now);

      const busy =
        engaged || state.presence > 0.002 || bursts.length > 0 || now < state.trailUntil || (state.image && intro < 1);
      if (busy) raf = requestAnimationFrame(frame);
      else last = 0;
    };

    const wake = () => {
      if (!raf && alive && visible && !document.hidden) raf = requestAnimationFrame(frame);
    };

    const load = (url, texture, done) => {
      if (!url) return null;
      const image = new Image();
      image.crossOrigin = 'anonymous';
      image.decoding = 'async';
      image.onload = () => {
        if (!alive) return;
        gl.bindTexture(gl.TEXTURE_2D, texture);
        gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, image);
        gl.generateMipmap(gl.TEXTURE_2D);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
        done(image);
        wake();
      };
      image.src = url;
      return image;
    };
    const shownImage = load(src, imageTexture, image => {
      state.image = image;
      state.introStart = performance.now();
    });
    const revealImage = load(revealSrc, revealTexture, () => {
      state.revealed = true;
    });

    // the pointer is followed over the whole component, also where other elements sit on top of it
    const locatePointer = event => {
      const rect = container.getBoundingClientRect();
      pointer.x = event.clientX - rect.left;
      pointer.y = event.clientY - rect.top;
      pointer.placed = true;
      return pointer.x >= 0 && pointer.y >= 0 && pointer.x <= rect.width && pointer.y <= rect.height;
    };
    const onMove = event => {
      const inside = locatePointer(event);
      if (inside && !pointer.inside) pointer.fresh = true;
      pointer.inside = inside;
      wake();
    };
    const onLeave = () => {
      pointer.inside = false;
      wake();
    };
    const onDown = event => {
      onMove(event);
      if (!pointer.inside) return;
      if (!settingsRef.current.clickBurst || (event.pointerType === 'mouse' && event.button !== 0)) return;
      bursts.push({ x: pointer.x, y: pointer.y, start: performance.now() });
      if (bursts.length > MAX_BURSTS) bursts.shift();
    };
    const onVisibility = () => {
      last = 0;
      wake();
    };

    window.addEventListener('pointermove', onMove, { passive: true });
    window.addEventListener('pointerdown', onDown, { passive: true });
    document.documentElement.addEventListener('pointerleave', onLeave, { passive: true });
    window.addEventListener('pointercancel', onLeave, { passive: true });
    document.addEventListener('visibilitychange', onVisibility);
    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(container);
    const intersection = new IntersectionObserver(entries => {
      visible = entries.some(entry => entry.isIntersecting);
      if (visible) {
        last = 0;
        wake();
      }
    });
    intersection.observe(container);
    resize();

    wakeRef.current = () => {
      if (!raf && alive && visible) {
        drawView(settingsRef.current, performance.now());
        wake();
      }
    };

    return () => {
      alive = false;
      cancelAnimationFrame(raf);
      wakeRef.current = null;
      if (shownImage) shownImage.onload = null;
      if (revealImage) revealImage.onload = null;
      resizeObserver.disconnect();
      intersection.disconnect();
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerdown', onDown);
      document.documentElement.removeEventListener('pointerleave', onLeave);
      window.removeEventListener('pointercancel', onLeave);
      document.removeEventListener('visibilitychange', onVisibility);
      masks.forEach(destroyMask);
      gl.deleteTexture(imageTexture);
      gl.deleteTexture(revealTexture);
      gl.deleteBuffer(buffer);
      gl.deleteVertexArray(vao);
      gl.deleteProgram(maskProgram);
      gl.deleteProgram(viewProgram);
    };
  }, [src, revealSrc]);

  useEffect(() => {
    wakeRef.current?.();
  });

  return (
    <div ref={containerRef} className={`halftone-reveal${className ? ` ${className}` : ''}`} style={style}>
      <canvas ref={canvasRef} className="halftone-reveal-canvas" aria-hidden="true" />
    </div>
  );
};

export default HalftoneReveal;
