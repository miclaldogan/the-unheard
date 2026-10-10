import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "./api/client";
import type {
  Health,
  MemoryOverview,
  Neighbour,
  RecordingSummary,
} from "./api/types";
import { AnalysisPanel } from "./components/AnalysisPanel";
import { Archive } from "./components/Archive";
import { Atlas } from "./components/Atlas";
import { Orchestra } from "./components/Orchestra";
import { HearingPanel } from "./components/HearingPanel";
import { Specimen } from "./components/Specimen";
import { MemoryPanel } from "./components/MemoryPanel";
import { RecordingPanel } from "./components/RecordingPanel";
import { useNarrative } from "./state/useNarrative";
import { NarrativeVoice } from "./components/NarrativeVoice";
import { FieldMission } from "./components/FieldMission";
import { Chamber } from "./components/Chamber";
import { FieldCollection } from "./components/FieldCollection";
import { installMediaFocus, claimPlayback } from "./platform/playbackFocus";

import { retryPending } from "./platform/uploadQueue";

const DEFAULT_LIMITS = { min_duration_s: 3, max_duration_s: 30 };

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [items, setItems] = useState<RecordingSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [memory, setMemory] = useState<MemoryOverview | null>(null);
  const [neighbours, setNeighbours] = useState<Neighbour[]>([]);
  const [version, setVersion] = useState(0);
  const [view, setView] = useState<
    "chamber" | "field" | "hearing" | "specimen" | "atlas" | "orchestra"
  >("chamber");
  const [orchestraIds, setOrchestraIds] = useState<string[]>([]);
  const [orchestraOpened, setOrchestraOpened] = useState(false);
  const activityRef = useRef<Record<string, number>>({});
  const toggleOrchestra = useCallback(
    (id: string) =>
      setOrchestraIds((cur) =>
        cur.includes(id)
          ? cur.filter((x) => x !== id)
          : cur.length >= 8
            ? cur
            : [...cur, id],
      ),
    [],
  );

  const refresh = useCallback(async () => {
    try {
      const [l, h, mem] = await Promise.all([
        api.list(),
        api.health(),
        api.memory().catch(() => null),
      ]);
      setItems(l.items);
      setHealth(h);
      setMemory(mem);
      setHealthError(null);
    } catch (e) {
      setHealth(null);
      setHealthError(
        e instanceof ApiError ? `${e.code}: ${e.message}` : String(e),
      );
    }
  }, []);
  const onMemoryChanged = useCallback(() => {
    setVersion((v) => v + 1);
    void refresh();
  }, [refresh]);
  const onNeighbours = useCallback((n: Neighbour[]) => {
    setNeighbours(n);
    setVersion((v) => v + 1);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // keep the archive fresh while anything is still processing
  useEffect(() => {
    if (
      !items.some((r) => r.status === "uploaded" || r.status === "processing")
    )
      return;
    const t = window.setTimeout(() => void refresh(), 1000);
    return () => window.clearTimeout(t);
  }, [items, refresh]);

  const onDeletedOrChanged = useCallback(() => {
    setVersion((v) => v + 1);
    void refresh();
  }, [refresh]);

  useEffect(() => {
    setSelected((current) =>
      current && !items.some((r) => r.id === current) ? null : current,
    );
  }, [items]);

  useEffect(() => installMediaFocus(), []);
  useEffect(() => {
    const retry = () => {
      if (document.visibilityState !== "hidden" && navigator.onLine)
        void retryPending()
          .then(refresh)
          .catch(() => undefined);
    };
    retry();
    window.addEventListener("online", retry);
    const timer = window.setInterval(retry, 30000);
    return () => {
      window.removeEventListener("online", retry);
      window.clearInterval(timer);
    };
  }, [refresh]);
  const limits = health?.limits ?? DEFAULT_LIMITS;
  const narrative = useNarrative(
    `${version}:${memory?.memory_version ?? 0}:${items.map((r) => `${r.id}:${r.status}`).join(",")}`,
  );
  const [captureActive, setCaptureActive] = useState(false);
  const [fieldOpened, setFieldOpened] = useState(false);
  const field = () => {
    if (captureActive) return;
    claimPlayback();
    setFieldOpened(true);
    setView("field");
  };
  const hear = (id?: string) => {
    if (captureActive) return;
    if (id) setSelected(id);
    setView("hearing");
  };
  const compose = () => {
    if (captureActive) return;
    setOrchestraOpened(true);
    setView("orchestra");
  };
  const scene = {
    chamber: ["00", "The Chamber", "Meet the machine. Borrow the world."],
    field: [
      "01",
      "The world outside",
      "Carry the instrument. Leave room for listening.",
    ],
    hearing: [
      "02",
      "The Hearing Room",
      "A hypothesis from the machine. An interpretation from you.",
    ],
    specimen: [
      "03",
      "The Specimen Archive",
      "Every sound leaves a singular trace.",
    ],
    atlas: [
      "04",
      "The Acoustic Atlas",
      "A constellation of sounds, connected by memory.",
    ],
    orchestra: [
      "05",
      "The Impossible Orchestra",
      "What was collected apart can now be heard together.",
    ],
  }[view];

  return (
    <div
      className={`app ${view === "field" ? "mode-field" : "mode-laboratory"}`}
    >
      <a className="skip-link" href="#main-content">
        Skip to experience
      </a>
      <header className="masthead">
        <button
          className="brand"
          disabled={captureActive}
          onClick={() => setView("chamber")}
          aria-label="THE UNHEARD — return to Chamber"
        >
          <span className="brand-emblem" aria-hidden="true">
            ◉
          </span>
          <span>
            THE UNHEARD<small>AN ACOUSTIC MEMORY EXPERIMENT</small>
          </span>
        </button>
        <div className="health" aria-label="server status">
          <span className={health ? "ok" : "bad"}>
            {health
              ? "● Laboratory connected"
              : healthError
                ? "○ Laboratory unreachable"
                : "○ Connecting to laboratory"}
          </span>
          <button className="connection-retry" onClick={() => void refresh()}>
            Check connection
          </button>
        </div>
      </header>
      <nav className="views" aria-label="views">
        {(
          [
            ["chamber", "Chamber"],
            ["field", "Field"],
            ["hearing", "Hearing"],
            ["specimen", "Specimen"],
            ["atlas", "Atlas"],
            ["orchestra", "Orchestra"],
          ] as const
        ).map(([key, label], i) => (
          <button
            key={key}
            aria-label={label}
            className={view === key ? "active" : ""}
            aria-current={view === key ? "page" : undefined}
            disabled={captureActive || (key === "specimen" && !selected)}
            onClick={() =>
              key === "field"
                ? field()
                : key === "orchestra"
                  ? compose()
                  : setView(key)
            }
          >
            <span className="nav-index">0{i}</span>
            {label}
          </button>
        ))}
      </nav>
      {captureActive && (
        <p className="capture-live-banner" role="status">
          Microphone active · stop and save before changing scenes.
        </p>
      )}
      {view === "chamber" && (
        <Chamber
          items={items}
          memory={memory}
          connected={!!health}
          onField={field}
          onHear={hear}
          onAtlas={() => setView("atlas")}
          onCompose={compose}
          snapshot={narrative.snapshot}
          narrativeStatus={narrative.status}
        />
      )}
      {view !== "chamber" && (
        <div className="scene-heading" id="main-content" tabIndex={-1}>
          <span className="scene-number">{scene[0]}</span>
          <div>
            <div className="eyebrow">
              THE UNHEARD /{" "}
              {view === "field" ? "FIELD INSTRUMENT" : "LABORATORY"}
            </div>
            <h1>{scene[1]}</h1>
            <p>{scene[2]}</p>
          </div>
          {view !== "field" && (
            <button
              className="btn small ghost"
              disabled={captureActive}
              onClick={field}
            >
              Go outside ↗
            </button>
          )}
        </div>
      )}
      {healthError && view !== "chamber" && (
        <div className="connection-notice" role="status">
          The laboratory is out of reach. Capture and save locally in Field
          Mode; upload when the connection returns.
          <details>
            <summary>Connection details</summary>
            <code>{healthError}</code>
          </details>
        </div>
      )}
      {view !== "chamber" && view !== "field" && narrative.snapshot && (
        <NarrativeVoice
          compact
          utterance={narrative.snapshot.current.utterance}
        />
      )}
      {fieldOpened && (
        <div className="field-layout" hidden={view !== "field"}>
          <div>
            <RecordingPanel
              field
              onCaptureActive={setCaptureActive}
              limits={limits}
              onProcessed={(id) => {
                setSelected(id);
                void refresh();
              }}
              onArchiveChanged={() => void refresh()}
            />
            {narrative.snapshot && (
              <FieldMission
                missions={narrative.snapshot.missions}
                onChanged={narrative.reload}
              />
            )}
            <p className="field-note">
              A note from the laboratory: find something close enough to hear,
              small enough to overlook.
            </p>
          </div>
          <FieldCollection
            onUploaded={(id) => {
              hear(id);
              void refresh();
            }}
          />
        </div>
      )}
      {view === "atlas" && (
        <Atlas
          version={version + items.length}
          onOpenSpecimen={(id) => {
            setSelected(id);
            setView("specimen");
          }}
          onBack={() => setView("hearing")}
          selection={orchestraIds}
          onToggleSelect={toggleOrchestra}
          onCompose={() => {
            setOrchestraOpened(true);
            setView("orchestra");
          }}
          activityRef={activityRef}
        />
      )}
      {/* stays mounted (hidden) once opened, so the music keeps playing and the atlas can react to it */}
      {(orchestraOpened || view === "orchestra") && (
        <div hidden={view !== "orchestra"}>
          <Orchestra
            items={items}
            preselected={orchestraIds}
            activityRef={activityRef}
            onOpenSpecimen={(id) => {
              setSelected(id);
              setView("specimen");
            }}
            onOpenAtlas={() => setView("atlas")}
          />
        </div>
      )}
      {view === "specimen" && selected && (
        <Specimen
          recordingId={selected}
          onTeach={() => setView("hearing")}
          onOpenAtlas={() => setView("atlas")}
          onSelect={setSelected}
        />
      )}
      <main className="grid hearing-grid" hidden={view !== "hearing"}>
        <div
          style={{
            display: "grid",
            gap: 18,
            minWidth: 0,
            alignContent: "start",
          }}
        >
          <RecordingPanel
            onCaptureActive={setCaptureActive}
            limits={limits}
            onProcessed={(id) => {
              setSelected(id);
              void refresh();
            }}
            onArchiveChanged={() => void refresh()}
          />
          <MemoryPanel
            memory={memory}
            neighbours={neighbours}
            onSelect={setSelected}
          />
        </div>
        <div
          style={{
            display: "grid",
            gap: 18,
            minWidth: 0,
            alignContent: "start",
          }}
        >
          {!selected && (
            <section className="hearing-empty">
              <div className="eyebrow">A conversation begins with a sound</div>
              <h2>First, let me listen.</h2>
              <p>
                Record a discovery, or choose one from your archive. I will
                offer a hypothesis. You can tell me what I missed.
              </p>
              <span className="empty-rule" aria-hidden="true" />
            </section>
          )}
          {selected && (
            <div className="row" style={{ justifyContent: "flex-end" }}>
              <button
                className="btn small teal"
                disabled={captureActive}
                onClick={() => setView("specimen")}
              >
                Open visual memory
              </button>
            </div>
          )}
          <HearingPanel
            recordingId={selected}
            onMemoryChanged={onMemoryChanged}
            onNeighbours={onNeighbours}
          />
          <AnalysisPanel recordingId={selected} version={version} />
          <Archive
            items={items}
            selected={selected}
            onSelect={setSelected}
            onChanged={onDeletedOrChanged}
          />
        </div>
      </main>

      <footer className="footer">
        <span>
          THE UNHEARD <span aria-hidden="true">/</span> LISTEN CLOSELY.
        </span>
        <span>
          Captured on your device. Analyzed by your connected laboratory.{" "}
          <a href="/api/docs">Instrument reference</a>
        </span>
      </footer>
    </div>
  );
}
