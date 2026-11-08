export type Cell = string | number | boolean | null;

export interface Config {
  server_key: boolean;
  model?: string;
  max_upload_mb?: number;
  max_files?: number;
  dataset_ttl_minutes?: number;
  allowed_extensions?: string[];
}

export interface ColumnSchema {
  name: string;
  logical_type: string;
}

export interface TableSchema {
  relation_name: string;
  row_count: number;
  column_count: number;
  columns: ColumnSchema[];
}

export interface ColumnProfile {
  name: string;
  missing_count?: number;
  missing_ratio?: number;
  distinct_count?: number;
  numeric_statistics?: { minimum: Cell; maximum: Cell } | null;
  datetime_statistics?: { earliest: Cell; latest: Cell } | null;
}

export interface Finding {
  issue_type: string;
  severity: "info" | "warning" | "error";
  relation_name: string | null;
  column_name: string | null;
  message: string;
  affected_count: number | null;
  affected_ratio: number | null;
  evidence?: { examples?: string[]; detail?: string };
}

export interface Dataset {
  dataset_id: string;
  files: { name: string; size_bytes: number }[];
  expires_in_seconds: number;
  profile: {
    schema: { tables: TableSchema[] };
    profiles: { tables: { relation_name: string; columns: ColumnProfile[] }[] };
    quality_findings: Finding[];
  };
}

export interface Kpi {
  label: string;
  value: Cell;
  sql: string;
}

export interface TrendPoint {
  period: string;
  value: Cell;
  rows: number;
}

export interface Trend {
  title: string;
  grain: string;
  points: TrendPoint[];
  sql: string;
}

export interface Bar {
  key: string;
  label: string;
  value: Cell;
  rows: number;
}

export interface Breakdown {
  title: string;
  column: string;
  bars: Bar[];
  categories: number;
  sql: string;
}

export interface Bin {
  low: number;
  high: number;
  rows: number;
}

export interface Histogram {
  title: string;
  bins: Bin[];
  sql: string;
}

export interface Insight {
  text: string;
  sql: string;
}

export interface TableLink {
  left: string;
  left_column: string;
  right: string;
  right_column: string;
  kind: "one_to_one" | "one_to_many" | "many_to_one" | "many_to_many";
  overlap: number;
}

export interface Dashboard {
  relation: string;
  relations: { name: string; rows: number }[];
  domain: {
    key: string;
    label: string;
    focus: string;
    confidence: string;
    matched: string[];
  };
  filters: { column: string; value: string }[];
  excluded_totals: string[];
  kpis: Kpi[];
  trend: Trend | null;
  breakdowns: Breakdown[];
  histograms: Histogram[];
  insights: Insight[];
  suggestions: string[];
  time: { column: string; earliest: string; latest: string } | null;
  links: TableLink[];
}

export interface RowsPage {
  relation: string;
  columns: { name: string; logical_type: string }[];
  rows: Cell[][];
  total: number;
  offset: number;
  limit: number;
  sql: string;
}

export interface TrustCheck {
  name: string;
  status: "passed" | "failed" | "not_assessed";
  detail: string;
}

export type TrustLevel =
  | "computed"
  | "verified"
  | "number_matched"
  | "needs_review"
  | "not_verified";

export interface Claim {
  claim: { operation: string; expected: string | number };
  verification: { status: string; actual: string | number | null };
}

export interface Step {
  question: string;
  sql: string;
  columns: string[];
  rows: Cell[][];
}

export interface Answer {
  outcome: "verified" | "unverified" | "clarify";
  status: string;
  answer: string;
  options?: string[];
  claims?: Claim[];
  steps?: Step[];
  cross_check?: { status: string; sql: string | null; independent_value: Cell } | null;
  trust?: { level: TrustLevel; checks: TrustCheck[] } | null;
  failure?: { kind?: string } | null;
  model_calls?: unknown[];
  elapsed_seconds?: number;
}

export type View = "overview" | "ask" | "explore" | "quality" | "model";

export interface Turn {
  id: number;
  question: string;
  answer?: Answer;
  error?: { message: string; code?: string };
  type: "number" | "difference" | "any";
}
