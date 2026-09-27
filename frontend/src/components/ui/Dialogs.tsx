import { createContext, useCallback, useContext, useId, useMemo, useRef, useState, type ReactNode } from 'react';
import { Modal } from '../common/Modal';

/**
 * In-app replacements for `window.confirm` and `window.prompt`.
 *
 * The browser's own dialogs are the one piece of the app that cannot be
 * styled: a grey system sheet reading "localhost:8000 says…" dropped over a
 * neon UI, blocking the page's JavaScript while it is up. They also cannot
 * explain themselves — no title, no way to mark the destructive button as
 * destructive — and iOS standalone PWAs suppress them entirely after a few
 * appearances ("Prevent this page from creating additional dialogs").
 *
 * Promise-shaped on purpose, so a call site changes from
 *   `if (confirm('Remove?')) remove()`
 * to
 *   `if (await confirm({ title: 'Remove?' })) remove()`
 * and keeps its control flow.
 */
export interface ConfirmOptions {
  title: ReactNode;
  /** Optional detail under the title: consequences, what is kept. */
  body?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  /** `danger` styles the confirm button as destructive. */
  tone?: 'default' | 'danger';
}

export interface PromptOptions {
  title: ReactNode;
  body?: ReactNode;
  /** Visible label for the text field. */
  label: string;
  defaultValue?: string;
  placeholder?: string;
  confirmLabel?: string;
}

type Request =
  | { kind: 'confirm'; options: ConfirmOptions; resolve: (ok: boolean) => void }
  | { kind: 'prompt'; options: PromptOptions; resolve: (value: string | null) => void };

interface DialogApi {
  confirm: (options: ConfirmOptions) => Promise<boolean>;
  prompt: (options: PromptOptions) => Promise<string | null>;
}

const DialogContext = createContext<DialogApi | null>(null);

/**
 * Outside a provider these fall back to the browser's dialogs, so a component
 * rendered bare (an isolated unit test, a future page mounted outside the app
 * root) still asks before it destroys anything. Asking in the wrong style is
 * a cosmetic bug; not asking is a data-loss one.
 */
const FALLBACK: DialogApi = {
  confirm: async o => window.confirm(plain(o.title)),
  prompt: async o => window.prompt(plain(o.title), o.defaultValue),
};

function plain(node: ReactNode): string {
  return typeof node === 'string' || typeof node === 'number' ? String(node) : '';
}

export function useConfirm() {
  return (useContext(DialogContext) ?? FALLBACK).confirm;
}

export function usePrompt() {
  return (useContext(DialogContext) ?? FALLBACK).prompt;
}

export function DialogProvider({ children }: { children: ReactNode }) {
  const [request, setRequest] = useState<Request | null>(null);
  // A second request while one is open cancels the first rather than
  // stacking two modals; in practice it cannot happen (the first is modal).
  const pending = useRef<Request | null>(null);

  const open = useCallback((next: Request) => {
    const prev = pending.current;
    if (prev) {
      if (prev.kind === 'confirm') prev.resolve(false);
      else prev.resolve(null);
    }
    pending.current = next;
    setRequest(next);
  }, []);

  const api = useMemo<DialogApi>(() => ({
    confirm: options => new Promise<boolean>(resolve => open({ kind: 'confirm', options, resolve })),
    prompt: options => new Promise<string | null>(resolve => open({ kind: 'prompt', options, resolve })),
  }), [open]);

  const settle = useCallback((value: boolean | string | null) => {
    const r = pending.current;
    pending.current = null;
    setRequest(null);
    if (!r) return;
    if (r.kind === 'confirm') r.resolve(value === true);
    else r.resolve(typeof value === 'string' ? value : null);
  }, []);

  return (
    <DialogContext.Provider value={api}>
      {children}
      {request?.kind === 'confirm' && (
        <ConfirmDialog options={request.options} onSettle={ok => settle(ok)} />
      )}
      {request?.kind === 'prompt' && (
        <PromptDialog options={request.options} onSettle={v => settle(v)} />
      )}
    </DialogContext.Provider>
  );
}

function ConfirmDialog({ options, onSettle }: { options: ConfirmOptions; onSettle: (ok: boolean) => void }) {
  const danger = options.tone === 'danger';
  const cancel = useCallback(() => onSettle(false), [onSettle]);
  return (
    <Modal
      title={options.title}
      onClose={cancel}
      maxWidth={420}
      footer={
        <>
          {/* Destructive: focus starts on Cancel, so a reflexive Enter is the
              safe answer. Otherwise it starts on the action. */}
          <button
            type="button"
            className="btn btn-outline-secondary"
            onClick={cancel}
            data-autofocus={danger ? '' : undefined}
          >
            {options.cancelLabel ?? 'Cancel'}
          </button>
          <button
            type="button"
            className={`btn ${danger ? 'btn-danger' : 'btn-primary'}`}
            onClick={() => onSettle(true)}
            data-autofocus={danger ? undefined : ''}
          >
            {options.confirmLabel ?? (danger ? 'Delete' : 'Confirm')}
          </button>
        </>
      }
    >
      {options.body
        ? <div className="text-secondary hr-dialog-body">{options.body}</div>
        : <p className="text-secondary mb-0 hr-dialog-body">This can’t be undone.</p>}
    </Modal>
  );
}

function PromptDialog({ options, onSettle }: { options: PromptOptions; onSettle: (value: string | null) => void }) {
  const [value, setValue] = useState(options.defaultValue ?? '');
  const inputId = useId();
  const cancel = useCallback(() => onSettle(null), [onSettle]);
  return (
    <Modal
      title={options.title}
      onClose={cancel}
      maxWidth={420}
      footer={
        <>
          <button type="button" className="btn btn-outline-secondary" onClick={cancel}>Cancel</button>
          <button type="submit" form={`${inputId}-form`} className="btn btn-primary">
            {options.confirmLabel ?? 'OK'}
          </button>
        </>
      }
    >
      <form
        id={`${inputId}-form`}
        onSubmit={e => { e.preventDefault(); onSettle(value); }}
      >
        {options.body && <div className="text-secondary mb-3 hr-dialog-body">{options.body}</div>}
        <label className="form-label" htmlFor={inputId}>{options.label}</label>
        <input
          id={inputId}
          className="form-control"
          value={value}
          placeholder={options.placeholder}
          onChange={e => setValue(e.target.value)}
          autoComplete="off"
          data-autofocus=""
        />
      </form>
    </Modal>
  );
}
