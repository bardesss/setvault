// Convert BBC audiowaveform JSON (v2, interleaved min/max) into the shape
// wavesurfer's `peaks` + `duration` options expect. Returns null for anything
// that isn't a usable v2 document so the caller can fall back to decoding.

export interface WavePeaks {
  peaks: Float32Array[];
  duration: number;
}

export function toPeaks(json: unknown, fallbackDuration?: number): WavePeaks | null {
  if (!json || typeof json !== "object") return null;
  const j = json as Record<string, unknown>;
  if (j.version !== 2) return null;
  const data = j.data;
  if (!Array.isArray(data) || data.length === 0 || data.length % 2 !== 0) return null;
  if (!data.every((v) => typeof v === "number" && Number.isFinite(v))) return null;

  const bits = typeof j.bits === "number" && j.bits > 0 ? j.bits : 8;
  const scale = 2 ** (bits - 1);
  const n = data.length / 2;
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const m = Math.max(Math.abs(data[2 * i] as number), Math.abs(data[2 * i + 1] as number));
    out[i] = Math.min(1, m / scale);
  }

  const { length, sample_rate: sr, samples_per_pixel: spp } = j;
  let duration: number | null = null;
  if (typeof length === "number" && typeof sr === "number" && typeof spp === "number" && sr > 0 && length > 0 && spp > 0) {
    duration = (length * spp) / sr;
  } else if (typeof fallbackDuration === "number" && fallbackDuration > 0) {
    duration = fallbackDuration;
  }
  if (duration === null) return null;
  return { peaks: [out], duration };
}
