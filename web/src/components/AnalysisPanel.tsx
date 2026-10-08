import { useEffect, useState } from 'react';
import { ApiError, api } from '../api/client';
import type { Features, RecordingDetail, Spectrogram as SpecData } from '../api/types';
import { Spectrogram } from './Spectrogram';
import { Waveform } from './Waveform';

interface Props {
  recordingId: string | null;
  version?: number; // bump to re-fetch (e.g. after inference or annotation)
}

function Stat({ label, value, unit, digits = 1 }: { label: string; value: number; unit?: string; digits?: number }) {
  return (
    <div className="stat">
      <div className="label">{label}</div>
      <div className="value">{Number.isFinite(value) ? value.toFixed(digits) : '—'}{unit && <span className="unit">{unit}</span>}</div>
    </div>
  );
}

export function AnalysisPanel({ recordingId, version = 0 }: Props) {
  const [detail, setDetail] = useState<RecordingDetail | null>(null);
  const [features, setFeatures] = useState<Features | null>(null);
  const [spec, setSpec] = useState<SpecData | null>(null);
  const [kind, setKind] = useState<'mel' | 'stft'>('mel');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setFeatures(null);
    setSpec(null);
    setError(null);
    if (!recordingId) {
      setDetail(null);
      return;
    }
    setLoading(true);
    (async () => {
      try {
        const d = await api.get(recordingId);
        if (cancelled) return;
        setDetail(d);
        if (d.status === 'ready') {
          const [f, s] = await Promise.all([api.features(recordingId), api.spectrogram(recordingId, kind)]);
          if (cancelled) return;
          setFeatures(f);
          setSpec(s);
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [recordingId, kind, version]);

  return (
    <section className="panel" aria-labelledby="an-h">
      <h2 id="an-h">Analysis</h2>
      {!recordingId && <p className="empty">Select a preserved signal from the archive, or record one.</p>}
      {error && <div className="error" role="alert"><span>{error}</span></div>}
      {detail && (
        <>
          <dl className="kv">
            <dt>recording</dt><dd><code>{detail.id}</code></dd>
            <dt>captured</dt><dd>{new Date(detail.captured_at ?? detail.created_at).toLocaleString()}</dd>
            <dt>status</dt><dd><span className={`chip ${detail.status}`}>{detail.status}</span>{detail.error && <span className="flags"> {detail.error.message}</span>}</dd>
            <dt>source</dt><dd>{detail.assets.filter((a) => a.kind === 'source').map((a) => `${a.container ?? '?'} / ${a.codec ?? '?'} · ${a.sample_rate} Hz · ${a.channels} ch · ${(a.bytes / 1024).toFixed(0)} KiB`)}</dd>
            <dt>canonical</dt><dd>{detail.assets.filter((a) => a.kind === 'canonical').map((a) => `${a.sample_rate} Hz mono float32 WAV`)}</dd>
            <dt>quality</dt><dd>{detail.quality.flags.length ? <span className="flags">{detail.quality.flags.join(', ')}</span> : 'no flags'} · peak {detail.quality.peak_dbfs.toFixed(1)} dBFS · clipped {(detail.quality.clipping_ratio * 100).toFixed(2)}%</dd>
            <dt>inference</dt><dd>{detail.inference.status === 'not_run' ? 'not run — see the Hearing panel' : `${detail.inference.status} · ${detail.inference.model_id ?? ''} · embedding ${detail.inference.embedding?.dim ?? '—'}-d`}</dd>
          </dl>
          {loading && <p className="caption" style={{ marginTop: 10 }}>loading measurements…</p>}
          {detail.status !== 'ready' && !loading && <p className="caption" style={{ marginTop: 10 }}>Measurements appear when processing reaches <em>ready</em>.</p>}
        </>
      )}
      {features && (
        <>
          <div className="stats">
            <Stat label="Duration" value={features.summary.duration_s} unit="s" digits={2} />
            <Stat label="RMS" value={features.summary.rms_dbfs} unit="dBFS" />
            <Stat label="Peak" value={features.summary.peak_dbfs} unit="dBFS" />
            <Stat label="Centroid (median)" value={features.summary.spectral_centroid_hz.median} unit="Hz" digits={0} />
            <Stat label="Bandwidth (median)" value={features.summary.spectral_bandwidth_hz.median} unit="Hz" digits={0} />
            <Stat label="Rolloff 85% (median)" value={features.summary.spectral_rolloff_hz.median} unit="Hz" digits={0} />
            <Stat label="Flatness (median)" value={features.summary.spectral_flatness.median} digits={3} />
            <Stat label="Zero crossings" value={features.summary.zero_crossings_per_s} unit="/s" digits={0} />
            <Stat label="Onsets" value={features.summary.onset_count} digits={0} />
            <Stat label="Onset density" value={features.summary.onset_density_per_s} unit="/s" digits={2} />
            <Stat label="Clipping" value={features.summary.clipping_ratio * 100} unit="%" digits={2} />
            <Stat label="Dominant mel band" value={features.summary.log_mel.dominant_band_hz} unit="Hz" digits={0} />
          </div>
          <div className="viz-title"><span>Waveform · {features.waveform.buckets} buckets · onsets marked</span><span className="right">dsp v{features.dsp_version}</span></div>
          <Waveform wave={features.waveform} onsets={features.onset_times_s} />
          <div className="viz-title">
            <span>{kind === 'mel' ? `Log-mel spectrogram · ${features.summary.log_mel.n_mels} bands · 25 ms / 10 ms` : 'STFT spectrogram · 2048-pt · hop 512 · 256 pooled bins'}</span>
            <span className="tabs" role="tablist">
              <button role="tab" aria-selected={kind === 'mel'} className={kind === 'mel' ? 'active' : ''} onClick={() => setKind('mel')}>mel</button>
              <button role="tab" aria-selected={kind === 'stft'} className={kind === 'stft' ? 'active' : ''} onClick={() => setKind('stft')}>stft</button>
            </span>
          </div>
          {spec && <Spectrogram data={spec} />}
          <p className="caption" style={{ marginTop: 8 }}>
            {spec && <>{spec.n_bins} × {spec.n_frames} frames (each averaging {spec.frames_pooled}) · {spec.min_db.toFixed(0)}…{spec.max_db.toFixed(0)} dB · </>}
            artifact <code>{features.artifact_sha256.slice(0, 12)}</code>
          </p>
        </>
      )}
    </section>
  );
}
