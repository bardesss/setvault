/** One piece of a translated sentence: plain text, or a value to show in
 *  `<code>`. */
export interface CodePart {
  text: string;
  code: boolean;
}

type Translate = (key: string, opts?: { values?: Record<string, string | number> }) => string;

/** Translates `key` with each `codes` value swapped for a marker, then splits
 *  the result so the markup can wrap those values in `<code>` while the
 *  sentence stays one message. */
export function codeParts(
  t: Translate,
  key: string,
  codes: Record<string, string>,
  values: Record<string, string | number> = {},
): CodePart[] {
  const names = Object.keys(codes);
  const markers: Record<string, string> = {};
  names.forEach((name, i) => (markers[name] = `\u0001${i}\u0002`));
  const msg = t(key, { values: { ...values, ...markers } });
  return msg
    .split(/\u0001(\d+)\u0002/)
    .map((piece, i) =>
      i % 2 === 1 ? { text: codes[names[Number(piece)]] ?? "", code: true } : { text: piece, code: false },
    )
    .filter((p) => p.text !== "" || p.code);
}
