import { useAudioSource } from '../platform/useAudioSource';
import { useEffect, useMemo, useRef, useState } from 'react';
import { ApiError, api } from '../api/client';
import type { Features, Neighbour, Prediction, RecordingDetail, Visual } from '../api/types';
import { buildGeometry, signatureSVG } from '../visual/signature';
import { SignatureCanvas } from './SignatureCanvas';
import { Spectrogram } from './Spectrogram';
import { Waveform } from './Waveform';
import type { Spectrogram as SpecData } from '../api/types';

interface Props {
  recordingId: string;
  onTeach: () => void;
  onOpenAtlas: () => void;
  onSelect: (id: string) => void;
}

const STATE_TEXT: Record<Visual['params']['semantic']['state'], string> = {
  unknown: 'unresolved — no name yet',
  uncertain: 'uncertain hypothesis',
  hypothesis: 'hypothesis (not confirmed)',
  confirmed: 'confirmed by you',
};

export function Specimen({ recordingId, onTeach, onOpenAtlas, onSelect }: Props) {
  const audioSource = useAudioSource(api.audioUrl(recordingId));
  const [visual, setVisual] = useState<Visual | null>(null);
  const [detail, setDetail] = useState<RecordingDetail | null>(null);
  const [prediction, setPrediction] = useState<Prediction | null>(null);
  const [neighbours, setNeighbours] = useState<Neighbour[]>([]);
  const [features, setFeatures] = useState<Features | null>(null);
  const [spec, setSpec] = useState<SpecData | null>(null);
  const [showMeasurements, setShowMeasurements] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const [audioEl, setAudioEl] = useState<HTMLAudioElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    setVisual(null); setDetail(null); setPrediction(null); setNeighbours([]); setFeatures(null); setSpec(null); setError(null);
    (async () => {
      try {
        const [v, d, p, n] = await Promise.all([api.visual(recordingId), api.get(recordingId), api.prediction(recordingId).catch(() => null), api.neighbours(recordingId).catch(() => [] as Neighbour[])]);
        if (cancelled) return;
        setVisual(v); setDetail(d); setPrediction(p); setNeighbours(n);
      } catch (e) {
        if (!cancelled) setError(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e));
      }
    })();
    return () => { cancelled = true; };
  }, [recordingId]);

  useEffect(() => {
    if (!showMeasurements || features) return;
    Promise.all([api.features(recordingId), api.spectrogram(recordingId, 'mel', 400)]).then(([f, s]) => { setFeatures(f); setSpec(s); }).catch(() => undefined);
  }, [showMeasurements, features, recordingId]);

  useEffect(() => { setAudioEl(audioRef.current); }, [visual]);

  const svg = useMemo(() => (visual ? signatureSVG(visual.params, buildGeometry(visual.params)) : ''), [visual]);
  const svgHref = useMemo(() => (svg ? `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}` : ''), [svg]);

  const exportPng = () => {
    const c = document.querySelector<HTMLCanvasElement>('canvas.signature.large');
    if (!c) return;
    const a = document.createElement('a');
    a.href = c.toDataURL('image/png');
    a.download = `specimen-${recordingId.slice(0, 8)}.png`;
    a.click();
  };

  if (error) return <section className="panel"><div className="error" role="alert"><span>{error}</span></div></section>;
  if (!visual || !detail) return <section className="panel"><p className="caption">reconstructing the specimen…</p></section>;
  const s = visual.params.semantic;
  const g = visual.params.geometry;
  const fused = prediction?.fused?.candidates.slice(0, 3) ?? [];
  return (
    <section className="specimen" aria-labelledby="sp-h">
      <header className="specimen-head">
        <div>
          <div className="eyebrow">Specimen <code>{recordingId.slice(0, 8)}</code> · generator v{visual.generator_version} · seed {visual.seed}</div>
          <h2 id="sp-h">{s.label ?? 'Unnamed sound'} <span className={`chip state-${s.state}`}>{STATE_TEXT[s.state]}</span></h2>
          <div className="caption">{new Date(detail.captured_at ?? detail.created_at).toLocaleString()} · {detail.duration_s.toFixed(1)} s · {s.confirmed_labels.length ? `you said: ${s.confirmed_labels.join(', ')}` : fused.length ? `ears: ${fused.map((c) => c.name).join(' · ')}` : 'not heard yet'}</div>
        </div>
        <div className="row">
          <button className="btn small" onClick={onTeach}>Teach / hear</button>
          <button className="btn small" onClick={onOpenAtlas}>Atlas</button>
        </div>
      </header>

      <div className="specimen-grid">
        <div className="specimen-art">
          <SignatureCanvas params={visual.params} audio={audioEl} className="signature large" ariaLabel={`acoustic signature of ${s.label ?? 'an unnamed sound'}; outline from the RMS envelope, ${g.symmetry_order}-fold symmetry, ${g.ticks.length} onset ticks`} />
          {audioSource.error && <p role="alert" className="caption">{audioSource.error}</p>}
          <audio ref={audioRef} controls src={audioSource.src} aria-label="original recording" style={{ width: '100%', marginTop: 8 }} />
          <div className="row" style={{ marginTop: 8 }}>
            <button className="btn small" onClick={exportPng}>Export PNG</button>
            <a className="btn small" href={svgHref} download={`specimen-${recordingId.slice(0, 8)}.svg`}>Export SVG</a>
            <span className="caption">geometry {visual.geometry_hash.slice(0, 12)} · dsp v{visual.dsp_version}{visual.model_version_id ? ' · embedded' : ' · no embedding'}</span>
          </div>
        </div>
        <div className="specimen-meta">
          <dl className="kv">
            <dt>outline</dt><dd>RMS envelope, {g.symmetry_order}-fold symmetry (tonality {(1 - g.jitter).toFixed(2)})</dd>
            <dt>crispness</dt><dd>{g.sharpness.toFixed(2)} from centroid</dd>
            <dt>fragmentation</dt><dd>{g.fragmentation.toFixed(2)} from spectral flux</dd>
            <dt>ticks</dt><dd>{g.ticks.length} onsets ({g.onset_density_per_s.toFixed(2)}/s)</dd>
            <dt>weight</dt><dd>energy {g.energy.toFixed(2)}</dd>
            <dt>hue</dt><dd>{s.hue ?? '—'} from {s.state === 'confirmed' ? 'your label' : 'the top hypothesis'} (the only label-driven property)</dd>
          </dl>
          {s.why && (s.state === 'unknown' || s.state === 'uncertain') && (
            <p className="novel">Why unresolved: {s.why.novel ? 'nothing in memory resembles it' : 'the ears are undecided'}{s.why.nearest_exemplar_similarity !== null ? ` · nearest memory cos ${s.why.nearest_exemplar_similarity?.toFixed(2)}` : ' · memory empty'} · margin {s.why.fused_margin?.toFixed(2)} · entropy {s.why.base_entropy_normalised?.toFixed(2)}{s.why.disagreement ? ' · ears and memory disagree' : ''}</p>
          )}
          {(s.descriptors.length > 0 || s.environment || s.mood) && (
            <p className="caption">Your notes: {s.descriptors.join(', ')}{s.environment ? ` · at ${s.environment}` : ''}{s.mood ? ` · feels ${s.mood} (your interpretation)` : ''}</p>
          )}
          {prediction?.model && <p className="caption">Ears: {prediction.model.id} · {prediction.model.revision.slice(0, 8)}{prediction.fused ? ` · memory v${prediction.fused.memory_version}` : ''}</p>}
          {neighbours.length > 0 && (
            <>
              <div className="field-label" style={{ marginTop: 10 }}>Similar memories</div>
              <ul className="memlist">
                {neighbours.slice(0, 5).map((n) => (
                  <li key={n.recording_id}><button className="linkish" onClick={() => onSelect(n.recording_id)}>{n.recording_id.slice(0, 8)}</button><span className="caption"> · cos {n.similarity.toFixed(2)} · {n.is_unknown ? 'unknown' : n.labels.join(', ') || 'unlabelled'}</span></li>
                ))}
              </ul>
            </>
          )}
          <button className="btn small" style={{ marginTop: 10 }} onClick={() => setShowMeasurements((v) => !v)}>{showMeasurements ? 'Hide' : 'Show'} measurements</button>
          {showMeasurements && features && (
            <div style={{ marginTop: 8 }}>
              <Waveform wave={features.waveform} onsets={features.onset_times_s} />
              {spec && <div style={{ marginTop: 8 }}><Spectrogram data={spec} /></div>}
              <p className="caption">RMS {features.summary.rms_dbfs.toFixed(1)} dBFS · centroid {features.summary.spectral_centroid_hz.median.toFixed(0)} Hz · flatness {features.summary.spectral_flatness.median.toFixed(3)} · onsets {features.summary.onset_count}</p>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
