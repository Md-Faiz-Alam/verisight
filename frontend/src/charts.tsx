import { useState } from "react";
import { compact, toNumber } from "./lib";
import { useWidth } from "./ui";
import type { Bar, Bin, TrendPoint } from "./types";

function niceScale(rawLow: number, rawHigh: number, count = 4) {
  const low = Math.min(rawLow, rawHigh);
  let high = Math.max(rawLow, rawHigh);
  if (low === high) high = low + (Math.abs(low) || 1);
  const rough = (high - low) / count;
  const power = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= rough) as number;
  const start = Math.floor(low / step) * step;
  const end = Math.ceil(high / step) * step;
  const ticks: number[] = [];
  for (let tick = start; tick <= end + step / 2; tick += step) ticks.push(Math.round(tick / step) * step);
  return { start, end, ticks };
}

interface Tip {
  x: number;
  y: number;
  title: string;
  lines: string[];
}

function Tooltip({ tip, width }: { tip: Tip | null; width: number }) {
  if (!tip) return null;
  const left = Math.max(4, Math.min(tip.x + 12, width - 180));
  return (
    <div className="tip" style={{ left, top: Math.max(0, tip.y - 66) }}>
      <b>{tip.title}</b>
      {tip.lines.map((line) => (
        <span key={line}>{line}</span>
      ))}
    </div>
  );
}

export type TrendForm = "area" | "line" | "columns";

export function TrendChart({ points, label, form }: { points: TrendPoint[]; label: string; form: TrendForm }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [active, setActive] = useState<number | null>(null);
  const usable = points
    .map((point) => ({ ...point, number: toNumber(point.value) as number }))
    .filter((point) => point.number !== null);
  const height = 300;
  const m = { top: 14, right: 20, bottom: 28, left: 56 };
  const ready = width > 0 && usable.length > 1;
  const values = usable.map((point) => point.number);
  const low = Math.min(...values, form === "columns" ? 0 : Infinity);
  const high = Math.max(...values);
  const scale = niceScale(low >= 0 && low < high * 0.6 ? 0 : low, high);
  const inner = width - m.left - m.right;
  const x = (i: number) => m.left + (i / (usable.length - 1)) * inner;
  const y = (v: number) => height - m.bottom - ((v - scale.start) / (scale.end - scale.start)) * (height - m.top - m.bottom);
  const line = usable.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(p.number).toFixed(1)}`).join("");
  const base = y(Math.max(scale.start, Math.min(0, scale.end)));
  const band = inner / usable.length;
  const every = Math.max(1, Math.ceil(usable.length / Math.max(2, Math.floor(inner / 84))));
  const last = usable.length - 1;
  const point = active === null ? null : usable[active];
  return (
    <div className="chart" ref={ref}>
      {ready && (
        <svg
          viewBox={`0 0 ${width} ${height}`}
          width={width}
          height={height}
          role="img"
          aria-label={`${label}, ${usable.length} periods. Open Table for the values.`}
          onPointerLeave={() => setActive(null)}
          onPointerMove={(event) => {
            const box = event.currentTarget.getBoundingClientRect();
            const ratio = (event.clientX - box.left - m.left) / inner;
            setActive(Math.max(0, Math.min(last, Math.round(ratio * last))));
          }}
        >
          {scale.ticks.map((tick) => (
            <g key={tick}>
              <line className={tick === 0 ? "axis" : "grid"} x1={m.left} x2={width - m.right} y1={y(tick)} y2={y(tick)} />
              <text className="tick" x={m.left - 8} y={y(tick) + 4} textAnchor="end">
                {compact(tick)}
              </text>
            </g>
          ))}
          {usable.map(
            (p, i) =>
              (i % every === 0 || i === last) &&
              (i === last || last - i >= every / 2) && (
                <text
                  key={p.period}
                  className="tick"
                  x={form === "columns" ? m.left + band * (i + 0.5) : x(i)}
                  y={height - 8}
                  textAnchor={form === "columns" ? "middle" : i === 0 ? "start" : i === last ? "end" : "middle"}
                >
                  {p.period}
                </text>
              ),
          )}
          {form === "columns" ? (
            usable.map((p, i) => {
              const w = Math.min(24, Math.max(2, band - 3));
              const left = m.left + band * i + (band - w) / 2;
              return (
                <rect
                  key={p.period}
                  className={`column${active === i ? " on" : ""}`}
                  x={left}
                  y={Math.min(y(p.number), base)}
                  width={w}
                  height={Math.abs(base - y(p.number))}
                  rx={Math.min(3, w / 2)}
                />
              );
            })
          ) : (
            <>
              {form === "area" && (
                <path className="area" d={`${line}L${x(last).toFixed(1)} ${base}L${x(0).toFixed(1)} ${base}Z`} />
              )}
              <path key={`${form}-${usable.length}`} className="line" d={line} pathLength={1} />
              <circle className="dot" cx={x(last)} cy={y(usable[last].number)} r={4} />
            </>
          )}
          {point && active !== null && form !== "columns" && (
            <g>
              <line className="cross" x1={x(active)} x2={x(active)} y1={m.top} y2={height - m.bottom} />
              <circle className="dot" cx={x(active)} cy={y(point.number)} r={5} />
            </g>
          )}
        </svg>
      )}
      <Tooltip
        width={width}
        tip={
          point && active !== null
            ? {
                x: form === "columns" ? m.left + band * active : x(active),
                y: y(point.number),
                title: point.period,
                lines: [compact(point.number), `${point.rows.toLocaleString("en-US")} rows`],
              }
            : null
        }
      />
    </div>
  );
}

export function Histogram({ bins, label }: { bins: Bin[]; label: string }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [active, setActive] = useState<number | null>(null);
  const height = 210;
  const m = { top: 12, right: 8, bottom: 26, left: 44 };
  const scale = niceScale(0, Math.max(...bins.map((b) => b.rows), 1), 3);
  const inner = width - m.left - m.right;
  const band = inner / bins.length;
  const w = Math.min(26, Math.max(2, band - 3));
  const y = (v: number) => height - m.bottom - (v / scale.end) * (height - m.top - m.bottom);
  const bin = active === null ? null : bins[active];
  return (
    <div className="chart" ref={ref}>
      {width > 0 && (
        <svg
          viewBox={`0 0 ${width} ${height}`}
          width={width}
          height={height}
          role="img"
          aria-label={`${label}, ${bins.length} equal ranges. Open Table for the values.`}
          onPointerLeave={() => setActive(null)}
        >
          {scale.ticks.map((tick) => (
            <g key={tick}>
              <line className={tick === 0 ? "axis" : "grid"} x1={m.left} x2={width - m.right} y1={y(tick)} y2={y(tick)} />
              <text className="tick" x={m.left - 7} y={y(tick) + 4} textAnchor="end">
                {compact(tick)}
              </text>
            </g>
          ))}
          {bins.map((item, i) => (
            <g key={i} onPointerEnter={() => setActive(i)}>
              {item.rows > 0 && (
                <rect
                  className={`column${active === i ? " on" : ""}`}
                  x={m.left + band * i + (band - w) / 2}
                  y={y(item.rows)}
                  width={w}
                  height={y(0) - y(item.rows)}
                  rx={Math.min(3, w / 2)}
                />
              )}
              <rect className="hit" x={m.left + band * i} y={0} width={band} height={height} />
            </g>
          ))}
          <text className="tick" x={m.left} y={height - 7}>
            {compact(bins[0].low)}
          </text>
          <text className="tick" x={width - m.right} y={height - 7} textAnchor="end">
            {compact(bins[bins.length - 1].high)}
          </text>
        </svg>
      )}
      <Tooltip
        width={width}
        tip={
          bin && active !== null
            ? {
                x: m.left + band * active,
                y: y(bin.rows),
                title: `${compact(bin.low)} to ${compact(bin.high)}`,
                lines: [`${bin.rows.toLocaleString("en-US")} rows`],
              }
            : null
        }
      />
    </div>
  );
}

export function RankedBars({
  bars,
  selected,
  onPick,
}: {
  bars: Bar[];
  selected?: string;
  onPick: (bar: Bar) => void;
}) {
  const widest = Math.max(...bars.map((bar) => Math.abs(toNumber(bar.value) ?? 0)), Number.MIN_VALUE);
  return (
    <div className={`bars${selected ? " has-selection" : ""}`}>
      {bars.map((bar) => (
        <button
          key={bar.key}
          type="button"
          className="bar"
          aria-pressed={selected === bar.key}
          title={`${bar.label}: ${bar.rows.toLocaleString("en-US")} rows. Select to filter.`}
          onClick={() => onPick(bar)}
        >
          <span className="bar-label">{bar.label}</span>
          <span className="bar-track">
            <span className="bar-fill" style={{ width: `${(Math.abs(toNumber(bar.value) ?? 0) / widest) * 100}%` }} />
          </span>
          <span className="bar-value">{compact(bar.value)}</span>
        </button>
      ))}
    </div>
  );
}
