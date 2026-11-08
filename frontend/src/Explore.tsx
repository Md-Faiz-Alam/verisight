import { useEffect, useState } from "react";
import { downloadCsv, exact, post, rawText } from "./lib";
import { Icon, Sql } from "./ui";
import type { Dataset, RowsPage } from "./types";

const PAGE = 50;
const TYPES: Record<string, string> = {
  integer: "123",
  float: "1.5",
  decimal: "1.5",
  string: "Aa",
  boolean: "T/F",
  datetime: "Date",
};

export function Explore({ dataset, initial }: { dataset: Dataset; initial: string }) {
  const tables = dataset.profile.schema.tables.filter((table) => table.row_count > 0);
  const [relation, setRelation] = useState(initial);
  const [offset, setOffset] = useState(0);
  const [sort, setSort] = useState<{ column: string; descending: boolean } | null>(null);
  const [search, setSearch] = useState("");
  const [applied, setApplied] = useState("");
  const [page, setPage] = useState<RowsPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showSql, setShowSql] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => {
      setApplied(search);
      setOffset(0);
    }, 250);
    return () => clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    let live = true;
    post<RowsPage>(`/api/datasets/${dataset.dataset_id}/rows`, {
      relation,
      offset,
      limit: PAGE,
      sort: sort?.column ?? null,
      descending: sort?.descending ?? false,
      search: applied,
    })
      .then((result) => {
        if (!live) return;
        setPage(result);
        setError(null);
      })
      .catch((err) => {
        if (live) setError(err.message);
      });
    return () => {
      live = false;
    };
  }, [dataset.dataset_id, relation, offset, sort, applied]);

  const last = page ? Math.min(offset + PAGE, page.total) : 0;
  return (
    <div className="explore">
      <div className="controls">
        {tables.length > 1 && (
          <div className="seg" role="group" aria-label="Table">
            {tables.map((table) => (
              <button
                key={table.relation_name}
                type="button"
                aria-pressed={table.relation_name === relation}
                onClick={() => {
                  setRelation(table.relation_name);
                  setOffset(0);
                  setSort(null);
                }}
              >
                {table.relation_name}
              </button>
            ))}
          </div>
        )}
        <label className="search">
          <Icon name="search" size={14} />
          <input
            type="search"
            placeholder="Search every column"
            aria-label="Search every column"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
        <span className="spacer" />
        <button type="button" className="link" aria-expanded={showSql} onClick={() => setShowSql(!showSql)}>
          SQL
        </button>
        {page && (
          <button
            type="button"
            className="btn small"
            onClick={() => downloadCsv(relation, page.columns.map((c) => c.name), page.rows)}
          >
            <Icon name="download" size={13} /> This page
          </button>
        )}
      </div>
      {showSql && page && <Sql sql={page.sql} />}
      {error && (
        <p className="notice bad" role="alert">
          {error}
        </p>
      )}
      {page && (
        <>
          <div className="grid-wrap">
            <table className="data explorer">
              <thead>
                <tr>
                  {page.columns.map((column) => {
                    const active = sort?.column === column.name;
                    return (
                      <th key={column.name} aria-sort={active ? (sort!.descending ? "descending" : "ascending") : "none"}>
                        <button
                          type="button"
                          onClick={() => {
                            setOffset(0);
                            setSort(active && sort!.descending ? null : { column: column.name, descending: active });
                          }}
                        >
                          <span className="type">{TYPES[column.logical_type] ?? "·"}</span>
                          {column.name}
                          <span className="sort" aria-hidden="true">
                            {active ? (sort!.descending ? "↓" : "↑") : ""}
                          </span>
                        </button>
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {page.rows.map((row, r) => (
                  <tr key={r}>
                    {row.map((cell, c) => (
                      <td key={c} className={`${typeof cell === "number" ? "num" : ""}${cell === null ? " null" : ""}`}>
                        {cell === null ? "null" : rawText(cell)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="pager">
            <span>{page.total === 0 ? "No rows match" : `${exact(offset + 1)}–${exact(last)} of ${exact(page.total)} rows`}</span>
            <button type="button" className="btn small" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
              Previous
            </button>
            <button type="button" className="btn small" disabled={last >= page.total} onClick={() => setOffset(offset + PAGE)}>
              Next
            </button>
          </div>
        </>
      )}
    </div>
  );
}
