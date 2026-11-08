import { useState } from "react";
import { Icon, TRUST } from "./ui";
import type { Config, TrustLevel } from "./types";

const STEPS = [
  ["Understood the question", "orders.status, across 4 spellings of “Shipped”"],
  ["Number equals the SQL result", "415 is the cell the query returned"],
  ["SQL checked against your data", "Filters, joins, totals and the calculation"],
  ["Independent second query", "Written separately, reached the same 415"],
];

const REPAIRS = [
  ["$1,234.50", "1234.5", "Currency and separators"],
  ["(1,234.50)", "-1234.5", "Accounting negatives"],
  ["1.2K", "1200", "Abbreviations"],
  ["Jan 5, 2024", "2024-01-05", "Date formats"],
  ["TOTAL,,8120", "row removed", "Footer totals, when they match"],
  ["03/04/2026", "kept as text", "Unclear dates are never guessed"],
];

const DOMAINS = [
  "Retail",
  "Finance",
  "Healthcare",
  "HR",
  "Marketing",
  "Logistics",
  "Education",
  "Energy",
  "Manufacturing",
  "Real estate",
  "Environment",
  "Economy",
  "Sports",
];

export function Landing({
  config,
  busy,
  error,
  onUpload,
  onDemo,
  onTheme,
}: {
  config: Config | null;
  busy: boolean;
  error: string | null;
  onUpload: (files: FileList) => void;
  onDemo: () => void;
  onTheme: () => void;
}) {
  const [dragging, setDragging] = useState(false);
  const accept = (config?.allowed_extensions ?? [".csv", ".tsv", ".json", ".jsonl", ".xlsx", ".xls"]).join(",");
  return (
    <div className="landing">
      <nav className="lnav">
        <a className="brand" href="/">
          <img src="/static/favicon.svg" alt="" width={26} height={26} />
          VeriSight
        </a>
        <div>
          <a href="https://github.com/Md-Faiz-Alam/verisight/blob/main/docs/results.md" target="_blank" rel="noopener">
            Measured results
          </a>
          <a href="/docs" target="_blank" rel="noopener">
            API
          </a>
          <a href="https://github.com/Md-Faiz-Alam/verisight" target="_blank" rel="noopener">
            GitHub
          </a>
          <button type="button" className="ghost-icon" onClick={onTheme} aria-label="Switch colour theme">
            <Icon name="moon" />
          </button>
        </div>
      </nav>

      <section className="hero">
        <div className="hero-copy">
          <h1>
            Numbers you can
            <br />
            <em>cross-examine.</em>
          </h1>
          <p className="lede">
            Drop in a spreadsheet from any field. VeriSight repairs it in the open, builds the dashboard without AI, and
            makes every answer show its evidence.
          </p>
          <label
            className={`drop${dragging ? " on" : ""}${busy ? " busy" : ""}`}
            onDragOver={(event) => {
              event.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => {
              event.preventDefault();
              setDragging(false);
              if (event.dataTransfer.files.length) onUpload(event.dataTransfer.files);
            }}
          >
            <input
              type="file"
              multiple
              accept={accept}
              onChange={(event) => {
                if (event.target.files?.length) onUpload(event.target.files);
                event.target.value = "";
              }}
            />
            <span className="drop-icon">{busy ? <span className="spinner" /> : <Icon name="upload" size={20} />}</span>
            <span>
              <strong>{busy ? "Reading your files" : "Drop files, or browse"}</strong>
              <small>
                CSV, TSV, JSON, JSON Lines or Excel
                {config?.max_upload_mb ? ` · up to ${config.max_upload_mb} MB each` : ""}
              </small>
            </span>
          </label>
          <div className="hero-actions">
            <button type="button" className="btn primary" onClick={onDemo} disabled={busy}>
              Open the sample workspace
            </button>
            <span>Messy orders and customers. No account, no key.</span>
          </div>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
        </div>

        <figure className="specimen" aria-label="Example of an evidence trail">
          <figcaption>Example evidence trail</figcaption>
          <p className="specimen-q">How many orders were shipped?</p>
          <div className="specimen-num">415</div>
          <ol>
            {STEPS.map(([title, detail], index) => (
              <li key={title} style={{ animationDelay: `${index * 0.55 + 0.3}s` }}>
                <span className="trail-dot passed">
                  <Icon name="check" size={12} />
                </span>
                <div>
                  <b>{title}</b>
                  <p>{detail}</p>
                </div>
              </li>
            ))}
          </ol>
          <div className="specimen-foot" style={{ animationDelay: "2.8s" }}>
            <span className="badge ok">
              <span className="badge-mark">✓</span>Verified
            </span>
          </div>
        </figure>
      </section>

      <section className="band">
        <div className="band-head">
          <h2>Messy files, repaired in the open</h2>
          <p>Each change is listed. Anything that could mean two things stays as it was, with a warning.</p>
        </div>
        <table className="repairs">
          <tbody>
            {REPAIRS.map(([before, after, why]) => (
              <tr key={before}>
                <td>
                  <code>{before}</code>
                </td>
                <td className="arrow" aria-hidden="true">
                  →
                </td>
                <td>
                  <code className="after">{after}</code>
                </td>
                <td>{why}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="band">
        <div className="band-head">
          <h2>Trust is earned, one check at a time</h2>
          <p>A number copied from a query proves little. Each answer states exactly how far it was checked.</p>
        </div>
        <ul className="ladder">
          {(Object.keys(TRUST) as TrustLevel[]).map((level) => (
            <li key={level} className={TRUST[level].tone}>
              <b>{TRUST[level].label}</b>
              <span>{TRUST[level].note}</span>
            </li>
          ))}
        </ul>
      </section>

      <section className="band domains">
        <h2>Knows what it is looking at</h2>
        <ul>
          {DOMAINS.map((domain) => (
            <li key={domain}>{domain}</li>
          ))}
          <li className="muted">Anything else, as general data</li>
        </ul>
      </section>

      <footer className="lfoot">
        <p>
          Dashboards are computed without AI. Asking a question may send your schema and sample values to Gemini, only
          after you allow it. No trust level proves an answer is right, so the SQL is always one click away.
        </p>
      </footer>
    </div>
  );
}
