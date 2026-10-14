import registry from "./generated/profile-caps.json";
export const profileCaps = registry.profiles;
export function nominalFps(fps) {
  const value = Number(fps),
    nearest = Math.round(value);
  return nearest > 0 && Math.abs(value - nearest) <= 0.1 ? nearest : value;
}
export const coldCapKey = (width, height, fps) =>
  `${width}x${height}@${nominalFps(fps)}`;
function cadenceIntervals(fps) {
  if (nominalFps(fps) === 24) return [2, 3];
  const interval = Math.max(1, Math.round(60000 / 1001 / fps));
  return interval <= 4 && Math.abs(60000 / 1001 / interval - fps) <= 0.01
    ? [interval]
    : null;
}
export function parseColdCap(value, fps) {
  const text = String(value).trim();
  const within = (v) =>
    Number.isSafeInteger(v) && v > 0 && v <= registry.maxColdCap;
  if (/^\d+$/.test(text) && within(Number(text)))
    return {
      valid: true,
      spec: { "*": Number(text) },
      value: String(Number(text)),
    };
  const spec = {};
  for (const part of text.split(",")) {
    const match = part.trim().match(/^([1-4])\s*:\s*(\d+)$/);
    if (!match || spec[match[1]] || !within(Number(match[2])))
      return { valid: false };
    spec[match[1]] = Number(match[2]);
  }
  const intervals = cadenceIntervals(Number(fps));
  if (
    !intervals ||
    Object.keys(spec).length !== intervals.length ||
    intervals.some((n) => !spec[n])
  )
    return { valid: false };
  return {
    valid: true,
    spec,
    value: intervals.map((n) => `${n}:${spec[n]}`).join(","),
  };
}
export function selectColdCap(width, height, fps, profiles = profileCaps) {
  const rate = nominalFps(fps),
    key = coldCapKey(width, height, fps);
  const matches = profiles.filter(
    (p) =>
      p.width === width && p.height === height && nominalFps(p.fps) === rate,
  );
  if (matches.length) {
    const specs = matches.map((p) => parseColdCap(p.cap, Number(fps)).spec);
    const intervals = [
      ...new Set(specs.flatMap((s) => Object.keys(s).filter((k) => k !== "*"))),
    ].sort();
    const value = intervals.length
      ? intervals
          .map((n) => `${n}:${Math.min(...specs.map((s) => s["*"] ?? s[n]))}`)
          .join(",")
      : String(Math.min(...specs.map((s) => s["*"])));
    return {
      value,
      key,
      kind: "profile",
      profiles: matches.map((p) => p.profile),
      reason: `Profile match · ${width} × ${height} / ${rate} fps${matches.length > 1 ? " · lowest matching caps" : ""}`,
    };
  }
  const cells = Math.floor(width / 8) * Math.floor(height / 8);
  const sameRate = profiles.filter((p) => nominalFps(p.fps) === rate);
  const references = sameRate.length ? sameRate : profiles;
  const slots =
    rate === 24
      ? [2, 3]
      : [Math.max(1, Math.floor(60 / Math.max(1, rate) + 1e-8))];
  const estimated = slots.map((slot) => {
    const candidates = references.flatMap((profile) => {
      const sourceCells =
        Math.floor(profile.width / 8) * Math.floor(profile.height / 8);
      const spec = parseColdCap(profile.cap, profile.fps).spec;
      // Preserve individual display-slot limits. Scalar caps use their frame duration.
      const entries =
        sameRate.length && spec[slot]
          ? [[String(slot), spec[slot]]]
          : Object.entries(spec);
      return entries.map(([interval, cap]) => {
        const sourceSlots =
          interval === "*" ? 60 / nominalFps(profile.fps) : Number(interval);
        return cap * (sourceCells / cells) * (slot / sourceSlots);
      });
    });
    // Round down to five-load steps; never infer a capacity above the VRAM pool.
    return Math.max(
      1,
      Math.min(
        registry.maxColdCap,
        Math.floor(Math.min(...candidates) / 5) * 5,
      ),
    );
  });
  const value =
    rate === 24
      ? slots.map((slot, index) => `${slot}:${estimated[index]}`).join(",")
      : String(estimated[0]);
  return {
    value,
    key,
    kind: "fallback",
    profiles: references.map((p) => p.profile),
    reason: `Profile-based estimate · tile count${sameRate.length ? " · same fps" : " and display time"} · unverified`,
  };
}
