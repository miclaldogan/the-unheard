# Submission video (50 s)

Remotion composition `Demo`, 1920x1080, 30 fps. Frames are real screenshots of the running app
(`web/scripts/m7-shots.cjs` against a backend seeded by `scripts/m7_synthetic_journey.py` with the ElevenLabs set).

**Provenance, stated in the video itself:** the demo sounds were generated with the ElevenLabs sound-effects API
(`scripts/m8_elevenlabs_sounds.py`), the narration is an ElevenLabs text-to-speech voice, and the music is the
app's own Composed render of those sounds. None of it is a field recording.

```bash
npm install            # or symlink node_modules from an existing Remotion project
npx remotion studio
npx remotion render src/index.ts Demo out/the-unheard-demo.mp4 --codec h264 --crf 18
```

`public/audio/mix.wav` (narration + composition, -16 LUFS) is not committed; rebuild it from the narration lines in
`src/theme.ts` and the exported composition.
