import { describe, expect, it } from "vitest";
import { toPeaks } from "./waveform-peaks.ts";

const v2 = { version: 2, channels: 1, sample_rate: 44100, samples_per_pixel: 2205, bits: 8, length: 3, data: [-64, 64, -128, 127, 0, 32] };

describe("toPeaks", () => {
  it("converts audiowaveform v2", () => {
    const r = toPeaks(v2)!;
    expect(r).not.toBeNull();
    expect(r.peaks).toHaveLength(1);
    const expected = [0.5, 1.0, 0.25];
    expected.forEach((e, i) => expect(Math.abs(r.peaks[0][i] - e)).toBeLessThan(1e-3));
    expect(r.duration).toBeCloseTo((3 * 2205) / 44100, 6);
  });

  it("returns null for {}, odd data length, missing length or non-number data", () => {
    expect(toPeaks({})).toBeNull();
    expect(toPeaks(null)).toBeNull();
    expect(toPeaks({ ...v2, data: [1, 2, 3] })).toBeNull();
    const { length: _l, ...noLen } = v2;
    expect(toPeaks(noLen)).toBeNull();
    expect(toPeaks({ ...v2, data: [1, "x", 3, 4, 5, 6] })).toBeNull();
    expect(toPeaks({ ...v2, version: 1 })).toBeNull();
  });

  it("uses fallbackDuration when length/sample_rate are absent but data is valid", () => {
    const { length: _l, sample_rate: _s, ...rest } = v2;
    const r = toPeaks(rest, 120)!;
    expect(r.duration).toBe(120);
    expect(r.peaks[0]).toHaveLength(3);
  });
});
