"""Event type names (doc 08 "Event envelope"). The log itself is ``storage.repos.EventRepo``."""

RECORDING_CAPTURED = "RecordingCaptured"
RECORDING_REJECTED = "RecordingRejected"
FEATURES_EXTRACTED = "FeaturesExtracted"
RECORDING_DELETED = "RecordingDeleted"
JOB_FAILED = "JobFailed"

# M2
AUDIO_INFERENCE_COMPLETED = "AudioInferenceCompleted"
AUDIO_INFERENCE_FAILED = "AudioInferenceFailed"
ANNOTATION_SUBMITTED = "AnnotationSubmitted"
PREDICTION_CONFIRMED = "PredictionConfirmed"
PREDICTION_CORRECTED = "PredictionCorrected"
CUSTOM_CATEGORY_CREATED = "CustomCategoryCreated"
ACOUSTIC_MEMORY_UPDATED = "AcousticMemoryUpdated"
UNKNOWN_SOUND_OBSERVED = "UnknownSoundObserved"

# M3
ARTIFACT_RENDERED = "ArtifactRendered"
ATLAS_UPDATED = "AtlasUpdated"

# M4
COMPOSITION_CREATED = "CompositionCreated"
COMPOSITION_PLANNED = "CompositionPlanned"
COMPOSITION_RENDERED = "CompositionRendered"
COMPOSITION_FAILED = "CompositionFailed"
COMPOSITION_REVISED = "CompositionRevised"
COMPOSITION_DELETED = "CompositionDeleted"
