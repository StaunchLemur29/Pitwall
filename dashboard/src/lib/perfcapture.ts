// Records a performance capture for a fixed time and sends it to the rig,
// which saves it as a JSON file in Pitwall's data folder.

import { perf, rig } from "./rig";

export interface CaptureResult {
  ok: boolean;
  path?: string;
  error?: string;
}

function gpuInfo(): Record<string, unknown> {
  try {
    const c = document.createElement("canvas");
    const gl = (c.getContext("webgl2") || c.getContext("webgl")) as WebGLRenderingContext | null;
    if (!gl) return { webgl: false };
    const dbg = gl.getExtension("WEBGL_debug_renderer_info");
    return {
      webgl: true,
      vendor: dbg ? gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL) : gl.getParameter(gl.VENDOR),
      renderer: dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER),
    };
  } catch (e) {
    return { error: String(e) };
  }
}

function summarise(xs: number[]) {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  const q = (p: number) => Math.round(s[Math.min(s.length - 1, Math.floor(p * s.length))] * 100) / 100;
  return { n: s.length, avg: Math.round((s.reduce((a, b) => a + b, 0) / s.length) * 100) / 100, p50: q(0.5), p95: q(0.95), p99: q(0.99), max: q(1) };
}

export async function capturePerformance(seconds: number, onProgress?: (left: number) => void): Promise<CaptureResult> {
  const frames: number[] = []; // ms between display frames
  const arrivals: number[] = []; // ms between telemetry messages
  const ages: number[] = []; // data age when it arrived
  const longTasks: { start: number; ms: number }[] = [];
  const t0 = performance.now();
  let last = t0;
  let lastMsg = 0;
  const updates0 = perf.storeUpdates;

  let observer: PerformanceObserver | null = null;
  try {
    observer = new PerformanceObserver((list) => {
      for (const e of list.getEntries()) longTasks.push({ start: Math.round(e.startTime - t0), ms: Math.round(e.duration) });
    });
    observer.observe({ type: "longtask", buffered: false });
  } catch {
    observer = null;
  }
  const off = rig.onFrame(() => {
    const now = performance.now();
    if (lastMsg) arrivals.push(now - lastMsg);
    lastMsg = now;
  });
  // data age comes from the lag stats the store already keeps
  const ageTimer = window.setInterval(() => {
    const a = (window as unknown as { __pitwallLagAges?: () => number[] }).__pitwallLagAges?.();
    if (a) ages.push(...a);
  }, 1000);

  await new Promise<void>((resolve) => {
    const tick = (now: number) => {
      frames.push(now - last);
      last = now;
      const left = seconds - (now - t0) / 1000;
      onProgress?.(Math.max(0, Math.ceil(left)));
      if (left <= 0) resolve();
      else requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });
  off();
  observer?.disconnect();
  window.clearInterval(ageTimer);

  const svgNodes = document.querySelectorAll("svg *").length;
  const report = {
    seconds,
    when: new Date().toISOString(),
    frame_ms: summarise(frames),
    fps_avg: frames.length / seconds,
    frames_over_33ms: frames.filter((f) => f > 33.4).length,
    frames_over_50ms: frames.filter((f) => f > 50).length,
    telemetry_gap_ms: summarise(arrivals),
    data_age_ms: summarise(ages),
    store_updates_per_s: (perf.storeUpdates - updates0) / seconds,
    long_tasks: longTasks.slice(0, 200),
    long_task_total_ms: longTasks.reduce((a, b) => a + b.ms, 0),
    page: {
      url: location.href,
      view: `${innerWidth}x${innerHeight}`,
      dpr: devicePixelRatio,
      screen: `${screen.width}x${screen.height}`,
      svg_nodes: svgNodes,
      dom_nodes: document.getElementsByTagName("*").length,
      visible: document.visibilityState,
      focused: document.hasFocus(),
    },
    browser: {
      ua: navigator.userAgent,
      cores: navigator.hardwareConcurrency,
      memory_gb: (navigator as unknown as { deviceMemory?: number }).deviceMemory ?? null,
      js_heap_mb:
        (performance as unknown as { memory?: { usedJSHeapSize: number } }).memory?.usedJSHeapSize != null
          ? Math.round((performance as unknown as { memory: { usedJSHeapSize: number } }).memory.usedJSHeapSize / 1e6)
          : null,
    },
    gpu: gpuInfo(),
  };
  try {
    const r = await fetch("/api/perf-report", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(report),
    });
    const body = await r.json();
    return r.ok ? { ok: true, path: body.path } : { ok: false, error: JSON.stringify(body) };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
}
