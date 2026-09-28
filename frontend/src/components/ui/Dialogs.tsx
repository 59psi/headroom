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

type RequestBody =
  | { kind: 'confirm'; options: ConfirmOptions; resolve: (ok: boolean) => void }
  | { kind: 'prompt'; options: PromptOptions; resolve: (value: string | null) => void };

/**
 * `id` keys the rendered dialog. Two requests of the same kind render the
 * same component at the same spot, so without a key React keeps the first
 * one's instance for the second — and a prompt opened over another prompt
 * showed the first one's half-typed text instead of its own default.
 */
type Request = RequestBody & { id: number };

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
 *
 * The message carries the body too: call sites moved their warning text
 * ("Its hats become unassigned") out of `window.confirm('…')` and into
 * `body`, and a fallback that sent only the title asked the bare question
 * without the consequences it used to state. A title that is markup (no
 * text to extract without rendering) still asks something, never a blank.
 */
const FALLBACK: DialogApi = {
  confirm: async o => window.confirm(message(o.title, o.body) || 'Are you sure?'),
  prompt: async o => window.prompt(message(o.title, o.body) || o.label, o.defaultValue),
};

function message(title: ReactNode, body: ReactNode): string {
  return [plain(title), plain(body)].filter(Boolean).join('\n\n');
}

/** The text of a string-ish node; '' for elements, which need a render to read. */
function plain(node: ReactNode): string {
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  // `{'Delete '}{name}{'?'}` arrives as an array of strings.
  if (Array.isArray(node)) return node.map(plain).join('');
  return '';
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
  const seq = useRef(0);

  const open = useCallback((body: RequestBody) => {
    const prev = pending.current;
    if (prev) {
      if (prev.kind === 'confirm') prev.resolve(false);
      else prev.resolve(null);
    }
    const next: Request = { ...body, id: ++seq.current };
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

  // `settle` itself, never a fresh arrow per render: the dialogs derive
  // their close handler from it and the modal's focus effect keys on that
  // handler, so a new identity on any provider re-render re-ran the effect
  // and threw focus back to the autofocus button — off the destructive
  // action the person had deliberately tabbed to, onto Cancel.
  return (
    <DialogContext.Provider value={api}>
      {children}
      {request?.kind === 'confirm' && (
        <ConfirmDialog key={request.id} options={request.options} onSettle={settle} />
      )}
      {request?.kind === 'prompt' && (
        <PromptDialog key={request.id} options={request.options} onSettle={settle} />
      )}
    </DialogContext.Provider>
  );
}

function ConfirmDialog({ options, onSettle }: { options: ConfirmOptions; onSettle: (ok: boolean) => void }) {
  const danger = options.tone === 'danger';
  const cancel = useCallback(() => onSettle(false), [onSettle]);
  // "This can't be undone" is only true of a destructive action. Said under
  // every confirm, it told the person "Re-analyze every hat?" was
  // irreversible, and a warning on everything is a warning on nothing.
  const body = options.body ?? (danger ? 'This can’t be undone.' : null);
  return (
    <Modal
      title={options.title}
      onClose={cancel}
      maxWidth={420}
      // The body IS the message: read it with the title, or a screen reader
      // hears "Remove this key? Cancel" and never the consequences.
      describeBody={body !== null}
      alert={danger}
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
      {body !== null && <div className="text-secondary hr-dialog-body">{body}</div>}
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
