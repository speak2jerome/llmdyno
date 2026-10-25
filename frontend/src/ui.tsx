// UI kit: every page builds from these so spacing, states and behaviour stay consistent.
import DOMPurify from "dompurify";
import hljs from "highlight.js/lib/common";
import { marked } from "marked";
import {
  AlertTriangle, Check, CheckCircle2, ChevronDown, ChevronUp, Copy, Info, Loader2, X, XCircle,
} from "lucide-react";
import React, { createContext, useCallback, useContext, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { cls } from "./format";

/* ------------------------------------------------------------------ buttons */
type BtnProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "danger" | "ghost" | "default" | "danger-solid";
  size?: "sm" | "xs" | "md";
  icon?: React.ReactNode;
  loading?: boolean;
  iconOnly?: boolean;
};
export function Button({ variant = "default", size = "md", icon, loading, iconOnly, className, children, disabled, ...rest }: BtnProps) {
  return (
    <button
      className={cls("btn", variant === "danger-solid" ? "danger solid" : variant !== "default" && variant, size !== "md" && size, iconOnly && "icon", className)}
      disabled={disabled || loading}
      {...rest}
    >
      {loading ? <Loader2 size={size === "md" ? 15 : 13} className="spin" /> : icon}
      {children}
    </button>
  );
}

export function Badge({ tone, children, dot, live, title, className }: { tone?: string; children: React.ReactNode; dot?: boolean; live?: boolean; title?: string; className?: string }) {
  return (
    <span className={cls("badge", tone, live && "live", className)} title={title}>
      {dot && <span className="dot" />}
      {children}
    </span>
  );
}

const STATUS_TONE: Record<string, string> = {
  done: "ok", ready: "ok", ok: "ok", running: "info", grading: "info", downloading: "info", building: "info", queued: "",
  paused: "warn", failed: "danger", cancelled: "", interrupted: "warn", missing: "", skipped: "", draft: "",
  waiting: "",
};
export function StatusBadge({ status, label }: { status: string; label?: string }) {
  const live = ["running", "grading", "downloading", "building"].includes(status);
  return (
    <Badge tone={STATUS_TONE[status] ?? ""} dot live={live}>
      {label || status.charAt(0).toUpperCase() + status.slice(1)}
    </Badge>
  );
}

export function Chip({ on, onClick, children, title }: { on?: boolean; onClick?: () => void; children: React.ReactNode; title?: string }) {
  return (
    <button type="button" className={cls("chip", on && "on")} onClick={onClick} title={title} aria-pressed={on}>
      {on && <Check size={13} />}
      {children}
    </button>
  );
}

/* ------------------------------------------------------------------ layout */
export function PageHead({ title, sub, actions, icon }: { title: React.ReactNode; sub?: React.ReactNode; actions?: React.ReactNode; icon?: React.ReactNode }) {
  return (
    <div className="page-head">
      <div>
        <h1 className="row" style={{ gap: 10 }}>
          {icon}
          {title}
        </h1>
        {sub && <div className="sub">{sub}</div>}
      </div>
      {actions && <div className="actions">{actions}</div>}
    </div>
  );
}

export function Card({ title, sub, actions, children, pad = true, className, onClick, selected, style, id }: {
  title?: React.ReactNode; sub?: React.ReactNode; actions?: React.ReactNode; children?: React.ReactNode; pad?: boolean;
  className?: string; onClick?: () => void; selected?: boolean; style?: React.CSSProperties; id?: string;
}) {
  return (
    <div id={id} className={cls("card", onClick && "clickable", selected && "selected", className)} onClick={onClick} style={style}>
      {(title || actions) && (
        <div className="card-head">
          <div style={{ minWidth: 0 }}>
            {typeof title === "string" ? <h3>{title}</h3> : title}
            {sub && <div className="sub">{sub}</div>}
          </div>
          {actions && <div className="actions" onClick={(e) => e.stopPropagation()}>{actions}</div>}
        </div>
      )}
      {children !== undefined && <div className={pad ? "card-body" : undefined}>{children}</div>}
    </div>
  );
}

export function Section({ title, sub, actions, children }: { title: string; sub?: React.ReactNode; actions?: React.ReactNode; children: React.ReactNode }) {
  return (
    <>
      <div className="section-title">
        <h2>{title}</h2>
        {sub && <span className="sub">{sub}</span>}
        {actions && <div style={{ marginLeft: "auto" }} className="row">{actions}</div>}
      </div>
      {children}
    </>
  );
}

export function Empty({ icon, title, children, action }: { icon?: React.ReactNode; title: string; children?: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="empty">
      {icon && <div className="ico">{icon}</div>}
      <h3>{title}</h3>
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}

export function Notice({ tone = "info", title, children, action }: { tone?: "info" | "warning" | "danger" | "ok"; title?: React.ReactNode; children?: React.ReactNode; action?: React.ReactNode }) {
  const Ico = tone === "danger" ? XCircle : tone === "warning" ? AlertTriangle : tone === "ok" ? CheckCircle2 : Info;
  return (
    <div className={cls("notice", tone !== "info" && tone)} role={tone === "danger" ? "alert" : undefined}>
      <Ico size={16} />
      <div style={{ minWidth: 0, flex: 1 }}>
        {title && <div style={{ fontWeight: 600 }}>{title}</div>}
        {children}
        {action && <div className="fix">{action}</div>}
      </div>
    </div>
  );
}

export function Skeleton({ h = 16, w = "100%", style }: { h?: number; w?: number | string; style?: React.CSSProperties }) {
  return <div className="skeleton" style={{ height: h, width: w, ...style }} />;
}

export function Spinner({ size = 16 }: { size?: number }) {
  return <Loader2 size={size} className="spin" style={{ animation: "spin .8s linear infinite" }} />;
}

export function Progress({ value, tone, indeterminate, style }: { value?: number; tone?: string; indeterminate?: boolean; style?: React.CSSProperties }) {
  return (
    <div className={cls("progress", tone, indeterminate && "indeterminate")} style={style} role="progressbar" aria-valuenow={value !== undefined ? Math.round(value * 100) : undefined}>
      <div style={{ width: `${Math.max(0, Math.min(1, value ?? 0)) * 100}%` }} />
    </div>
  );
}

export function Tip({ text, children }: { text: React.ReactNode; children: React.ReactNode }) {
  return (
    <span className="tip">
      {children}
      <span className="tip-body" role="tooltip">{text}</span>
    </span>
  );
}

export function InfoTip({ text }: { text: React.ReactNode }) {
  return (
    <Tip text={text}>
      <Info size={13} className="muted" style={{ cursor: "help" }} />
    </Tip>
  );
}

/* ------------------------------------------------------------------ forms */
/** The label id of the enclosing Field; inputs use it as their accessible name unless they have their own. */
const FieldLabel = createContext<string | undefined>(undefined);

export function Field({ label, hint, error, children, className, tip }: { label?: React.ReactNode; hint?: React.ReactNode; error?: string | null; children: React.ReactNode; className?: string; tip?: React.ReactNode }) {
  const id = useId();
  return (
    <div className={cls("field", className)}>
      {label && (
        <label>
          <span id={id}>{label}</span>
          {tip && <InfoTip text={tip} />}
        </label>
      )}
      <FieldLabel.Provider value={label ? id : undefined}>{children}</FieldLabel.Provider>
      {error ? <div className="error">{error}</div> : hint ? <div className="hint">{hint}</div> : null}
    </div>
  );
}

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement> & { invalid?: boolean }>(
  ({ className, invalid, ...p }, ref) => {
    const lid = useContext(FieldLabel);
    return <input ref={ref} className={cls("input", invalid && "invalid", className)} aria-labelledby={p["aria-label"] ? undefined : lid} {...p} />;
  },
);

export function NumInput({ value, onChange, min, max, step, placeholder, allowEmpty, suffix, ...rest }: {
  value: number | null | undefined; onChange: (v: number | null) => void; min?: number; max?: number; step?: number;
  placeholder?: string; allowEmpty?: boolean; suffix?: string; disabled?: boolean; "aria-label"?: string;
}) {
  const [text, setText] = useState(value === null || value === undefined ? "" : String(value));
  const lid = useContext(FieldLabel);
  useEffect(() => {
    setText(value === null || value === undefined ? "" : String(value));
  }, [value]);
  const commit = (t: string) => {
    if (t.trim() === "") {
      if (allowEmpty) onChange(null);
      else setText(value === null || value === undefined ? "" : String(value));
      return;
    }
    let v = Number(t);
    if (isNaN(v)) {
      setText(value === null || value === undefined ? "" : String(value));
      return;
    }
    if (min !== undefined) v = Math.max(min, v);
    if (max !== undefined) v = Math.min(max, v);
    onChange(v);
    setText(String(v));
  };
  const input = (
    <input className="input" inputMode="decimal" value={text} placeholder={placeholder} onChange={(e) => setText(e.target.value)}
      onBlur={(e) => commit(e.target.value)} onKeyDown={(e) => e.key === "Enter" && commit((e.target as HTMLInputElement).value)}
      step={step} disabled={rest.disabled} aria-label={rest["aria-label"]} aria-labelledby={rest["aria-label"] ? undefined : lid} />
  );
  if (!suffix) return input;
  return (
    <div className="input-group">
      {input}
      <span className="addon">{suffix}</span>
    </div>
  );
}

export function Select<T extends string | number>({ value, onChange, options, disabled, ...rest }: {
  value: T; onChange: (v: T) => void; options: { value: T; label: string; disabled?: boolean }[]; disabled?: boolean; "aria-label"?: string;
}) {
  const lid = useContext(FieldLabel);
  return (
    <select className="select" value={String(value)} disabled={disabled} aria-label={rest["aria-label"]} aria-labelledby={rest["aria-label"] ? undefined : lid}
      onChange={(e) => {
        const o = options.find((x) => String(x.value) === e.target.value);
        if (o) onChange(o.value);
      }}>
      {options.map((o) => (
        <option key={String(o.value)} value={String(o.value)} disabled={o.disabled}>{o.label}</option>
      ))}
    </select>
  );
}

export function Textarea(p: React.TextareaHTMLAttributes<HTMLTextAreaElement> & { code?: boolean }) {
  const { code, className, ...rest } = p;
  const lid = useContext(FieldLabel);
  return <textarea className={cls("textarea", code && "code", className)} spellCheck={!code} aria-labelledby={rest["aria-label"] ? undefined : lid} {...rest} />;
}

export function Toggle({ checked, onChange, label, disabled, title }: { checked: boolean; onChange: (v: boolean) => void; label?: React.ReactNode; disabled?: boolean; title?: string }) {
  const id = useId();
  return (
    <label className="toggle" title={title}>
      <input type="checkbox" role="switch" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)}
        aria-labelledby={label ? id : undefined} aria-label={label ? undefined : title} />
      <span className="track" />
      {label && <span id={id}>{label}</span>}
    </label>
  );
}

export function Checkbox({ checked, onChange, children, disabled }: { checked: boolean; onChange: (v: boolean) => void; children: React.ReactNode; disabled?: boolean }) {
  const id = useId();
  return (
    <label className="check">
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} aria-labelledby={id} />
      <span id={id}>{children}</span>
    </label>
  );
}

export function Segmented<T extends string>({ value, onChange, options }: { value: T; onChange: (v: T) => void; options: { value: T; label: React.ReactNode }[] }) {
  return (
    <div className="segmented" role="tablist">
      {options.map((o) => (
        <button type="button" key={o.value} className={cls(value === o.value && "on")} onClick={() => onChange(o.value)} role="tab" aria-selected={value === o.value}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Stepper({ value, onChange, min = 1, max = 99 }: { value: number; onChange: (v: number) => void; min?: number; max?: number }) {
  return (
    <div className="number-stepper">
      <button type="button" onClick={() => onChange(Math.max(min, value - 1))} aria-label="decrease" disabled={value <= min}>−</button>
      <input value={value} onChange={(e) => { const v = parseInt(e.target.value); if (!isNaN(v)) onChange(Math.max(min, Math.min(max, v))); }} aria-label="value" />
      <button type="button" onClick={() => onChange(Math.min(max, value + 1))} aria-label="increase" disabled={value >= max}>+</button>
    </div>
  );
}

export function Tabs<T extends string>({ value, onChange, tabs }: { value: T; onChange: (v: T) => void; tabs: { value: T; label: React.ReactNode; count?: number; icon?: React.ReactNode }[] }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => (
        <button key={t.value} className={cls(value === t.value && "on")} onClick={() => onChange(t.value)} role="tab" aria-selected={value === t.value}>
          {t.icon}
          {t.label}
          {t.count !== undefined && <span className="count">{t.count}</span>}
        </button>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ overlays */
function useEscape(onClose: () => void, active = true) {
  useEffect(() => {
    if (!active) return;
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose, active]);
}

export function Modal({ open, onClose, title, sub, children, footer, size }: {
  open: boolean; onClose: () => void; title: React.ReactNode; sub?: React.ReactNode; children: React.ReactNode; footer?: React.ReactNode; size?: "wide" | "xwide";
}) {
  useEscape(onClose, open);
  if (!open) return null;
  return createPortal(
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={cls("modal", size)} role="dialog" aria-modal="true">
        <div className="modal-head">
          <div style={{ flex: 1, minWidth: 0 }}>
            <h2>{title}</h2>
            {sub && <div className="sub">{sub}</div>}
          </div>
          <Button variant="ghost" size="sm" iconOnly icon={<X size={16} />} onClick={onClose} aria-label="Close" />
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}

export function Drawer({ open, onClose, title, sub, children, footer, wide, actions }: {
  open: boolean; onClose: () => void; title: React.ReactNode; sub?: React.ReactNode; children: React.ReactNode; footer?: React.ReactNode; wide?: boolean; actions?: React.ReactNode;
}) {
  useEscape(onClose, open);
  if (!open) return null;
  return createPortal(
    <>
      <div className="drawer-overlay" onClick={onClose} />
      <aside className={cls("drawer", wide && "wide")} role="dialog" aria-modal="true">
        <div className="drawer-head">
          <div style={{ flex: 1, minWidth: 0 }}>
            <h2 style={{ fontSize: 17 }}>{title}</h2>
            {sub && <div className="muted small mt-8" style={{ marginTop: 4 }}>{sub}</div>}
          </div>
          {actions}
          <Button variant="ghost" size="sm" iconOnly icon={<X size={16} />} onClick={onClose} aria-label="Close" />
        </div>
        <div className="drawer-body">{children}</div>
        {footer && <div className="drawer-foot">{footer}</div>}
      </aside>
    </>,
    document.body,
  );
}

type ConfirmOpts = { title: string; body?: React.ReactNode; confirm?: string; danger?: boolean; input?: { label: string; placeholder?: string; initial?: string } ; check?: string };
const ConfirmCtx = createContext<(o: ConfirmOpts) => Promise<{ ok: boolean; value?: string; checked?: boolean }>>(() => Promise.resolve({ ok: false }));
export const useConfirm = () => useContext(ConfirmCtx);

export function ConfirmProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<(ConfirmOpts & { resolve: (r: { ok: boolean; value?: string; checked?: boolean }) => void }) | null>(null);
  const [value, setValue] = useState("");
  const [checked, setChecked] = useState(false);
  const ask = useCallback((o: ConfirmOpts) => new Promise<{ ok: boolean; value?: string; checked?: boolean }>((resolve) => {
    setValue(o.input?.initial || "");
    setChecked(false);
    setState({ ...o, resolve });
  }), []);
  const close = (ok: boolean) => {
    state?.resolve({ ok, value, checked });
    setState(null);
  };
  return (
    <ConfirmCtx.Provider value={ask}>
      {children}
      <Modal open={!!state} onClose={() => close(false)} title={state?.title || ""}
        footer={<>
          <Button onClick={() => close(false)}>Cancel</Button>
          <Button variant={state?.danger ? "danger-solid" : "primary"} onClick={() => close(true)} disabled={!!state?.input && !value.trim()} autoFocus>
            {state?.confirm || "Confirm"}
          </Button>
        </>}>
        <div className="col" style={{ gap: 12 }}>
          {state?.body && <div className="text-2">{state.body}</div>}
          {state?.input && (
            <Field label={state.input.label}>
              <Input value={value} placeholder={state.input.placeholder} onChange={(e) => setValue(e.target.value)} autoFocus
                onKeyDown={(e) => e.key === "Enter" && value.trim() && close(true)} />
            </Field>
          )}
          {state?.check && <Checkbox checked={checked} onChange={setChecked}>{state.check}</Checkbox>}
        </div>
      </Modal>
    </ConfirmCtx.Provider>
  );
}

export function Menu({ trigger, items, align = "right" }: { trigger: (open: () => void) => React.ReactNode; items: ({ label: string; icon?: React.ReactNode; onClick: () => void; danger?: boolean; disabled?: boolean } | "sep")[]; align?: "left" | "right" }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<React.CSSProperties>({ visibility: "hidden" });
  const ref = useRef<HTMLDivElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const h = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    const close = () => setOpen(false);
    document.addEventListener("mousedown", h);
    window.addEventListener("resize", close);
    document.addEventListener("scroll", close, true);
    return () => {
      document.removeEventListener("mousedown", h);
      window.removeEventListener("resize", close);
      document.removeEventListener("scroll", close, true);
    };
  }, [open]);
  // fixed positioning escapes drawers and scroll containers; flip above the trigger when there is no room below
  useLayoutEffect(() => {
    if (!open || !ref.current || !menu.current) return;
    const t = ref.current.getBoundingClientRect();
    const h = menu.current.offsetHeight;
    const w = menu.current.offsetWidth;
    const below = window.innerHeight - t.bottom;
    const up = below < h + 12 && t.top > below;
    const left = align === "right" ? Math.max(8, t.right - w) : Math.min(t.left, window.innerWidth - w - 8);
    setPos(up ? { left, bottom: window.innerHeight - t.top + 4 } : { left, top: t.bottom + 4 });
    menu.current.querySelector<HTMLButtonElement>("button:not(:disabled)")?.focus();
  }, [open, align]);
  useEscape(() => setOpen(false), open);
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    const btns = [...(menu.current?.querySelectorAll<HTMLButtonElement>("button:not(:disabled)") || [])];
    const i = btns.indexOf(document.activeElement as HTMLButtonElement);
    btns[(i + (e.key === "ArrowDown" ? 1 : btns.length - 1)) % btns.length]?.focus();
  };
  return (
    <div ref={ref} style={{ position: "relative", display: "inline-flex" }} onClick={(e) => e.stopPropagation()}>
      {trigger(() => {
        setPos({ visibility: "hidden" });
        setOpen((o) => !o);
      })}
      {open && (
        <div ref={menu} className="menu" style={{ position: "fixed", ...pos }} role="menu" onKeyDown={onKey}>
          {items.map((it, i) => it === "sep" ? <hr key={i} /> : (
            <button key={i} className={cls(it.danger && "danger")} disabled={it.disabled} role="menuitem"
              onClick={() => { setOpen(false); it.onClick(); }} style={it.disabled ? { opacity: 0.45, cursor: "not-allowed" } : undefined}>
              {it.icon}
              {it.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ toasts */
type Toast = { id: number; tone: "ok" | "danger" | "warn" | "info"; title: string; body?: string };
const ToastCtx = createContext<{ push: (t: Omit<Toast, "id">) => void }>({ push: () => undefined });
export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((t: Omit<Toast, "id">) => {
    const id = Date.now() + Math.random();
    setItems((x) => [...x.slice(-4), { ...t, id }]);
    setTimeout(() => setItems((x) => x.filter((i) => i.id !== id)), t.tone === "danger" ? 9000 : 4500);
  }, []);
  const value = useMemo(() => ({ push }), [push]);
  return (
    <ToastCtx.Provider value={value}>
      {children}
      {createPortal(
        <div className="toasts" aria-live="polite">
          {items.map((t) => (
            <div key={t.id} className={cls("toast", t.tone)}>
              {t.tone === "ok" ? <CheckCircle2 size={17} className="ok" /> : t.tone === "danger" ? <XCircle size={17} className="danger" /> :
                t.tone === "warn" ? <AlertTriangle size={17} className="warn" /> : <Info size={17} className="info" />}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="t">{t.title}</div>
                {t.body && <div className="text-2" style={{ overflowWrap: "anywhere" }}>{t.body}</div>}
              </div>
              <button className="btn ghost xs icon" onClick={() => setItems((x) => x.filter((i) => i.id !== t.id))} aria-label="Dismiss"><X size={13} /></button>
            </div>
          ))}
        </div>,
        document.body,
      )}
    </ToastCtx.Provider>
  );
}
export function useToast() {
  const { push } = useContext(ToastCtx);
  return useMemo(() => ({
    ok: (title: string, body?: string) => push({ tone: "ok", title, body }),
    err: (title: string, body?: unknown) => push({ tone: "danger", title, body: body instanceof Error ? body.message : body ? String(body) : undefined }),
    warn: (title: string, body?: string) => push({ tone: "warn", title, body }),
    info: (title: string, body?: string) => push({ tone: "info", title, body }),
  }), [push]);
}

/** Wrap an async action with a busy flag and error toast. */
export function useAction<A extends any[], R>(fn: (...a: A) => Promise<R>, opts?: { ok?: string | ((r: R) => string); err?: string }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const run = useCallback(async (...a: A): Promise<R | undefined> => {
    setBusy(true);
    try {
      const r = await fn(...a);
      if (opts?.ok) toast.ok(typeof opts.ok === "function" ? opts.ok(r) : opts.ok);
      return r;
    } catch (e) {
      toast.err(opts?.err || "Something went wrong", e);
      return undefined;
    } finally {
      setBusy(false);
    }
  }, [fn, opts?.ok, opts?.err, toast]);
  return [run, busy] as const;
}

/* ------------------------------------------------------------------ table */
export type Col<T> = { key: string; label: React.ReactNode; render?: (r: T) => React.ReactNode; sort?: (r: T) => number | string | null | undefined; num?: boolean; width?: number | string; className?: string };
export function Table<T>({ rows, cols, onRow, initialSort, empty, rowKey, maxHeight }: {
  rows: T[]; cols: Col<T>[]; onRow?: (r: T) => void; initialSort?: { key: string; dir: 1 | -1 }; empty?: React.ReactNode; rowKey: (r: T) => string; maxHeight?: number;
}) {
  const [sort, setSort] = useState(initialSort);
  const sorted = useMemo(() => {
    if (!sort) return rows;
    const c = cols.find((x) => x.key === sort.key);
    if (!c?.sort) return rows;
    return [...rows].sort((a, b) => {
      const va = c.sort!(a), vb = c.sort!(b);
      if (va === vb) return 0;
      if (va === null || va === undefined) return 1;
      if (vb === null || vb === undefined) return -1;
      return (va < vb ? -1 : 1) * sort.dir;
    });
  }, [rows, cols, sort]);
  if (!rows.length && empty) return <>{empty}</>;
  return (
    <div className="table-wrap" style={maxHeight ? { maxHeight, overflowY: "auto" } : undefined}>
      <table className="table">
        <thead>
          <tr>
            {cols.map((c) => (
              <th key={c.key} className={cls(c.sort && "sortable", c.num && "num")} style={{ width: c.width }}
                onClick={() => c.sort && setSort((s) => ({ key: c.key, dir: s?.key === c.key ? (-s.dir as 1 | -1) : c.num ? -1 : 1 }))}
                aria-sort={sort?.key === c.key ? (sort.dir === 1 ? "ascending" : "descending") : undefined}>
                <span className="row" style={{ gap: 3, justifyContent: c.num ? "flex-end" : "flex-start", display: "inline-flex" }}>
                  {c.label}
                  {sort?.key === c.key && (sort.dir === 1 ? <ChevronUp size={12} /> : <ChevronDown size={12} />)}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => (
            <tr key={rowKey(r)} className={onRow ? "clickable" : undefined} onClick={onRow ? () => onRow(r) : undefined}>
              {cols.map((c) => (
                <td key={c.key} className={cls(c.num && "num", c.className)}>{c.render ? c.render(r) : (r as any)[c.key]}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ------------------------------------------------------------------ code & markdown */
marked.setOptions({ gfm: true, breaks: false });
export function Markdown({ text, className }: { text: string; className?: string }) {
  const html = useMemo(() => DOMPurify.sanitize(marked.parse(text || "", { async: false }) as string), [text]);
  return <div className={cls("md", className)} dangerouslySetInnerHTML={{ __html: html }} />;
}

const EXT_LANG: Record<string, string> = { py: "python", ts: "typescript", tsx: "typescript", js: "javascript", jsx: "javascript", json: "json", md: "markdown", html: "xml", css: "css", sh: "bash", toml: "ini", yml: "yaml", yaml: "yaml", sql: "sql", diff: "diff", txt: "plaintext", ini: "ini", cfg: "ini" };
export function langOf(path?: string) {
  const ext = (path || "").split(".").pop()?.toLowerCase() || "";
  return EXT_LANG[ext];
}
export function Code({ code, lang, path, wrap, maxHeight, lineNumbers }: { code: string; lang?: string; path?: string; wrap?: boolean; maxHeight?: number; lineNumbers?: boolean }) {
  const l = lang || langOf(path);
  const html = useMemo(() => {
    if (code.length > 300_000) return escapeHtml(code);
    try {
      return l && hljs.getLanguage(l) ? hljs.highlight(code, { language: l, ignoreIllegals: true }).value : escapeHtml(code);
    } catch {
      return escapeHtml(code);
    }
  }, [code, l]);
  const lines = lineNumbers ? code.split("\n").length : 0;
  return (
    <pre className={cls("code", wrap && "wrap")} style={maxHeight ? { maxHeight } : undefined}>
      {lineNumbers ? (
        <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: 12 }}>
          <span className="muted" style={{ textAlign: "right", userSelect: "none" }}>{Array.from({ length: lines }, (_, i) => i + 1).join("\n")}</span>
          <code style={{ background: "none", padding: 0 }} dangerouslySetInnerHTML={{ __html: html }} />
        </div>
      ) : <code style={{ background: "none", padding: 0 }} dangerouslySetInnerHTML={{ __html: html }} />}
    </pre>
  );
}
export function escapeHtml(s: string) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

export function CopyButton({ text, label }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <Button size="xs" variant="ghost" icon={done ? <Check size={12} /> : <Copy size={12} />}
      onClick={(e) => { e.stopPropagation(); navigator.clipboard?.writeText(text); setDone(true); setTimeout(() => setDone(false), 1200); }}>
      {label ?? (done ? "Copied" : "Copy")}
    </Button>
  );
}

export function KV({ items }: { items: [React.ReactNode, React.ReactNode][] }) {
  return (
    <dl className="kv">
      {items.map(([k, v], i) => (
        <React.Fragment key={i}>
          <dt>{k}</dt>
          <dd>{v}</dd>
        </React.Fragment>
      ))}
    </dl>
  );
}

export function Stat({ label, value, sub, tone }: { label: React.ReactNode; value: React.ReactNode; sub?: React.ReactNode; tone?: string }) {
  return (
    <div className="stat">
      <span className="k">{label}</span>
      <span className={cls("v", tone)}>{value}</span>
      {sub && <span className="s">{sub}</span>}
    </div>
  );
}

export function ScoreCell({ v, digits = 0 }: { v?: number | null; digits?: number }) {
  if (v === undefined || v === null) return <span className="muted">–</span>;
  return (
    <span className="score nowrap">
      {(v * 100).toFixed(digits)}
      <span className="score-bar"><i style={{ width: `${Math.max(0, Math.min(1, v)) * 100}%`, background: v >= 0.85 ? "var(--ok)" : v >= 0.65 ? "var(--accent)" : v >= 0.45 ? "var(--warn)" : "var(--danger)" }} /></span>
    </span>
  );
}
