import { useEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { cellText, compact, downloadCsv, toNumber } from "./lib";
import type { Cell, TrustCheck, TrustLevel } from "./types";

const PATHS: Record<string, string> = {
  overview: "M3 13h8V3H3zM13 21h8V11h-8zM13 3v6h8V3zM3 21h8v-6H3z",
  ask: "M21 12a8 8 0 0 1-11.6 7.1L3 21l1.9-6.4A8 8 0 1 1 21 12Z",
  explore: "M3 5h18M3 12h18M3 19h18M8 5v14M16 5v14",
  quality: "M12 3l8 4v5c0 5-3.4 8-8 9-4.6-1-8-4-8-9V7zM9 12l2 2 4-4",
  model: "M4 4h6v6H4zM14 14h6v6h-6zM10 7h4a3 3 0 0 1 3 3v4",
  search: "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16ZM21 21l-4.3-4.3",
  moon: "M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z",
  upload: "M12 16V4m0 0-4 4m4-4 4 4M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3",
  download: "M12 4v12m0 0-4-4m4 4 4-4M4 20h16",
  close: "M6 6l12 12M18 6 6 18",
  send: "M5 12h14M13 6l6 6-6 6",
  check: "M5 12.5l4.5 4.5L19 7.5",
  logout: "M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9",
};

export function Icon({ name, size = 16 }: { name: string; size?: number }) {
  return (
    <svg className="icon" viewBox="0 0 24 24" width={size} height={size} aria-hidden="true">
      <path d={PATHS[name]} />
    </svg>
  );
}

export function useWidth<T extends HTMLElement>(): [RefObject<T>, number] {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    if (!ref.current) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);
  return [ref, width];
}

export function CountUp({ value }: { value: Cell }) {
  const target = toNumber(value);
  const [shown, setShown] = useState<number | null>(target);
  useEffect(() => {
    if (target === null || matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setShown(target);
      return;
    }
    let frame = 0;
    const started = performance.now();
    const tick = (now: number) => {
      const progress = Math.min(1, (now - started) / 480);
      setShown(target * (1 - (1 - progress) ** 3));
      if (progress < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [target]);
  return <>{target === null ? "–" : compact(shown === target ? value : shown)}</>;
}

const KEYWORDS = new Set(
  (
    "select distinct from where and or not in is null as join left right inner outer full on group by order having " +
    "limit offset union all with case when then else end between like ilike count sum avg min max cast date timestamp " +
    "lower upper trim coalesce nullif over partition desc asc exists interval extract round strftime date_diff median"
  ).split(" "),
);
const TOKEN = /('(?:[^']|'')*')|("(?:[^"]|"")*")|(\b\d+(?:\.\d+)?\b)|([A-Za-z_][A-Za-z0-9_]*)|(\s+|[^\sA-Za-z0-9_'"]+)/g;

export function Sql({ sql }: { sql: string }) {
  const [copied, setCopied] = useState(false);
  const parts = Array.from(sql.matchAll(TOKEN)).map((match, index) => {
    const kind = match[1]
      ? "str"
      : match[3]
        ? "num"
        : match[4] && KEYWORDS.has(match[4].toLowerCase())
          ? "kw"
          : undefined;
    return (
      <span key={index} className={kind}>
        {match[0]}
      </span>
    );
  });
  return (
    <div className="sql">
      <pre>{parts}</pre>
      <button
        type="button"
        className="sql-copy"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(sql);
            setCopied(true);
            setTimeout(() => setCopied(false), 1400);
          } catch {
            /* the text can still be selected */
          }
        }}
      >
        {copied ? "Copied" : "Copy"}
      </button>
    </div>
  );
}

export function DataTable({
  columns,
  rows,
  highlight,
}: {
  columns: string[];
  rows: Cell[][];
  highlight?: [number, number];
}) {
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            {columns.map((column, index) => (
              <th key={index}>{column}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, r) => (
            <tr key={r}>
              {row.map((cell, c) => (
                <td
                  key={c}
                  className={[
                    typeof cell === "number" ? "num" : "",
                    cell === null ? "null" : "",
                    highlight && highlight[0] === r && highlight[1] === c ? "cited" : "",
                  ].join(" ")}
                >
                  {cell === null ? "null" : cellText(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export interface CardData {
  columns: string[];
  rows: Cell[][];
}

export function Card({
  title,
  subtitle,
  sql,
  data,
  className = "",
  actions,
  children,
}: {
  title: string;
  subtitle?: string;
  sql?: string;
  data?: CardData;
  className?: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  const [mode, setMode] = useState<"chart" | "table" | "sql">("chart");
  return (
    <article className={`card ${className}`}>
      <header className="card-head">
        <div>
          <h3>{title}</h3>
          {subtitle && <p>{subtitle}</p>}
        </div>
        <div className="card-tools no-print">
          {mode === "chart" && actions}
          {(data || sql) && (
            <div className="seg small" role="group" aria-label={`${title} view`}>
              <button type="button" aria-pressed={mode === "chart"} onClick={() => setMode("chart")}>
                Chart
              </button>
              {data && (
                <button type="button" aria-pressed={mode === "table"} onClick={() => setMode("table")}>
                  Table
                </button>
              )}
              {sql && (
                <button type="button" aria-pressed={mode === "sql"} onClick={() => setMode("sql")}>
                  SQL
                </button>
              )}
            </div>
          )}
          {data && (
            <button
              type="button"
              className="ghost-icon"
              aria-label={`Download ${title} as CSV`}
              title="Download CSV"
              onClick={() => downloadCsv(title, data.columns, data.rows)}
            >
              <Icon name="download" size={14} />
            </button>
          )}
        </div>
      </header>
      <div className="card-body">
        {mode === "chart" && children}
        {mode === "table" && data && <DataTable columns={data.columns} rows={data.rows} />}
        {mode === "sql" && sql && <Sql sql={sql} />}
      </div>
    </article>
  );
}

export const TRUST: Record<TrustLevel, { label: string; tone: string; note: string }> = {
  computed: {
    label: "Computed without AI",
    tone: "ok",
    note: "Fixed rules turned your question into SQL.",
  },
  verified: {
    label: "Verified",
    tone: "ok",
    note: "The SQL passed every check, and a differently written second query agreed.",
  },
  number_matched: {
    label: "Number matches SQL only",
    tone: "warn",
    note: "A check could not run or added no new evidence, so this is not fully verified.",
  },
  needs_review: {
    label: "Needs review",
    tone: "warn",
    note: "A check failed. See why before using this number.",
  },
  not_verified: {
    label: "Not verified",
    tone: "bad",
    note: "No number could be tied to an executed result.",
  },
};

export function TrustBadge({ level }: { level: TrustLevel }) {
  const trust = TRUST[level];
  return (
    <span className={`badge ${trust.tone}`}>
      <span className="badge-mark" aria-hidden="true">
        {trust.tone === "ok" ? "✓" : "!"}
      </span>
      {trust.label}
    </span>
  );
}

const CHECK_NAMES: Record<string, string> = {
  compiled_without_ai: "Written by fixed rules",
  number_matches_sql: "Number equals the SQL result",
  sql_audit: "SQL checked against your data",
  population_review: "Right rows selected",
  second_query: "Independent second query",
  second_query_audit: "Second query checked against your data",
};

export function Trail({ checks }: { checks: TrustCheck[] }) {
  return (
    <ol className="trail">
      {checks.map((check, index) => (
        <li key={check.name} style={{ animationDelay: `${index * 70}ms` }}>
          <span className={`trail-dot ${check.status}`} aria-label={check.status.replace("_", " ")}>
            {check.status === "passed" ? <Icon name="check" size={12} /> : check.status === "failed" ? "!" : "–"}
          </span>
          <div>
            <b>{CHECK_NAMES[check.name] ?? check.name}</b>
            <p>{check.detail}</p>
          </div>
        </li>
      ))}
    </ol>
  );
}
