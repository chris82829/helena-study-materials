export const DEFAULT_CHAT_WIDTH = 460;
export const CHAT_WIDTH_KEY = 'helena-chat-width-v1';
export function chatWidthBounds(containerWidth) {
  return { min: 360, max: Math.max(360, Math.min(800, containerWidth - 412)) };
}
export function clampChatWidth(width, containerWidth) {
  const bounds = chatWidthBounds(containerWidth);
  return Math.round(Math.min(bounds.max, Math.max(bounds.min, Number.isFinite(width) ? width : DEFAULT_CHAT_WIDTH)));
}
export function onboardingChatWidth(containerWidth) {
  return clampChatWidth(containerWidth * 0.6, containerWidth);
}
export function keyboardChatWidth(key, width, containerWidth, shift = false) {
  const bounds = chatWidthBounds(containerWidth);
  const step = shift ? 50 : 20;
  if (key === 'Home') return bounds.min;
  if (key === 'End') return bounds.max;
  if (key === 'ArrowLeft') return clampChatWidth(width + step, containerWidth);
  if (key === 'ArrowRight') return clampChatWidth(width - step, containerWidth);
  return null;
}
export function messagePreview(text, limit = 620) {
  if (text.length <= 700) return text;
  const fragment = text.slice(0, limit);
  const space = fragment.lastIndexOf(' ');
  return fragment.slice(0, space > limit / 2 ? space : limit).trimEnd() + ' …';
}
