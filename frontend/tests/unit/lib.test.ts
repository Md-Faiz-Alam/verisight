import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, cellText, compact, downloadCsv, exact, percent, rawText, toNumber } from "../../src/lib";

afterEach(() => vi.unstubAllGlobals());

describe("exact", () => {
  it.each([
    [1234567.891, "1,234,567.891"],
    ["12345678901234567.123456", "12,345,678,901,234,567.123456"],
    ["-2194.172782", "-2,194.172782"],
    [0.000123, "0.000123"],
    ["007", "007"],
    ["1e+21", "1e+21"],
    ["n/a", "n/a"],
    [null, ""],
    [undefined, ""],
  ])("shows %s as %s without rounding", (value, shown) => {
    expect(exact(value as never)).toBe(shown);
  });
});

describe("compact", () => {
  it.each([
    [9999, "9,999"],
    [12345, "12.3K"],
    [123456, "123K"],
    [2_500_000, "2.5M"],
    [3e9, "3B"],
    [4.2e12, "4.2T"],
    [12.345, "12.35"],
    [0.12345, "0.123"],
    [-15000, "-15K"],
    ["", "–"],
    [null, "–"],
    ["text", "–"],
  ])("shortens %s to %s", (value, shown) => {
    expect(compact(value as never)).toBe(shown);
  });
});

describe("cells", () => {
  it("keeps identifiers and years free of separators in raw tables", () => {
    expect(rawText(2024)).toBe("2024");
    expect(rawText(10001)).toBe("10001");
    expect(cellText(10001)).toBe("10,001");
  });

  it("shows a midnight timestamp as a plain date", () => {
    expect(cellText("2024-03-01T00:00:00")).toBe("2024-03-01");
    expect(cellText("2024-03-01T10:30:00")).toBe("2024-03-01T10:30:00");
  });

  it("reads numbers only from real numbers", () => {
    expect(toNumber("12.5")).toBe(12.5);
    expect(toNumber("")).toBeNull();
    expect(toNumber(null)).toBeNull();
    expect(toNumber("abc")).toBeNull();
  });

  it("shows shares as percentages", () => {
    expect(percent(0.0004)).toBe("<0.1%");
    expect(percent(0.054)).toBe("5.4%");
    expect(percent(0.5)).toBe("50%");
    expect(percent(null)).toBe("");
  });
});

describe("api", () => {
  it("returns the body of a good reply", async () => {
    vi.stubGlobal("fetch", async () => new Response(JSON.stringify({ ok: 1 }), { status: 200 }));
    await expect(api("/x")).resolves.toEqual({ ok: 1 });
  });

  it("keeps the server's message and code", async () => {
    const body = JSON.stringify({ code: "busy", message: "VeriSight is busy." });
    vi.stubGlobal("fetch", async () => new Response(body, { status: 503 }));
    await expect(api("/x")).rejects.toMatchObject({ message: "VeriSight is busy.", code: "busy" });
  });

  it("reads FastAPI's detail shape", async () => {
    const body = JSON.stringify({ detail: { code: "bad", message: "Bad input." } });
    vi.stubGlobal("fetch", async () => new Response(body, { status: 400 }));
    await expect(api("/x")).rejects.toMatchObject({ message: "Bad input.", code: "bad" });
  });

  it("explains a page that is not JSON", async () => {
    vi.stubGlobal("fetch", async () => new Response("<html>", { status: 502 }));
    await expect(api("/x")).rejects.toThrow("The request failed (HTTP 502).");
  });

  it("explains a lost connection", async () => {
    vi.stubGlobal("fetch", async () => {
      throw new TypeError("offline");
    });
    const error = await api("/x").catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).message).toContain("Could not reach");
  });

  it("returns nothing for an empty reply", async () => {
    vi.stubGlobal("fetch", async () => new Response(null, { status: 204 }));
    await expect(api("/x")).resolves.toBeUndefined();
  });
});

describe("downloadCsv", () => {
  it("stops spreadsheet formulas and quotes awkward cells", async () => {
    const saved: Blob[] = [];
    const link = { href: "", download: "", click: vi.fn() };
    vi.stubGlobal("document", { createElement: () => link });
    vi.stubGlobal("URL", {
      createObjectURL: (blob: Blob) => {
        saved.push(blob);
        return "blob:x";
      },
      revokeObjectURL: vi.fn(),
    });
    vi.useFakeTimers();

    downloadCsv("My Report!", ["name", "note"], [
      ["=SUM(A1)", "a,b"],
      ["-5", 'say "hi"'],
      [null, "@cmd"],
    ]);
    vi.runAllTimers();
    vi.useRealTimers();

    expect(link.download).toBe("my_report_.csv");
    expect(link.click).toHaveBeenCalled();
    expect(await saved[0].text()).toBe(
      ["name,note", "'=SUM(A1),\"a,b\"", '-5,"say ""hi"""', ",'@cmd"].join("\r\n"),
    );
  });
});
