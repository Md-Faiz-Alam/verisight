import { exact, percent, readable } from "./lib";
import type { Dataset, TableLink } from "./types";

/** The Model view: how the uploaded tables connect through shared keys. */
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
