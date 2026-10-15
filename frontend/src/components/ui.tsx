import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { GUARD_LABEL, STATUS_LABEL, sourceLabel } from "../format";
import type { GuardStatus, OfferStatus, Source } from "../types";

// ------------------------------------------------------------------ icons
const PATHS: Record<string, string> = {
  overview: "M4 4h7v7H4zM13 4h7v4h-7zM13 10h7v10h-7zM4 13h7v7H4z",
  requests: "M7 4h10l3 3v13H4V4h3M8 11h8M8 15h8M8 7h4",
  suppliers: "M3 21V9l9-5 9 5v12M8 21v-6h8v6M3 21h18",
  activity: "M3 12h4l3-8 4 16 3-8h4",
  inbox: "M3 13h5l2 3h4l2-3h5M5 5h14l2 8v6H3v-6z",
  catalog: "M4 5h16v4H4zM4 11h16v8H4zM8 15h3",
  logout: "M15 4h4v16h-4M10 8l-4 4 4 4M6 12h10",
  plus: "M12 5v14M5 12h14",
  play: "M7 5l12 7-12 7z",
  next: "M5 5l8 7-8 7M15 5v14",
  close: "M6 6l12 12M18 6L6 18",
  chevron: "M9 6l6 6-6 6",
  user: "M12 12a4 4 0 100-8 4 4 0 000 8zM4 20c1.5-4 4.5-6 8-6s6.5 2 8 6",
  shield: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z",
  phone: "M5 4h4l2 5-3 2a11 11 0 005 5l2-3 5 2v4a2 2 0 01-2 2A16 16 0 013 6a2 2 0 012-2",
  refresh: "M20 11a8 8 0 10-2 6M20 5v6h-6",
  hand: "M8 13V5a1.5 1.5 0 013 0v6M11 11V4a1.5 1.5 0 013 0v7M14 11V5.5a1.5 1.5 0 013 0V14c0 4-3 7-6.5 7S5 18 5 15v-3a1.5 1.5 0 013 0",
  bot: "M12 3v3M6 8h12v10H6zM9 12h.01M15 12h.01M9 16h6",
};

export function Icon({ name, size = 18 }: { name: keyof typeof PATHS | string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={PATHS[name] ?? ""} />
    </svg>
  );
}

// ------------------------------------------------------------------ badges
type Tone = "neutral" | "ok" | "warn" | "err" | "info" | "accent" | "dark";

export function Badge({ tone = "neutral", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return <span className={`badge badge-${tone}`} title={title}>{children}</span>;
}

const SOURCE_TONE: Record<Source, Tone> = {
  engine: "neutral", seeded: "neutral", llm_agent: "info",
  human_seller: "dark", human_buyer: "dark", voice_confirmed: "accent",
};

export function SourceBadge({ source, voiceMode }: { source: Source; voiceMode?: string }) {
  return <Badge tone={SOURCE_TONE[source] ?? "neutral"} title="Who produced this number">{sourceLabel(source, voiceMode)}</Badge>;
}

const STATUS_TONE: Record<OfferStatus, Tone> = {
  proposed: "neutral", accepted: "ok", flagged: "warn", confirmed: "info", countered: "neutral", rejected: "err",
};

export function StatusBadge({ status }: { status: OfferStatus }) {
  return <Badge tone={STATUS_TONE[status] ?? "neutral"}>{STATUS_LABEL[status] ?? status}</Badge>;
}

const GUARD_TONE: Record<GuardStatus, Tone> = {
  ok: "ok", blocked: "err", flagged_outside_authority: "warn", override_confirmed: "info",
};

export function GuardBadge({ status }: { status?: GuardStatus }) {
  if (!status) return null;
  return (
    <Badge tone={GUARD_TONE[status]}>
      <Icon name="shield" size={12} /> {GUARD_LABEL[status]}
    </Badge>
  );
}

export function ControllerBadge({ controller }: { controller: string }) {
  return (
    <Badge tone={controller === "human" ? "dark" : "neutral"}>
      <Icon name={controller === "human" ? "user" : "bot"} size={12} />
      {controller === "human" ? "Human" : controller === "engine" ? "System" : "Agent"}
    </Badge>
  );
}

// ------------------------------------------------------------------ states
export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div className="state" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" /> {label}…
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="state state-error" role="alert">
      <span>{message}</span>
      {onRetry && <button className="btn btn-ghost btn-sm" onClick={onRetry}>Retry</button>}
    </div>
  );
}

export function Empty({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty">
      <strong>{title}</strong>
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}

// ------------------------------------------------------------------ layout bits
export function Card({ title, actions, children, className = "", subtitle }: {
  title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; subtitle?: ReactNode;
}) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <header className="card-head">
          <div>
            {title && <h2 className="card-title">{title}</h2>}
            {subtitle && <p className="card-sub">{subtitle}</p>}
          </div>
          {actions && <div className="card-actions">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange }: {
  tabs: { id: T; label: string; count?: number }[]; value: T; onChange: (id: T) => void;
}) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={value === t.id}
          className={`tab ${value === t.id ? "tab-on" : ""}`} onClick={() => onChange(t.id)}>
          {t.label}
          {t.count !== undefined && <span className="tab-count">{t.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function Drawer({ title, subtitle, onClose, children, wide }: {
  title: ReactNode; subtitle?: ReactNode; onClose: () => void; children: ReactNode; wide?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    ref.current?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`drawer ${wide ? "drawer-wide" : ""}`} role="dialog" aria-modal="true" tabIndex={-1} ref={ref}>
        <header className="drawer-head">
          <div>
            <h2>{title}</h2>
            {subtitle && <p className="muted">{subtitle}</p>}
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="Close"><Icon name="close" /></button>
        </header>
        <div className="drawer-body">{children}</div>
      </div>
    </div>
  );
}

export function KV({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="kv">
      {items.map(([k, v]) => (
        <div key={k}><dt>{k}</dt><dd>{v}</dd></div>
      ))}
    </dl>
  );
}

// ------------------------------------------------------------------ toasts
interface ToastMsg { id: number; tone: "ok" | "err" | "warn"; text: string }
const ToastContext = createContext<(tone: ToastMsg["tone"], text: string) => void>(() => undefined);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastMsg[]>([]);
  const push = useCallback((tone: ToastMsg["tone"], text: string) => {
    const id = Date.now() + Math.random();
    setItems((xs) => [...xs, { id, tone, text }]);
    window.setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== id)), 5200);
  }, []);
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="toasts" aria-live="polite">
        {items.map((t) => <div key={t.id} className={`toast toast-${t.tone}`}>{t.text}</div>)}
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);

/** Run an async action with a busy flag and a toast on failure. */
export function useAction() {
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const run = useCallback(async <T,>(key: string, fn: () => Promise<T>, okText?: string): Promise<T | undefined> => {
    setBusy(key);
    try {
      const out = await fn();
      if (okText) toast("ok", okText);
      return out;
    } catch (e) {
      toast("err", e instanceof Error ? e.message : "Action failed");
      return undefined;
    } finally {
      setBusy(null);
    }
  }, [toast]);
  return { busy, run };
}
