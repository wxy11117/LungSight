export const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

export function fitImage(width: number, height: number, viewportWidth: number, viewportHeight: number) {
  const ratio = Math.min(viewportWidth / Math.max(width, 1), viewportHeight / Math.max(height, 1));
  return { width: width * ratio, height: height * ratio };
}

export function imagePoint(clientX: number, clientY: number, bounds: { left: number; top: number; width: number; height: number }) {
  if (!bounds.width || !bounds.height) return null;
  const x = (clientX - bounds.left) / bounds.width;
  const y = (clientY - bounds.top) / bounds.height;
  return x < 0 || x > 1 || y < 0 || y > 1 ? null : { x, y };
}

export function boundedPan(x: number, y: number, width: number, height: number, zoom: number) {
  return { x: clamp(x, -width * (zoom - 1) / 2, width * (zoom - 1) / 2), y: clamp(y, -height * (zoom - 1) / 2, height * (zoom - 1) / 2) };
}
