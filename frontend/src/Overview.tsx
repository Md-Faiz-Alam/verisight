import { useEffect, useState } from "react";
import { Histogram, RankedBars, TrendChart, type TrendForm } from "./charts";
import { compact, post, readable } from "./lib";
import { Card, CountUp, Icon, Sql } from "./ui";
import type { Dashboard, Dataset } from "./types";

export interface Selection {
  relation: string | null;
  filters: { column: string; value: string; label: string }[];
  start: string;
  end: string;
}

export function useDashboard(dataset: Dataset, selection: Selection, onLost: () => void) {
  const [data, setData] = useState<Dashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const key = JSON.stringify(selection);
  useEffect(() => {
    let live = true;
    setLoading(true);
    post<Dashboard>(`/api/datasets/${dataset.dataset_id}/dashboard`, {
      relation: selection.relation,
      filters: selection.filters.map(({ column, value }) => ({ column, value })),
      start: selection.start || null,
      end: selection.end || null,
    })
      .then((result) => {
        if (!live) return;
        setData(result);
        setError(null);
      })
      .catch((err) => {
        if (!live) return;
        if (err.code === "dataset_not_found") onLost();
        else setError(err.message);
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
    // The serialised selection stands for its contents.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dataset.dataset_id, key]);
  return { data, loading, error };
}

function Kpis({ data }: { data: Dashboard }) {
  const [open, setOpen] = useState<number | null>(null);
  return (
    <section className="kpis" aria-label="Key figures">
      {data.kpis.map((kpi, index) => (
        <div className="kpi" key={kpi.label}>
          <span className="kpi-label">{kpi.label}</span>
          <strong title={String(kpi.value)}>
            <CountUp value={kpi.value} />
          </strong>
          <button
            type="button"
            className="link no-print"
            aria-expanded={open === index}
            onClick={() => setOpen(open === index ? null : index)}
          >
            {open === index ? "Hide SQL" : "SQL"}
          </button>
          {open === index && <Sql sql={kpi.sql} />}
        </div>
      ))}
    </section>
  );
}

export function Overview({
  data,
  loading,
  error,
  selection,
  onSelect,
}: {
  data: Dashboard | null;
  loading: boolean;
  error: string | null;
  selection: Selection;
  onSelect: (next: Selection) => void;
}) {
  const [form, setForm] = useState<TrendForm>("area");
  if (error) {
    return (
      <p className="notice bad" role="alert">
        {error}
      </p>
    );
  }
  if (!data) {
    return (
      <div className="skeletons">
        <div className="sk tall" />
        <div className="sk big" />
        <div className="sk" />
        <div className="sk" />
      </div>
    );
  }
  const toggle = (column: string, value: string, label: string) => {
    const same = selection.filters.some((f) => f.column === column && f.value === value);
    const kept = selection.filters.filter((f) => f.column !== column);
    onSelect({ ...selection, filters: same ? kept : [...kept, { column, value, label }] });
  };
  const trend = data.trend;
  return (
    <div className={`dash${loading ? " updating" : ""}`}>
      <div className="controls no-print">
        {data.relations.length > 1 && (
          <div className="seg" role="group" aria-label="Table">
            {data.relations.map((relation) => (
              <button
                key={relation.name}
                type="button"
                aria-pressed={relation.name === data.relation}
                onClick={() => onSelect({ relation: relation.name, filters: [], start: "", end: "" })}
              >
                {relation.name}
                <small>{compact(relation.rows)}</small>
              </button>
            ))}
          </div>
        )}
        {data.time && (
          <div className="dates">
            <span>{readable(data.time.column)}</span>
            <input
              type="date"
              aria-label="From date"
              min={data.time.earliest}
              max={selection.end || data.time.latest}
              value={selection.start}
              onChange={(event) => onSelect({ ...selection, start: event.target.value })}
            />
            <span aria-hidden="true">–</span>
            <input
              type="date"
              aria-label="To date"
              min={selection.start || data.time.earliest}
              max={data.time.latest}
              value={selection.end}
              onChange={(event) => onSelect({ ...selection, end: event.target.value })}
            />
          </div>
        )}
        {selection.filters.map((filter) => (
          <button
            key={filter.column}
            type="button"
            className="chip-filter"
            aria-label={`Remove filter ${filter.column} ${filter.label}`}
            onClick={() => toggle(filter.column, filter.value, filter.label)}
          >
            {readable(filter.column)} <b>{filter.label}</b>
            <Icon name="close" size={12} />
          </button>
        ))}
        {(selection.filters.length > 0 || selection.start || selection.end) && (
          <button type="button" className="link" onClick={() => onSelect({ ...selection, filters: [], start: "", end: "" })}>
            Clear all
          </button>
        )}
      </div>

      {data.excluded_totals.length > 0 && (
        <p className="notice">
          Rows that hold totals of other rows are left out, so nothing is counted twice:{" "}
          {data.excluded_totals.join("; ")}.
        </p>
      )}

      {data.kpis.length > 0 && <Kpis data={data} />}

      <div className="grid">
        {trend && (
          <Card
            className={data.insights.length ? "w8" : "w12"}
            title={trend.title}
            subtitle={`${trend.points.length} ${trend.grain}s`}
            sql={trend.sql}
            data={{
              columns: ["Period", "Value", "Rows"],
              rows: trend.points.map((p) => [p.period, p.value, p.rows]),
            }}
            actions={
              <div className="seg small" role="group" aria-label="Chart type">
                {(["area", "line", "columns"] as TrendForm[]).map((option) => (
                  <button key={option} type="button" aria-pressed={form === option} onClick={() => setForm(option)}>
                    {option[0].toUpperCase() + option.slice(1)}
                  </button>
                ))}
              </div>
            }
          >
            <TrendChart points={trend.points} label={trend.title} form={form} />
          </Card>
        )}
        {data.insights.length > 0 && (
          <article className={`card insights ${trend ? "w4" : "w12"}`}>
            <header className="card-head">
              <div>
                <h3>What stands out</h3>
                <p>Calculated from your data, not written by AI</p>
              </div>
            </header>
            <ul>
              {data.insights.map((insight) => (
                <li key={insight.text}>{insight.text}</li>
              ))}
            </ul>
          </article>
        )}
        {data.breakdowns.map((item) => (
          <Card
            key={item.column}
            className="w6"
            title={item.title}
            subtitle={`${item.categories > item.bars.length ? `Top ${item.bars.length} of ${item.categories}` : `${item.categories} categories`} · select one to filter`}
            sql={item.sql}
            data={{
              columns: ["Category", "Value", "Rows"],
              rows: item.bars.map((b) => [b.label, b.value, b.rows]),
            }}
          >
            <RankedBars
              bars={item.bars}
              selected={selection.filters.find((f) => f.column === item.column)?.value}
              onPick={(bar) => toggle(item.column, bar.key, bar.label)}
            />
          </Card>
        ))}
        {data.histograms.map((item) => (
          <Card
            key={item.title}
            className="w6"
            title={item.title}
            subtitle={`Rows in ${item.bins.length} equal ranges`}
            sql={item.sql}
            data={{ columns: ["From", "To", "Rows"], rows: item.bins.map((b) => [b.low, b.high, b.rows]) }}
          >
            <Histogram bins={item.bins} label={item.title} />
          </Card>
        ))}
      </div>
    </div>
  );
}
