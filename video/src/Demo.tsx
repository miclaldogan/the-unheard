import React from 'react';
import {AbsoluteFill, Audio, Img, Sequence, interpolate, staticFile, useCurrentFrame} from 'remotion';
import {C, s} from './theme';
import {Caption, F, Shot, Stat, Tag, Vignette, fade} from './ui';

const Scene: React.FC<{from: number; to: number; children: React.ReactNode}> = ({from, to, children}) => {
  const f = useCurrentFrame();
  const a = fade(f, from, to - from, 10, 10);
  return (
    <Sequence from={from} durationInFrames={to - from}>
      <AbsoluteFill style={{opacity: f < 10 && from === 0 ? 1 : a}}>{children}</AbsoluteFill>
    </Sequence>
  );
};

const TopShade: React.FC = () => (
  <AbsoluteFill style={{background: 'linear-gradient(180deg, rgba(8,10,9,.92) 0%, rgba(8,10,9,.55) 30%, rgba(8,10,9,0) 55%)'}} />
);

const Chamber: React.FC = () => (
  <>
    <AbsoluteFill style={{filter: 'blur(7px)'}}>
      <Shot
        src="shots/01-chamber-desktop.jpg"
        imgW={2400}
        showW={1900}
        from={{cx: 1200, cy: 760, z: 1.0}}
        to={{cx: 1200, cy: 700, z: 1.18}}
        dur={s(6)}
      />
    </AbsoluteFill>
    <AbsoluteFill style={{background: 'rgba(8,10,9,.55)'}} />
    <div style={{position: 'absolute', top: 120, left: 0, right: 0, textAlign: 'center'}}>
      <Tag>Hacktoberfest 2026 · Touch Grass</Tag>
      <div style={{fontFamily: F.serif, fontSize: 190, letterSpacing: 10, color: C.ink, marginTop: 14}}>THE UNHEARD</div>
      <div style={{fontFamily: F.sans, fontWeight: 500, fontSize: 34, color: C.dim, letterSpacing: 6}}>
        AN ACOUSTIC MEMORY EXPERIMENT
      </div>
    </div>
  </>
);

const Field: React.FC = () => {
  const f = useCurrentFrame();
  const y = interpolate(f, [0, s(6.4)], [0, -120]);
  return (
    <AbsoluteFill style={{background: C.bg}}>
      <div style={{position: 'absolute', left: 250, top: 70, width: 470, height: 940, borderRadius: 54, border: '10px solid #1d2623', overflow: 'hidden', boxShadow: '0 40px 120px rgba(0,0,0,.7)', background: '#0b0e0d'}}>
        <Img src={staticFile('shots/04-field-mobile.jpg')} style={{width: 450, transform: `translateY(${y}px)`}} />
      </div>
      <div style={{position: 'absolute', left: 860, top: 250, width: 900}}>
        <Tag>01 · Field</Tag>
        <div style={{fontFamily: F.serif, fontSize: 112, lineHeight: 1.02, color: C.ink, marginTop: 16}}>
          The screen is the shortest part.
        </div>
        <div style={{fontFamily: F.sans, fontWeight: 500, fontSize: 34, color: C.dim, marginTop: 34, lineHeight: 1.45}}>
          Capture is saved in the browser first, even offline. Upload is your choice.
        </div>
        <div style={{fontFamily: F.sans, fontWeight: 500, fontSize: 26, color: C.amber, marginTop: 44, lineHeight: 1.4, borderLeft: `4px solid ${C.amber}`, paddingLeft: 20}}>
          Honest note: the sounds in this video were generated with the ElevenLabs sound-effects API. They are not field recordings.
        </div>
      </div>
    </AbsoluteFill>
  );
};

const Hearing: React.FC = () => {
  const f = useCurrentFrame();
  return (
    <>
      <Shot
        src="shots/05-hearing-desktop.jpg"
        imgW={2400}
        showW={1900}
        from={{cx: 1180, cy: 1330, z: 1.0}}
        to={{cx: 1120, cy: 1460, z: 1.25}}
        dur={s(11.2)}
      />
      <TopShade />
      <div style={{position: 'absolute', left: 90, top: 90}}>
        <Tag>02 · Hearing</Tag>
      </div>
      <div style={{opacity: fade(f, s(1.4), s(10), 14, 10), position: 'absolute', left: 90, top: 240}}>
        <Stat label="Ears · CLAP, local" value="0.367" sub="“Church bells” — a similarity, not a probability" color={C.amber} />
      </div>
      <div style={{opacity: fade(f, s(6.6), s(4.6), 14, 10), position: 'absolute', left: 90, top: 560}}>
        <Stat label="Memory · yours" value="0.844" sub="“Bells” — 2 examples you taught" color={C.teal} />
      </div>
    </>
  );
};

const Shapes: React.FC = () => {
  const f = useCurrentFrame();
  const two = f > s(3.3);
  return (
    <>
      <div style={{opacity: two ? interpolate(f, [s(3.3), s(3.8)], [1, 0], {extrapolateRight: 'clamp'}) : 1, position: 'absolute', inset: 0}}>
        <Shot src="shots/07-specimen-desktop.jpg" imgW={2400} showW={1800} from={{cx: 1200, cy: 1000, z: 1.0}} to={{cx: 1200, cy: 1060, z: 1.12}} dur={s(4)} />
      </div>
      {two && (
        <div style={{opacity: interpolate(f, [s(3.3), s(3.8)], [0, 1], {extrapolateRight: 'clamp'}), position: 'absolute', inset: 0}}>
          <Shot src="shots/09-atlas-desktop.jpg" imgW={2400} showW={1800} from={{cx: 1250, cy: 1950, z: 1.0}} to={{cx: 1250, cy: 1950, z: 1.2}} dur={s(4.4)} />
        </div>
      )}
      <TopShade />
      <div style={{position: 'absolute', left: 90, top: 90}}>
        <Tag>{two ? '04 · Atlas' : '03 · Specimen'}</Tag>
        <div style={{fontFamily: F.serif, fontSize: 84, color: C.ink, marginTop: 8, textShadow: '0 4px 30px #000'}}>
          {two ? 'Distance = how alike they sound.' : 'Same sound, same shape.'}
        </div>
      </div>
    </>
  );
};

const Orchestra: React.FC = () => {
  const f = useCurrentFrame();
  return (
    <>
      <Shot src="shots/11-orchestra-desktop.jpg" imgW={2400} showW={1900} from={{cx: 1500, cy: 1700, z: 1.0}} to={{cx: 1500, cy: 1840, z: 1.22}} dur={s(9.5)} />
      <TopShade />
      <div style={{position: 'absolute', left: 90, top: 80, opacity: fade(f, s(0.3), s(9), 10, 12)}}>
        <Tag>05 · Orchestra</Tag>
        <div style={{fontFamily: F.serif, fontSize: 84, color: C.ink, marginTop: 8, textShadow: '0 4px 30px #000'}}>
          Composed from 3 recordings.
        </div>
        <div style={{fontFamily: F.sans, fontWeight: 500, fontSize: 30, color: C.ink, marginTop: 10, textShadow: '0 2px 20px #000'}}>
          47 events · every bar traces back to a source · no music model
        </div>
      </div>
    </>
  );
};

const End: React.FC = () => {
  const f = useCurrentFrame();
  const a = interpolate(f, [0, 20], [0, 1], {extrapolateRight: 'clamp'});
  return (
    <AbsoluteFill style={{background: C.bg, opacity: a}}>
      <div style={{position: 'absolute', top: 90, left: 0, right: 0, textAlign: 'center'}}>
        <div style={{fontFamily: F.serif, fontSize: 150, letterSpacing: 8, color: C.ink}}>THE UNHEARD</div>
        <div style={{display: 'flex', justifyContent: 'center', gap: 70, marginTop: 36}}>
          {[
            ['CLAP', 'hears', C.amber],
            ['Memory', 'remembers', C.teal],
            ['Gemma', 'speaks', C.green],
          ].map(([a1, b1, col]) => (
            <div key={a1} style={{fontFamily: F.serif, fontSize: 62, color: C.ink}}>
              <span style={{color: col as string}}>{a1}</span> {b1}
            </div>
          ))}
        </div>
        <div style={{fontFamily: F.sans, fontWeight: 500, fontSize: 32, color: C.dim, marginTop: 34}}>
          Local-first · MIT · retrieval memory, nothing fine-tuned · Gemma 3 4B via Ollama
        </div>
        <div style={{fontFamily: F.sans, fontWeight: 500, fontSize: 24, letterSpacing: 6, color: C.dim, marginTop: 52, textTransform: 'uppercase'}}>
          Built by
        </div>
        <div style={{fontFamily: F.serif, fontSize: 84, color: C.amber, marginTop: 6}}>
          İclal Doğan · Melike Zaman
        </div>
        <div style={{fontFamily: F.sans, fontWeight: 500, fontSize: 28, color: C.dim, marginTop: 14}}>
          Open source on GitHub · link in the post
        </div>
      </div>
      <div style={{position: 'absolute', bottom: 190, left: 0, right: 0, textAlign: 'center', fontFamily: F.sans, fontWeight: 500, fontSize: 24, color: C.dim, lineHeight: 1.5}}>
        Demo sounds: ElevenLabs sound-effects API (AI-generated, not field recordings) · Narration: ElevenLabs voice · Audio model: LAION-CLAP · #hf26challenge
      </div>
    </AbsoluteFill>
  );
};

export const Demo: React.FC = () => (
  <AbsoluteFill style={{background: C.bg}}>
    <Audio src={staticFile('audio/mix.wav')} />
    <Scene from={0} to={s(6.0)}><Chamber /></Scene>
    <Scene from={s(5.8)} to={s(12.4)}><Field /></Scene>
    <Scene from={s(12.2)} to={s(23.4)}><Hearing /></Scene>
    <Scene from={s(23.2)} to={s(31.3)}><Shapes /></Scene>
    <Scene from={s(31.1)} to={s(40.8)}><Orchestra /></Scene>
    <Sequence from={s(40.6)}><End /></Sequence>
    <Vignette />
    <Caption />
  </AbsoluteFill>
);
