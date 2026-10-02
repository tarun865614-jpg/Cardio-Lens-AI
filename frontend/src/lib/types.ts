export type Role = "clinician" | "researcher" | "admin";

export interface User {
  id: number;
  email: string;
  full_name: string;
  role: Role;
  org_id: number;
  is_active: boolean;
  is_demo: boolean;
}

export type CheckStatus = "pass" | "warn" | "fail";
export type QualityOverall = "usable" | "usable_with_warnings" | "unusable";
export type ResultTier = "signal_only" | "experimental" | "validated";
export type ModelStatus = "not_run_quality" | "no_model" | "service_error" | "completed";
export type ReviewStatus = "pending" | "in_review" | "reviewed" | "flagged";

export interface QualityCheck {
  id: string;
  label: string;
  status: CheckStatus;
  value: number | string | null;
  threshold: string;
  explanation: string;
}

export interface QualityReport {
  pipeline_version: string;
  overall: QualityOverall;
  recommend_rerecord: boolean;
  headline: string;
  checks: QualityCheck[];
  notes: string[];
  disclaimer: string;
}

export interface Spectrogram {
  freqs_hz: number[];
  times_s: number[];
  db_u8: number[][];
  range_db: number;
}

export interface SignalSummary {
  duration_s?: number;
  sample_rate_hz?: number;
  analysis_sample_rate_hz?: number;
  rms_dbfs?: number;
  peak_dbfs?: number;
  band_energy_fraction?: Record<string, number>;
  envelope_periodicity?: number;
  envelope_cycle_rate_per_min?: number | null;
  envelope_cycle_rate_note?: string;
  windows?: { start_s: number; end_s: number; snr_db: number; periodicity: number }[];
  waveform?: [number, number][];
  envelope?: number[];
  spectrogram?: Spectrogram;
}

export interface ModelScore {
  category: string;
  label: string;
  score: number;
  score_type: "calibrated_probability" | "uncalibrated_score";
}

export interface ModelOutput {
  abstained: boolean;
  abstain_reason: string | null;
  scores: ModelScore[];
  segments: { start_s: number; end_s: number }[];
  model_card?: Record<string, unknown> & {
    name: string;
    version: string;
    intended_use: string;
    validation_status: string;
    validation_evidence?: string | null;
    categories: { id: string; label?: string }[];
    training_datasets?: string[];
  };
  limitations?: string[];
  tier_reason?: string;
}

export interface Analysis {
  id: number;
  created_at: string;
  pipeline_version: string;
  quality: QualityReport;
  signal_summary: SignalSummary;
  model_status: ModelStatus;
  model_status_text: string;
  result_tier: ResultTier;
  result_tier_text: string;
  model_name: string | null;
  model_version: string | null;
  model_output: ModelOutput | null;
  error: string | null;
  boundaries: string[];
}

export interface Review {
  id: number;
  created_at: string;
  status: ReviewStatus;
  note: string;
  clinician_conclusion: string | null;
  flagged_for_followup: boolean;
  reviewer: { id: number; full_name: string } | null;
}

export interface Recording {
  id: number;
  patient_id: number;
  patient_pseudonym: string | null;
  created_at: string;
  recorded_at: string | null;
  original_filename: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
  sample_rate: number | null;
  channels: number | null;
  duration_s: number | null;
  device_type: string;
  auscultation_site: string;
  environment: string;
  is_demo: boolean;
  consent_confirmed: boolean;
  quality_status: QualityOverall | null;
  review_status: ReviewStatus;
  retention_until: string | null;
  audio_available: boolean;
  deleted_at: string | null;
  latest_result_tier: ResultTier | null;
  latest_model_status: ModelStatus | null;
  analyses?: Analysis[];
  reviews?: Review[];
}

export interface Patient {
  id: number;
  pseudonym: string;
  external_ref: string | null;
  birth_year: number | null;
  sex: string | null;
  is_synthetic: boolean;
  created_at: string;
  recording_count: number;
  last_recording_at: string | null;
  open_reviews: number;
  recordings?: Recording[];
}

export interface SystemMode {
  mode: "research_demo" | "experimental_model" | "validated_model" | "model_error";
  label: string;
  detail: string;
  model: { name: string; version: string; validation_status: string; calibrated: boolean } | null;
}

export interface Dashboard {
  counts: Record<"patients" | "recordings" | "pending_review" | "flagged" | "quality_unusable" | "quality_warnings", number>;
  recent: Recording[];
  pending_reviews: Recording[];
  flagged: Recording[];
  quality_issues: Recording[];
  system: SystemMode;
}

export interface Proportion {
  value: number | null;
  ci_low: number | null;
  ci_high: number | null;
  k?: number;
  n?: number;
  reason?: string;
  method?: string;
}

export interface MetricBlock {
  n_recordings: number;
  n_patients: number;
  failed_recording_rate: Proportion;
  n?: number;
  n_positive?: number;
  n_negative?: number;
  prevalence?: number | null;
  threshold?: number;
  confusion?: { tp: number; fp: number; tn: number; fn: number };
  sensitivity?: Proportion;
  specificity?: Proportion;
  ppv?: Proportion;
  npv?: Proportion;
  accuracy?: Proportion;
  auc?: Proportion;
  roc?: { fpr: number; tpr: number; threshold: number | null }[];
  calibration?: {
    bins: { bin_low: number; bin_high: number; n: number; mean_predicted: number; observed_rate: number }[];
    ece: number;
    brier: number;
    slope: number | null;
    intercept: number | null;
  } | null;
  warning?: string;
  reason?: string;
}

export interface EvaluationRun {
  id: number;
  created_at: string;
  split_name: string;
  is_external: boolean;
  threshold: number;
  n_recordings: number;
  n_patients: number;
  warnings: string[];
  model: { id: number; name: string; version: string };
  dataset: { id: number; name: string };
  headline: { sensitivity: number | null; specificity: number | null; auc: number | null };
  metrics?: { overall: MetricBlock; subgroups: Record<string, Record<string, MetricBlock>> };
}

export interface Dataset {
  id: number;
  name: string;
  source_url: string | null;
  license: string;
  permitted_use: string;
  provenance: string;
  label_definitions: string;
  recording_devices: string;
  population: string;
  limitations: string;
  n_patients: number | null;
  n_recordings: number | null;
  is_downloaded: boolean;
}

export interface ModelVersion {
  id: number;
  name: string;
  version: string;
  intended_use: string;
  categories: { id: string; label?: string }[];
  validation_status: string;
  validation_evidence: string | null;
  training_datasets: string[];
  weights_sha256: string | null;
  is_active: boolean;
  created_at: string;
}

export interface AuditEntry {
  id: number;
  ts: string;
  actor: string | null;
  action: string;
  entity_type: string;
  entity_id: string | null;
  details: Record<string, unknown>;
  hash: string;
}
