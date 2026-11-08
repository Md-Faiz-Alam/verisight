import type { Cell } from "./types";

export class ApiError extends Error {
  code?: string;
  constructor(message: string, code?: string) {
    super(message);
    this.code = code;
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new ApiError("Could not reach the VeriSight server. Check your connection.");
  }
  if (response.status === 204) return undefined as T;
  let body: any = null;
  try {
    body = await response.json();
  } catch {
    /* a non-JSON error page */
  }
  if (!response.ok) {
    const detail = body && (body.message ? body : body.detail);
    throw new ApiError(
      typeof detail?.message === "string"
        ? detail.message
        : `The request failed (HTTP ${response.status}).`,
      detail?.code,
    );
  }
  return body as T;
}

export function post<T>(path: string, body: unknown): Promise<T> {
  return api<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function toNumber(value: Cell | undefined): number | null {
  const number = typeof value === "number" ? value : Number(value);
  return value !== null && value !== "" && Number.isFinite(number) ? number : null;
}

/** Figures stay in full below 10,000, then shorten. */
export function compact(value: Cell | undefined): string {
  const number = toNumber(value);
  if (number === null) return "–";
  const size = Math.abs(number);
  const scale = (
    [
      [1e12, "T", 1e12],
      [1e9, "B", 1e9],
      [1e6, "M", 1e6],
      [1e3, "K", 1e4],
    ] as const
  ).find(([, , from]) => size >= from);
  if (scale) {
    const scaled = number / scale[0];
    return `${scaled.toFixed(Math.abs(scaled) >= 100 ? 0 : 1).replace(/\.0$/, "")}${scale[1]}`;
  }
  const digits = size >= 100 || Number.isInteger(number) ? 0 : size >= 1 ? 2 : 3;
  return number.toLocaleString("en-US", { maximumFractionDigits: digits });
}

const PLAIN = /^([+-]?)(\d+)(\.\d+)?$/;

/** Digits are grouped, never rounded, so a shown value can be traced to its cell. */
export function exact(value: Cell | undefined): string {
  if (value === null || value === undefined) return "";
  const text = String(value);
  const match = PLAIN.exec(text);
  if (!match || (match[2].length > 1 && match[2].startsWith("0"))) return text;
  return `${match[1]}${BigInt(match[2]).toLocaleString("en-US")}${match[3] ?? ""}`;
}

export function cellText(value: Cell): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "number") return exact(value);
  return String(value).replace(/^(\d{4}-\d{2}-\d{2})T00:00:00$/, "$1");
}

/** A raw table cell: IDs and years must not gain thousands separators. */
export function rawText(value: Cell): string {
  return typeof value === "number" ? String(value) : cellText(value);
}

export function percent(ratio: number | null | undefined): string {
  if (typeof ratio !== "number") return "";
  if (ratio > 0 && ratio < 0.001) return "<0.1%";
  return `${(ratio * 100).toFixed(ratio < 0.1 ? 1 : 0)}%`;
}

export function readable(name: string): string {
  return name.replace(/_/g, " ");
}

export function downloadCsv(name: string, header: string[], rows: Cell[][]): void {
  const escape = (cell: Cell) => {
    const text = cell === null || cell === undefined ? "" : String(cell);
    // A leading = + - @ would run as a formula when opened in a spreadsheet.
    const safe = /^[=+\-@\t\r]/.test(text) && Number.isNaN(Number(text)) ? `'${text}` : text;
    return /[",\n\r]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
  };
  const text = [header, ...rows].map((row) => row.map(escape).join(",")).join("\r\n");
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `${name.replace(/[^\w-]+/g, "_").toLowerCase()}.csv`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function storedTheme(): string | null {
  try {
    return localStorage.getItem("verisight-theme");
  } catch {
    return null;
  }
}

export function saveTheme(theme: string): void {
  try {
    localStorage.setItem("verisight-theme", theme);
  } catch {
    /* private mode */
  }
}
