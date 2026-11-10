import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Ask } from "./Ask";
import { Explore } from "./Explore";
import { Landing } from "./Landing";
import { Overview, useDashboard, type Selection } from "./Overview";
import { Model, Quality } from "./Quality";
import { api, saveTheme, storedTheme } from "./lib";
import { Icon } from "./ui";
import type { Config, Dataset, Turn, View } from "./types";

const NAV: [View, string][] = [
  ["overview", "Dashboard"],
  ["ask", "Ask"],
  ["explore", "Explore"],
  ["quality", "Quality"],
  ["model", "Model"],
];
const TITLES: Record<Exclude<View, "overview">, [string, string]> = {
  ask: ["Ask", "Every answer shows how far it was checked"],
  explore: ["Explore", "Your data as VeriSight read it"],
  quality: ["Quality", "What was changed, and what to look at"],
  model: ["Model", "How your tables connect"],
};
const EMPTY: Selection = { relation: null, filters: [], start: "", end: "" };

function toggleTheme() {
  const root = document.documentElement;
  const current = root.dataset.theme ?? (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  const next = current === "dark" ? "light" : "dark";
  root.dataset.theme = next;
  saveTheme(next);
}

interface Command {
  label: string;
  hint: string;
  run: () => void;
}

function Palette({ commands, onClose }: { commands: Command[]; onClose: () => void }) {
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => input.current?.focus(), []);
  const shown = commands.filter((c) => c.label.toLowerCase().includes(query.toLowerCase())).slice(0, 9);
  const run = (command?: Command) => {
    if (!command) return;
    onClose();
    command.run();
  };
  return (
    <div className="overlay" onMouseDown={onClose}>
      <div className="palette" role="dialog" aria-modal="true" aria-label="Command search" onMouseDown={(e) => e.stopPropagation()}>
        <label>
          <Icon name="search" />
          <input
            ref={input}
            placeholder="Search or ask…"
            aria-label="Search commands"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setIndex(0);
            }}
            onKeyDown={(event) => {
              if (event.key === "ArrowDown") {
                event.preventDefault();
                setIndex((i) => Math.min(shown.length - 1, i + 1));
              } else if (event.key === "ArrowUp") {
                event.preventDefault();
                setIndex((i) => Math.max(0, i - 1));
              } else if (event.key === "Enter") {
                run(shown[index]);
              } else if (event.key === "Escape") {
                onClose();
              }
            }}
          />
        </label>
        <ul role="listbox" aria-label="Commands">
          {shown.length === 0 && <li className="none">Nothing found</li>}
          {shown.map((command, i) => (
            <li key={command.label} role="option" aria-selected={i === index}>
              <button type="button" onMouseEnter={() => setIndex(i)} onClick={() => run(command)}>
                {command.label}
                <small>{command.hint}</small>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function Workspace({
  dataset,
  config,
  isDemo,
  onRemove,
}: {
  dataset: Dataset;
  config: Config | null;
  isDemo: boolean;
  onRemove: () => void;
}) {
  const [view, setView] = useState<View>("overview");
  const [selection, setSelection] = useState<Selection>(EMPTY);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState<string | null>(null);
  const [palette, setPalette] = useState(false);
  const { data, loading, error } = useDashboard(dataset, selection, onRemove);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPalette((open) => !open);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const suggestions = useMemo(
    () =>
      isDemo
        ? [
            "How many orders were shipped?",
            "What is the total Amount?",
            "What is the average qty?",
            "What is the total amount of orders placed by customers in the NA region?",
          ]
        : (data?.suggestions ?? []),
    [isDemo, data],
  );

  const ask = useCallback((question: string) => {
    setView("ask");
    setDraft(question);
  }, []);

  const commands: Command[] = [
    ...NAV.map(([key, label]) => ({ label: `Go to ${label}`, hint: "View", run: () => setView(key) })),
    ...(data?.relations ?? []).map((relation) => ({
      label: `Open table ${relation.name}`,
      hint: "Table",
      run: () => {
        setSelection({ ...EMPTY, relation: relation.name });
        setView("overview");
      },
    })),
    ...suggestions.map((question) => ({ label: question, hint: "Ask", run: () => ask(question) })),
    { label: "Clear filters", hint: "Action", run: () => setSelection({ ...selection, filters: [], start: "", end: "" }) },
    { label: "Switch theme", hint: "Action", run: toggleTheme },
    { label: "Print or save as PDF", hint: "Action", run: () => window.print() },
    { label: "Remove data", hint: "Action", run: onRemove },
  ];

  const title = view === "overview" ? [data?.domain.label ?? "Reading your data", data?.domain.focus ?? ""] : TITLES[view];
  const names = dataset.files.map((f) => f.name).join(", ");
  const findings = dataset.profile.quality_findings.filter((f) => f.issue_type !== "high_cardinality").length;
  return (
    <div className="app">
      <aside className="side no-print">
        <a className="brand" href="/">
          <img src="/static/favicon.svg" alt="" width={24} height={24} />
          VeriSight
        </a>
        <nav aria-label="Views">
          {NAV.map(([key, label]) => (
            <button key={key} type="button" aria-current={view === key ? "page" : undefined} onClick={() => setView(key)}>
              <Icon name={key} />
              <span>{label}</span>
              {key === "quality" && findings > 0 && <span className="count">{findings}</span>}
            </button>
          ))}
        </nav>
        {turns.length > 0 && (
          <section className="side-history">
            <h4>This session</h4>
            {turns
              .slice(-6)
              .reverse()
              .map((turn) => (
                <button key={turn.id} type="button" title={turn.question} onClick={() => setView("ask")}>
                  {turn.question}
                </button>
              ))}
          </section>
        )}
        <div className="side-foot">
          <div className="side-file">
            <b title={names}>{names}</b>
            <small>Deleted after {Math.round(dataset.expires_in_seconds / 60)} minutes</small>
          </div>
          <div className="side-actions">
            <button type="button" className="ghost-icon" onClick={toggleTheme} aria-label="Switch colour theme">
              <Icon name="moon" />
            </button>
            <button type="button" className="ghost-icon" onClick={onRemove} aria-label="Remove data">
              <Icon name="logout" />
            </button>
          </div>
        </div>
      </aside>
      <main className="main">
        <header className="top">
          <div>
            <h1>{title[0]}</h1>
            <p>
              {title[1]}
              {view === "overview" && data && data.domain.matched.length > 0 && (
                <span className="why"> · recognised from {data.domain.matched.join(", ")}</span>
              )}
            </p>
          </div>
          <div className="top-tools no-print">
            <button type="button" className="search-btn" onClick={() => setPalette(true)}>
              <Icon name="search" size={14} />
              <span>Search or ask</span>
              <kbd>Ctrl K</kbd>
            </button>
            {/* The sidebar's own buttons are hidden on narrow screens. */}
            <button type="button" className="ghost-icon phone-only" onClick={toggleTheme} aria-label="Switch colour theme">
              <Icon name="moon" />
            </button>
            <button type="button" className="ghost-icon phone-only" onClick={onRemove} aria-label="Remove data">
              <Icon name="logout" />
            </button>
            {view === "overview" && (
              <button type="button" className="btn small" onClick={() => window.print()}>
                <Icon name="download" size={13} /> PDF
              </button>
            )}
          </div>
        </header>
        <div className="content">
          {view === "overview" && (
            <Overview data={data} loading={loading} error={error} selection={selection} onSelect={setSelection} />
          )}
          <div hidden={view !== "ask"}>
            <Ask
              dataset={dataset}
              config={config}
              turns={turns}
              setTurns={setTurns}
              suggestions={suggestions}
              draft={draft}
              onDraftUsed={() => setDraft(null)}
            />
          </div>
          {view === "explore" && (
            <Explore dataset={dataset} initial={data?.relation ?? dataset.profile.schema.tables[0].relation_name} />
          )}
          {view === "quality" && <Quality dataset={dataset} />}
          {view === "model" && <Model dataset={dataset} links={data?.links ?? []} />}
        </div>
      </main>
      {palette && <Palette commands={commands} onClose={() => setPalette(false)} />}
    </div>
  );
}

export function App() {
  const [config, setConfig] = useState<Config | null>(null);
  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [isDemo, setIsDemo] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const theme = storedTheme();
    if (theme) document.documentElement.dataset.theme = theme;
    api<Config>("/api/config")
      .then(setConfig)
      .catch((err) => {
        setConfig({ server_key: false });
        setError(err.message);
      });
  }, []);

  const load = async (make: () => Promise<Dataset>, demo: boolean) => {
    setBusy(true);
    setError(null);
    try {
      setDataset(await make());
      setIsDemo(demo);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const upload = (files: FileList) => {
    const form = new FormData();
    Array.from(files).forEach((file) => form.append("files", file));
    load(() => api<Dataset>("/api/datasets", { method: "POST", body: form }), false);
  };

  const remove = () => {
    if (dataset) api(`/api/datasets/${dataset.dataset_id}`, { method: "DELETE" }).catch(() => undefined);
    setDataset(null);
  };

  if (!dataset) {
    return (
      <Landing
        config={config}
        busy={busy}
        error={error}
        onUpload={upload}
        onDemo={() => load(() => api<Dataset>("/api/datasets/demo", { method: "POST" }), true)}
        onTheme={toggleTheme}
      />
    );
  }
  return <Workspace key={dataset.dataset_id} dataset={dataset} config={config} isDemo={isDemo} onRemove={remove} />;
}
