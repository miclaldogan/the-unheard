export const FPS = 30;
export const W = 1920;
export const H = 1080;
export const TOTAL = 50 * FPS;
export const s = (sec: number) => Math.round(sec * FPS);

// palette taken from the app's own UI
export const C = {
  bg: '#0b0e0d',
  panel: '#131a18',
  ink: '#ece7de',
  dim: '#9aa39e',
  amber: '#d59a5e',
  teal: '#6fc9b8',
  green: '#a5c24a',
  blue: '#6d8fe0',
};

// narration lines: start second, text. Start times match audio/mix.py exactly.
export const LINES: {t: number; d: number; text: string}[] = [
  {t: 0.6, d: 4.55, text: 'This machine knows the name of every sound. It has never heard one.'},
  {t: 6.0, d: 5.71, text: 'The game sends you outside, to record what is really there, and bring it back.'},
  {t: 12.4, d: 5.76, text: 'It guesses in similarity, never certainty. You tell it what you actually heard.'},
  {t: 18.9, d: 3.85, text: "And it remembers. Your word comes first, not the model's."},
  {t: 23.4, d: 3.11, text: 'Every sound becomes a shape. The shapes find each other.'},
  {t: 27.1, d: 4.18, text: 'Then it composes, using only what you brought back.'},
  {t: 40.8, d: 7.57, text: 'Gemma narrates, and every line is checked against the facts. Go outside. Listen closely.'},
];
