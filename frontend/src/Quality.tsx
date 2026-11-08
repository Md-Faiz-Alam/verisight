import { cellText, exact, percent, readable } from "./lib";
import type { ColumnProfile, Dataset, Finding, TableLink } from "./types";

const LABELS: Record<string, string> = {
  missing_values: "Missing values",
  missing_value_markers: "Placeholders treated as missing",
  formatted_numbers: "Numbers cleaned",
  label_variants: "Label variants",
  trimmed_column_name: "Column name trimmed",
  named_blank_column: "Column had no header",
  total_row: "Rows that hold totals",
  reformatted_dates: "Dates recognised",
  ambiguous_dates: "Unclear dates",
  ambiguous_numbers: "Unclear numbers",
  stray_values: "Stray values",
  possible_missing_labels: "Possibly missing",
  removed_rows: "Summary row removed",
  file_structure: "File layout repaired",
  constant_column: "Single repeated value",
  duplicate_rows: "Duplicate rows",
};
const CHANGED = new Set([
  "missing_value_markers",
  "formatted_numbers",
  "trimmed_column_name",
  "named_blank_column",
  "reformatted_dates",
  "stray_values",
  "removed_rows",
  "file_structure",
]);

function FindingItem({ finding }: { finding: Finding }) {
  const where = finding.column_name
    ? `${finding.relation_name}.${finding.column_name}`
    : (finding.relation_name ?? "dataset");
  return (
    <li className={`finding ${finding.severity}`}>
      <div className="finding-head">
        <b>{LABELS[finding.issue_type] ?? finding.issue_type}</b>
        <code>{where}</code>
        {typeof finding.affected_count === "number" && (
          <span>
            {exact(finding.affected_count)}
            {finding.affected_ratio !== null ? ` · ${percent(finding.affected_ratio)}` : ""}
          </span>
        )}
      </div>
      <p>{finding.message}</p>
      {finding.evidence?.detail && <p className="detail">{finding.evidence.detail}</p>}
      {finding.evidence?.examples && finding.evidence.examples.length > 0 && (
        <div className="examples">
          {finding.evidence.examples.map((example) => (
            <code key={example}>{example}</code>
          ))}
        </div>
      )}
    </li>
  );
}

function range(profile: ColumnProfile | undefined): string {
  if (!profile) return "";
  if (profile.datetime_statistics) {
    const s = profile.datetime_statistics;
    return `${String(s.earliest).slice(0, 10)} → ${String(s.latest).slice(0, 10)}`;
  }
  if (profile.numeric_statistics) {
    const s = profile.numeric_statistics;
    return `${cellText(s.minimum)} → ${cellText(s.maximum)}`;
  }
  return typeof profile.distinct_count === "number" ? `${exact(profile.distinct_count)} distinct` : "";
}

export function Quality({ dataset }: { dataset: Dataset }) {
  const relevant = dataset.profile.quality_findings.filter((f) => f.issue_type !== "high_cardinality");
  const changed = relevant.filter((f) => CHANGED.has(f.issue_type));
  const check = relevant.filter((f) => !CHANGED.has(f.issue_type));
  const profiles = new Map(dataset.profile.profiles.tables.map((t) => [t.relation_name, t.columns]));
  return (
    <div className="quality">
      <div className="q-cols">
        <section>
          <h2>
            Worth checking <span className="count">{check.length}</span>
          </h2>
          {check.length === 0 ? (
            <p className="muted">Nothing to check.</p>
          ) : (
            <ul className="findings">
              {check.map((f, i) => (
                <FindingItem key={i} finding={f} />
              ))}
            </ul>
          )}
        </section>
        <section>
          <h2>
            What VeriSight changed <span className="count">{changed.length}</span>
          </h2>
          {changed.length === 0 ? (
            <p className="muted">The file needed no repairs.</p>
          ) : (
            <ul className="findings">
              {changed.map((f, i) => (
                <FindingItem key={i} finding={f} />
              ))}
            </ul>
          )}
        </section>
      </div>
      <h2>Columns</h2>
      {dataset.profile.schema.tables.map((table) => {
        const columns = new Map((profiles.get(table.relation_name) ?? []).map((c) => [c.name, c]));
        return (
          <section key={table.relation_name} className="card">
            <h3 className="table-title">
              <code>{table.relation_name}</code>
              <small>
                {exact(table.row_count)} rows · {table.column_count} columns
              </small>
            </h3>
            <div className="table-wrap tall">
              <table className="data">
                <thead>
                  <tr>
                    <th>Column</th>
                    <th>Type</th>
                    <th>Present</th>
                    <th>Range</th>
                  </tr>
                </thead>
                <tbody>
                  {table.columns.map((column) => {
                    const profile = columns.get(column.name);
                    const missing = profile?.missing_ratio ?? 0;
                    return (
                      <tr key={column.name}>
                        <td>
                          <code>{column.name}</code>
                        </td>
                        <td>{column.logical_type}</td>
                        <td>
                          <span className="meter" title={`${percent(missing)} missing`}>
                            <span style={{ width: `${(1 - missing) * 100}%` }} />
                          </span>
                          {percent(1 - missing)}
                        </td>
                        <td>{range(profile)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        );
      })}
    </div>
  );
}

const KINDS: Record<TableLink["kind"], string> = {
  one_to_one: "one to one",
  one_to_many: "one to many",
  many_to_one: "many to one",
  many_to_many: "many to many",
};

export function Model({ dataset, links }: { dataset: Dataset; links: TableLink[] }) {
  const tables = dataset.profile.schema.tables;
  return (
    <div className="model">
      {tables.length < 2 && <p className="notice">Upload two or more files to see how they connect.</p>}
      {tables.length > 1 && links.length === 0 && (
        <p className="notice">No shared keys were found. Tables connect through a column with the same name that is an ID, or that has one row per value in at least one table.</p>
      )}
      {links.map((link) => (
        <div className="link-row" key={`${link.left}.${link.left_column}-${link.right}`}>
          <div className="node">
            <b>{link.left}</b>
            <code>{link.left_column}</code>
          </div>
          <div className="connector">
            <span>{KINDS[link.kind]}</span>
            <small>{percent(link.overlap)} of keys match</small>
          </div>
          <div className="node">
            <b>{link.right}</b>
            <code>{link.right_column}</code>
          </div>
          {link.kind.includes("many") && (
            <p className="link-note">Joining these can repeat rows. VeriSight&apos;s SQL audit flags sums that get inflated this way.</p>
          )}
        </div>
      ))}
      <div className="node-grid">
        {tables.map((table) => (
          <article className="card" key={table.relation_name}>
            <h3 className="table-title">
              <code>{table.relation_name}</code>
              <small>{exact(table.row_count)} rows</small>
            </h3>
            <ul>
              {table.columns.map((column) => (
                <li key={column.name}>
                  {readable(column.name)}
                  <small>{column.logical_type}</small>
                </li>
              ))}
            </ul>
          </article>
        ))}
      </div>
    </div>
  );
}
