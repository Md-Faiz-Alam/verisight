import { useEffect, useRef, useState } from "react";
import { exact, post } from "./lib";
import { DataTable, Icon, Sql, Trail, TrustBadge, TRUST } from "./ui";
import type { Answer, Cell, Config, Dataset, Turn } from "./types";

const FAILURES: Record<string, string> = {
  provider_unavailable: "Gemini was busy or unavailable. Wait a minute and ask again.",
  provider_error: "Gemini returned an error. Try again or rephrase the question.",
  prompt_budget_exceeded: "This dataset is too large to describe in one request. Try narrower files.",
  synthesis_error: "The model's answer could not be matched to the SQL results.",
  measure_not_in_data: "The data does not appear to hold what was asked, so no number is shown.",
};

function failureText(answer: Answer): string {
  const kind = answer.failure?.kind;
  if (kind && FAILURES[kind]) return FAILURES[kind];
  if (answer.status === "incomplete") return "VeriSight could not finish with a number it can check, so it does not show one.";
  if (answer.status === "complete" && !answer.claims?.length) {
    return "No number was given. The answer above explains why.";
  }
  const level = answer.trust?.level;
  return level ? TRUST[level].note : "This answer could not be checked.";
}

function headline(answer: Answer) {
  const verification = answer.claims?.[0]?.verification;
  return answer.outcome === "verified" && answer.claims?.length === 1 ? (verification?.actual ?? null) : null;
}

/** The cell that holds the answer; a result often lists the parts first. */
function citedCell(step: { columns: string[]; rows: Cell[][] }, value: string | number | null) {
  if (value === null || step.rows.length !== 1) return undefined;
  const column = step.rows[0].findIndex((cell) => cell !== null && String(cell) === String(value));
  return column >= 0 ? ([0, column] as [number, number]) : undefined;
}

function Evidence({ turn }: { turn: Turn | null }) {
  const answer = turn?.answer;
  if (!turn || !answer || answer.outcome === "clarify") {
    return (
      <aside className="evidence empty">
        <h2>Evidence</h2>
        <p>Select an answer to see how it was reached and what was checked.</p>
      </aside>
    );
  }
  const level = answer.trust?.level;
  const value = headline(answer);
  return (
    <aside className="evidence" aria-label="Evidence for the selected answer">
      <h2>Evidence</h2>
      {level && <p className="evidence-note">{TRUST[level].note}</p>}
      {answer.trust && <Trail key={turn.id} checks={answer.trust.checks} />}
      {answer.steps?.map((step, index) => (
        <section key={index}>
          <h3>{answer.steps!.length > 1 ? `Query ${index + 1}` : "Query"}</h3>
          <Sql sql={step.sql} />
          {step.columns.length > 0 && (
            <DataTable columns={step.columns} rows={step.rows} highlight={citedCell(step, value)} />
          )}
        </section>
      ))}
      {answer.cross_check?.sql && (
        <section>
          <h3>Independent second query</h3>
          <Sql sql={answer.cross_check.sql} />
        </section>
      )}
      <p className="evidence-meta">
        {answer.elapsed_seconds}s
        {answer.model_calls?.length ? ` · ${answer.model_calls.length} model calls` : " · no AI used"}
      </p>
    </aside>
  );
}

function Pending() {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const started = Date.now();
    const timer = setInterval(() => setSeconds(Math.round((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  }, []);
  return (
    <div className="thinking">
      <span className="spinner" />
      Working and checking · {seconds}s
    </div>
  );
}

function AnswerBody({
  turn,
  onAsk,
  onAllow,
}: {
  turn: Turn;
  onAsk: (text: string) => void;
  onAllow: (turn: Turn) => void;
}) {
  if (turn.error) {
    if (turn.error.code === "consent_required") {
      return (
        <div className="notice">
          <p>This question needs AI, which means sending the schema, profile, question and sample values to Google Gemini.</p>
          <button type="button" className="btn small" onClick={() => onAllow(turn)}>
            Allow and ask
          </button>
        </div>
      );
    }
    return <p className="notice bad">{turn.error.message}</p>;
  }
  const answer = turn.answer;
  if (!answer) return <Pending />;
  if (answer.outcome === "clarify") {
    return (
      <div>
        <p className="answer-text">{answer.answer}</p>
        <div className="chips">
          {answer.options?.map((option) => (
            <button key={option} type="button" className="chip" onClick={() => onAsk(option)}>
              {option}
            </button>
          ))}
        </div>
      </div>
    );
  }
  const value = headline(answer);
  return (
    <div>
      <div className="answer-top">{answer.trust && <TrustBadge level={answer.trust.level} />}</div>
      {value !== null && <div className="answer-num">{exact(value)}</div>}
      <p className={value === null ? "answer-text muted" : "answer-text"}>{answer.answer}</p>
      {answer.outcome !== "verified" && answer.trust?.level !== "needs_review" && (
        <p className="notice warn">{failureText(answer)}</p>
      )}
    </div>
  );
}

export function Ask({
  dataset,
  config,
  turns,
  setTurns,
  suggestions,
  draft,
  onDraftUsed,
}: {
  dataset: Dataset;
  config: Config | null;
  turns: Turn[];
  setTurns: (update: (turns: Turn[]) => Turn[]) => void;
  suggestions: string[];
  draft: string | null;
  onDraftUsed: () => void;
}) {
  const [text, setText] = useState("");
  const [type, setType] = useState<Turn["type"]>("number");
  const [consent, setConsent] = useState(false);
  const [key, setKey] = useState("");
  const [selected, setSelected] = useState<number | null>(null);
  const counter = useRef(0);
  const end = useRef<HTMLDivElement>(null);

  const send = async (question: string, allow = consent, kind = type) => {
    const clean = question.trim();
    if (!clean) return;
    const id = ++counter.current;
    setTurns((all) => [...all, { id, question: clean, type: kind }]);
    setSelected(id);
    setText("");
    try {
      const answer = await post<Answer>(`/api/datasets/${dataset.dataset_id}/ask`, {
        question: clean,
        answer_type: kind,
        consent: allow,
        api_key: key.trim() || null,
      });
      setTurns((all) => all.map((t) => (t.id === id ? { ...t, answer } : t)));
    } catch (err: any) {
      setTurns((all) => all.map((t) => (t.id === id ? { ...t, error: { message: err.message, code: err.code } } : t)));
    }
  };

  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns.length]);

  useEffect(() => {
    if (draft) {
      onDraftUsed();
      send(draft);
    }
    // Only a new draft should send.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft]);

  const current = turns.find((t) => t.id === selected) ?? turns[turns.length - 1] ?? null;
  const needsKey = config && !config.server_key;
  return (
    <div className="ask">
      <div className="thread">
        <div className="turns">
          {turns.length === 0 && (
            <div className="ask-empty">
              <h2>Ask about your data</h2>
              <p>Plain questions are answered by fixed rules, with no AI and no key. Harder ones use AI and are checked.</p>
              <div className="chips">
                {suggestions.map((s) => (
                  <button key={s} type="button" className="chip" onClick={() => send(s)}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}
          {turns.map((turn) => (
            <article key={turn.id} className={`turn${current?.id === turn.id ? " on" : ""}`} onClick={() => setSelected(turn.id)}>
              <p className="turn-q">{turn.question}</p>
              <AnswerBody
                turn={turn}
                onAsk={(option) => send(option)}
                onAllow={(t) => {
                  setConsent(true);
                  setTurns((all) => all.filter((x) => x.id !== t.id));
                  send(t.question, true, t.type);
                }}
              />
            </article>
          ))}
          <div ref={end} />
        </div>
        <form
          className="composer"
          onSubmit={(event) => {
            event.preventDefault();
            send(text);
          }}
        >
          <textarea
            aria-label="Your question"
            rows={2}
            maxLength={1000}
            placeholder="Ask a question about your data"
            value={text}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                send(text);
              }
            }}
          />
          <div className="composer-row">
            <div className="seg small" role="group" aria-label="Answer type">
              {(
                [
                  ["number", "One number"],
                  ["difference", "Difference"],
                  ["any", "Anything"],
                ] as const
              ).map(([value, label]) => (
                <button key={value} type="button" aria-pressed={type === value} onClick={() => setType(value)}>
                  {label}
                </button>
              ))}
            </div>
            <label className="consent">
              <input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} />
              Allow AI for harder questions
            </label>
            {needsKey && (
              <input
                className="key"
                type="password"
                aria-label="Gemini API key"
                placeholder="Gemini key, used once"
                autoComplete="off"
                spellCheck={false}
                value={key}
                onChange={(event) => setKey(event.target.value)}
              />
            )}
            <button type="submit" className="btn primary send" disabled={!text.trim()} aria-label="Send question">
              <Icon name="send" />
            </button>
          </div>
        </form>
      </div>
      <Evidence turn={current} />
    </div>
  );
}
