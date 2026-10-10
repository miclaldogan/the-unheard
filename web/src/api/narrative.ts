import { ApiError, request } from "./client";
/** Wire types from backend commit 923b4aa / docs/contracts/M5-NARRATIVE-API.md. */
export type NarrativePresence =
  | "dormant"
  | "listening"
  | "uncertain"
  | "learning"
  | "remembering"
  | "composing";
export type ActId = "prologue" | "act_1" | "act_2" | "act_3" | "ending";
export type Provenance =
  | "model"
  | "user_confirmed"
  | "personal_memory"
  | "measurement"
  | "system"
  | "imagination";
export interface NarrativeRef {
  type:
    | "recording"
    | "annotation"
    | "label"
    | "prediction"
    | "composition"
    | "atlas_edge"
    | "mission"
    | "measurement";
  id: string;
  label: string | null;
  provenance: Provenance;
}
export interface Fact {
  handle: string;
  statement: string;
  provenance: Provenance;
  ref: NarrativeRef | null;
}
export interface NarrativeLine {
  text: string;
  kind: "grounded" | "imagination";
  provenance: Provenance[];
  cites: string[];
}
export interface Utterance {
  id: string;
  revision: number;
  moment: {
    kind:
      | "awaiting_sound"
      | "first_sound"
      | "teaching"
      | "correction"
      | "unknown"
      | "relationship"
      | "ready_to_compose"
      | "composition"
      | "ending";
    key: string;
    act: ActId;
    occurred_at: string | null;
  };
  lines: NarrativeLine[];
  facts: Fact[];
  source: "gemma" | "template";
  model: string | null;
  generation: {
    status: "ready" | "pending" | "fallback";
    latency_ms: number | null;
    attempts: number;
    fallback_reason: string | null;
  };
  created_at: string;
}
export interface NarrativeState {
  contract_version: "m5.1";
  derived_at: string;
  act: ActId;
  phase:
    | "awaiting_sound"
    | "first_hearing"
    | "teaching"
    | "ready_to_compose"
    | "composing"
    | "remembered";
  ending_unlocked: boolean;
  acts: {
    id: ActId;
    title: string;
    status: "locked" | "active" | "complete";
    progress: { current: number; target: number };
    criteria: {
      id: string;
      text: string;
      met: boolean;
      evidence: NarrativeRef[];
    }[];
  }[];
  milestones: {
    id: string;
    title: string;
    achieved: boolean;
    achieved_at: string | null;
    optional: boolean;
    evidence: NarrativeRef[];
  }[];
  counts: {
    recordings: number;
    heard: number;
    taught: number;
    labels_confirmed: number;
    corrections: number;
    unknown: number;
    compositions: number;
    memory_version: number;
  };
  gemma: { status: string; model: string | null; enabled: boolean };
}
export interface Mission {
  id: string;
  type:
    | "record_first"
    | "gather_three"
    | "resolve_unknown"
    | "second_example"
    | "novel_sound"
    | "repeat_not_machine"
    | "find_tonal";
  title: string;
  objective: string;
  reason: string;
  evidence: NarrativeRef[];
  completion: { predicate: string; description: string };
  safe_fallback: string;
  safety: string;
  status: "available" | "active" | "completed" | "expired";
  wording: { text: string; source: "gemma" | "template" };
  activated_at: string | null;
  completed_at: string | null;
  progress: { current: number; target: number } | null;
}
export interface NarrativeCurrent {
  contract_version: "m5.1";
  utterance: Utterance;
  available_actions: (
    "record" | "teach" | "compose" | "open_atlas" | "open_orchestra"
  )[];
}
export interface Missions {
  contract_version: "m5.1";
  max_active: number;
  active: Mission[];
  candidates: Mission[];
  completed: Mission[];
  selection: {
    source: "gemma" | "template";
    model: string | null;
    fallback_reason: string | null;
  };
}
export interface NarrativeSnapshot {
  state: NarrativeState;
  current: NarrativeCurrent;
  missions: Missions;
}
export interface NarrativeAdapter {
  read(signal: AbortSignal): Promise<NarrativeSnapshot | null>;
  activate(id: string, signal: AbortSignal): Promise<Mission>;
}
function version<T extends { contract_version: string }>(data: T): T {
  if (data?.contract_version !== "m5.1")
    throw new Error(
      "The narrative contract has changed. Update the instrument to reconnect.",
    );
  return data;
}
export const narrativeApi: NarrativeAdapter = {
  read: async (signal) => {
    try {
      const [state, current, missions] = await Promise.all([
        request<NarrativeState>("/api/narrative/state", { signal }),
        request<NarrativeCurrent>("/api/narrative/current", { signal }),
        request<Missions>("/api/narrative/missions", { signal }),
      ]);
      return {
        state: version(state),
        current: version(current),
        missions: version(missions),
      };
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) return null;
      throw e;
    }
  },
  activate: (id, signal) =>
    request<Mission>(
      `/api/narrative/missions/${encodeURIComponent(id)}/activate`,
      { method: "POST", signal },
    ),
};
export function narrativePresence(
  state: NarrativeState,
  utterance: Utterance,
): NarrativePresence {
  if (state.phase === "awaiting_sound") return "dormant";
  if (
    state.phase === "composing" ||
    utterance.moment.kind === "composition" ||
    utterance.moment.kind === "ending"
  )
    return "composing";
  if (
    utterance.moment.kind === "correction" ||
    utterance.moment.kind === "teaching"
  )
    return "learning";
  if (utterance.moment.kind === "unknown") return "uncertain";
  return state.phase === "first_hearing" ? "listening" : "remembering";
}
