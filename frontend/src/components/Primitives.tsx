import { useEffect, useRef, isValidElement, type ReactNode } from "react";
import { X, LoaderCircle } from "lucide-react";
import { useTranslation } from "react-i18next";
export function Spinner() {
  return <LoaderCircle size={17} className="spin" />;
}
export function Modal({
  title,
  children,
  onClose,
  wide = false,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  const { t } = useTranslation();
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  return (
    <dialog
      ref={dialog}
      className={"modal " + (wide ? "wide" : "")}
      onCancel={onClose}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <header>
        <h2>{title}</h2>
        <button
          className="icon-button"
          onClick={onClose}
          aria-label={t("close")}
        >
          <X size={20} />
        </button>
      </header>
      {children}
    </dialog>
  );
}
export function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  const isInput =
    isValidElement(children) &&
    ["input", "textarea", "select"].includes(String(children.type));
  return isInput ? (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
  ) : (
    <fieldset className="field">
      <legend>{label}</legend>
      {children}
    </fieldset>
  );
}
export function ErrorMessage({ error }: { error: unknown }) {
  return error ? (
    <div role="alert" className="error">
      {error instanceof Error ? error.message : String(error)}
    </div>
  ) : null;
}
export function Confirm({
  title,
  message,
  onConfirm,
  onClose,
  pending = false,
}: {
  title: string;
  message: string;
  onConfirm: () => void;
  onClose: () => void;
  pending?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <Modal title={title} onClose={onClose}>
      <p className="muted">{message}</p>
      <footer>
        <button className="button" onClick={onClose}>
          {t("cancel")}
        </button>
        <button
          className="button danger"
          disabled={pending}
          onClick={onConfirm}
        >
          {pending ? <Spinner /> : null}
          {t("confirm")}
        </button>
      </footer>
    </Modal>
  );
}
