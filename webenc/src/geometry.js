export const clamp = (v, min, max) => Math.max(min, Math.min(max, v));
export function normalizeCrop(rect, width, height) {
  const w = Math.round(clamp(Number(rect.w) || 1, 1, width));
  const h = Math.round(clamp(Number(rect.h) || 1, 1, height));
  return {
    x: Math.round(clamp(Number(rect.x) || 0, 0, width - w)),
    y: Math.round(clamp(Number(rect.y) || 0, 0, height - h)),
    w,
    h,
  };
}
export function dragCrop(start, handle, dx, dy, width, height, lock) {
  if (handle === "move")
    return normalizeCrop(
      { ...start, x: start.x + dx, y: start.y + dy },
      width,
      height,
    );
  let left = start.x,
    top = start.y,
    right = left + start.w,
    bottom = top + start.h;
  if (handle.includes("w")) left = clamp(left + dx, 0, right - 1);
  if (handle.includes("e")) right = clamp(right + dx, left + 1, width);
  if (handle.includes("n")) top = clamp(top + dy, 0, bottom - 1);
  if (handle.includes("s")) bottom = clamp(bottom + dy, top + 1, height);
  if (lock) {
    const ratio = start.w / start.h;
    let w = right - left,
      h = bottom - top;
    if (handle === "n" || handle === "s") w = h * ratio;
    else if (handle === "e" || handle === "w") h = w / ratio;
    else if (Math.abs(dx / start.w) > Math.abs(dy / start.h)) h = w / ratio;
    else w = h * ratio;
    const anchorX = handle.includes("w") ? start.x + start.w : start.x;
    const anchorY = handle.includes("n") ? start.y + start.h : start.y;
    const maxW = handle.includes("w") ? anchorX : width - anchorX;
    const maxH = handle.includes("n") ? anchorY : height - anchorY;
    w = Math.max(1, Math.min(w, maxW, maxH * ratio));
    h = w / ratio;
    left = handle.includes("w") ? anchorX - w : anchorX;
    top = handle.includes("n") ? anchorY - h : anchorY;
    right = left + w;
    bottom = top + h;
  }
  return normalizeCrop(
    { x: left, y: top, w: right - left, h: bottom - top },
    width,
    height,
  );
}
export function framing(crop, sar, width, height, fit) {
  const sourceAspect = (crop.w * sar) / crop.h;
  const outputAspect = (width * (32 / 35)) / height;
  let sx = crop.x,
    sy = crop.y,
    sw = crop.w,
    sh = crop.h;
  let dx = 0,
    dy = 0,
    dw = width,
    dh = height;
  if (fit === "crop") {
    if (sourceAspect > outputAspect) {
      sw = (sh * outputAspect) / sar;
      sx += (crop.w - sw) / 2;
    } else {
      sh = (sw * sar) / outputAspect;
      sy += (crop.h - sh) / 2;
    }
  } else if (sourceAspect > outputAspect) {
    dh = (width * (32 / 35)) / sourceAspect;
    dy = (height - dh) / 2;
  } else {
    dw = (height * sourceAspect) / (32 / 35);
    dx = (width - dw) / 2;
  }
  return { sx, sy, sw, sh, dx, dy, dw, dh };
}
