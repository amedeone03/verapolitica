// One motion vocabulary for the whole app. Feel: "crisp".
//
// Crisp means: press feedback lands on press-in (120ms), entrances are short and
// ease-out, exits take ~70% of the entrance, springs are critically damped (they
// settle, they do not wobble) and nothing moves unless the reader did something.
// Durations live in motion.css as custom properties; the spring and the gesture
// helpers below are the JS half of the same system.

export const reducedMotion = () => globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

// Critically damped: damping = 2·sqrt(stiffness·mass) ≈ 45.6, settles in ~200ms.
export const SPRING = { stiffness: 520, damping: 46, mass: 1 };

// iOS-style rubber band: resistance grows the further you pull past an edge.
export function rubberband(overflow, dimension, constant = 0.55) {
  if (overflow <= 0 || dimension <= 0) return 0;
  return (1 - 1 / ((overflow * constant) / dimension + 1)) * dimension;
}

// Where a flick would come to rest (UIScrollView's normal deceleration).
// velocity in px/ms, result in px.
export function project(velocity, decelerationRate = 0.998) {
  return (velocity * decelerationRate) / (1 - decelerationRate);
}

// Animate a single value with a spring, starting from the gesture's velocity.
// Returns a cancel function, so a new touch can grab the element mid-flight.
export function animateSpring({ from, to, velocity = 0, onUpdate, onDone, spring = SPRING }) {
  if (reducedMotion()) { onUpdate(to); onDone?.(); return () => {}; }
  let x = from;
  let v = velocity * 1000; // px/s
  let last = performance.now();
  let frame = 0;
  let stopped = false;
  const step = (now) => {
    if (stopped) return;
    let dt = Math.min(0.064, (now - last) / 1000);
    last = now;
    while (dt > 0) { // fixed 4ms sub-steps keep the integration stable on slow frames
      const h = Math.min(dt, 0.004);
      const force = -spring.stiffness * (x - to) - spring.damping * v;
      v += (force / spring.mass) * h;
      x += v * h;
      dt -= h;
    }
    if (Math.abs(x - to) < 0.5 && Math.abs(v) < 20) { onUpdate(to); onDone?.(); return; }
    onUpdate(x);
    frame = requestAnimationFrame(step);
  };
  frame = requestAnimationFrame(step);
  return () => { stopped = true; cancelAnimationFrame(frame); };
}

// Vertical drag that follows the finger 1:1. It only takes over after a few
// pixels, so taps and clicks inside the element still work; once it has taken
// over, the click that would follow is swallowed. onEnd receives the total
// offset and the release velocity (px/ms) measured over the last ~80ms.
export function attachVerticalDrag(element, { enabled = () => true, onStart, onMove, onEnd, threshold = 6 }) {
  let start = null;
  let samples = [];
  let dragging = false;
  const velocity = () => {
    const now = samples[samples.length - 1];
    const old = samples.find((sample) => now.t - sample.t <= 80) || samples[0];
    const dt = now.t - old.t;
    return dt > 0 ? (now.y - old.y) / dt : 0;
  };
  element.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || !enabled(event)) return;
    start = { x: event.clientX, y: event.clientY, id: event.pointerId };
    samples = [{ y: event.clientY, t: event.timeStamp }];
    dragging = false;
  });
  element.addEventListener("pointermove", (event) => {
    if (!start || event.pointerId !== start.id) return;
    const dy = event.clientY - start.y;
    if (!dragging) {
      if (Math.abs(dy) < threshold || Math.abs(dy) < Math.abs(event.clientX - start.x)) return;
      dragging = true;
      element.setPointerCapture?.(event.pointerId);
      onStart?.();
    }
    samples.push({ y: event.clientY, t: event.timeStamp });
    if (samples.length > 12) samples.shift();
    onMove(dy);
  });
  const finish = (event) => {
    if (!start || event.pointerId !== start.id) return;
    const was = dragging;
    const dy = event.clientY - start.y;
    start = null;
    dragging = false;
    if (!was) return;
    samples.push({ y: event.clientY, t: event.timeStamp });
    const swallow = (click) => { click.preventDefault(); click.stopPropagation(); };
    element.addEventListener("click", swallow, { capture: true, once: true });
    setTimeout(() => element.removeEventListener("click", swallow, { capture: true }), 0);
    onEnd(dy, event.type === "pointercancel" ? 0 : velocity());
  };
  element.addEventListener("pointerup", finish);
  element.addEventListener("pointercancel", finish);
}

// ---------------------------------------------------------------------------
// Toast: one shared component. It enters from the bottom edge, stays long
// enough to be read (4s minimum, more for long text or a link to act on),
// pauses while touched, hovered or focused, can be swiped away, and is
// announced through a live region that exists before any message arrives.
const EXIT_MS = 150; // keep in step with --dur-exit in motion.css
let toastTimer = 0;
let toastDeadline = 0;
let toastRemaining = 0;
let toastHolds = 0;
let toastBound = false;

function toastNodes() {
  let root = document.getElementById("toast");
  if (!root) {
    document.body.insertAdjacentHTML("beforeend", `<div id="toast" class="toast" hidden></div><p id="toast-live" class="visually-hidden" role="status" aria-live="polite" aria-atomic="true"></p>`);
    root = document.getElementById("toast");
  }
  return { root, live: document.getElementById("toast-live") };
}

export function toastDuration(text, hasAction = false) {
  const base = Math.min(8000, Math.max(4000, 1800 + text.length * 55));
  return hasAction ? Math.max(base, 6000) : base;
}

function scheduleHide(ms) {
  clearTimeout(toastTimer);
  toastRemaining = ms;
  toastDeadline = performance.now() + ms;
  if (!toastHolds) toastTimer = setTimeout(hideToast, ms);
}

function hold() {
  if (toastHolds++ === 0) { clearTimeout(toastTimer); toastRemaining = Math.max(1500, toastDeadline - performance.now()); }
}

function release() {
  if (toastHolds === 0) return;
  if (--toastHolds === 0) scheduleHide(toastRemaining);
}

export function hideToast() {
  const { root } = toastNodes();
  clearTimeout(toastTimer);
  toastHolds = 0;
  if (root.hidden || !root.classList.contains("is-visible")) return;
  root.classList.remove("is-visible");
  if (reducedMotion()) { root.hidden = true; return; }
  root.classList.add("is-leaving");
  setTimeout(() => { if (!root.classList.contains("is-visible")) { root.hidden = true; root.classList.remove("is-leaving"); root.style.removeProperty("--toast-y"); } }, EXIT_MS);
}

function bindToast(root) {
  if (toastBound) return;
  toastBound = true;
  root.addEventListener("pointerenter", hold);
  root.addEventListener("pointerleave", release);
  root.addEventListener("focusin", hold);
  root.addEventListener("focusout", release);
  document.addEventListener("visibilitychange", () => (document.hidden ? hold() : release()));
  // Swipe down to dismiss; pulling up only stretches a little (rubber band).
  let y = 0;
  attachVerticalDrag(root, {
    onStart: () => { root.classList.add("is-dragging"); },
    onMove: (dy) => {
      y = dy >= 0 ? dy : -rubberband(-dy, 120);
      root.style.setProperty("--toast-y", `${y}px`);
    },
    onEnd: (dy, v) => {
      root.classList.remove("is-dragging");
      if (dy > 32 || v > 0.35) { root.style.removeProperty("--toast-y"); hideToast(); return; }
      animateSpring({ from: y, to: 0, velocity: v, onUpdate: (value) => root.style.setProperty("--toast-y", `${value}px`), onDone: () => root.style.removeProperty("--toast-y") });
    },
  });
}

export function toast(html, { duration } = {}) {
  const { root, live } = toastNodes();
  bindToast(root);
  const wasVisible = root.classList.contains("is-visible");
  root.innerHTML = html;
  const text = root.textContent.trim();
  const ms = duration ?? toastDuration(text, Boolean(root.querySelector("a, button")));
  // Re-announce even an identical message: clear, then write on the next frame.
  live.textContent = "";
  requestAnimationFrame(() => { live.textContent = text; });
  root.classList.remove("is-leaving");
  if (!wasVisible) {
    root.hidden = false;
    void root.offsetWidth; // commit the hidden pose so the entrance transitions
    root.classList.add("is-visible");
  }
  scheduleHide(ms);
}
