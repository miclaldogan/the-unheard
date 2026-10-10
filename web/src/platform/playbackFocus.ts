/** All media shares one audible focus; compatible scene navigation does not change it. */
const stops = new Set<() => void>();
export function registerPlayback(stop: () => void): () => void {
  stops.add(stop);
  return () => {
    stops.delete(stop);
  };
}
export function claimPlayback(except?: () => void): void {
  stops.forEach((stop) => {
    if (stop !== except) stop();
  });
  document
    .querySelectorAll<HTMLMediaElement>("audio,video")
    .forEach((el) => el.pause());
}
export function installMediaFocus(): () => void {
  const listener = (e: Event) => {
    const target = e.target;
    if (!(target instanceof HTMLMediaElement)) return;
    stops.forEach((stop) => stop());
    document.querySelectorAll<HTMLMediaElement>("audio,video").forEach((el) => {
      if (el !== target) el.pause();
    });
  };
  document.addEventListener("play", listener, true);
  return () => document.removeEventListener("play", listener, true);
}
