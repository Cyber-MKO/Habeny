import { createContext, useCallback, useContext, useRef, useState } from "react";
import { Modal } from "./UI";
import { t } from "../i18n";

const ConfirmCtx = createContext(null);

// const confirm = useConfirm();
// if (!(await confirm({ title: "Delete group?", message: "…", confirmLabel: "Delete", danger: true }))) return;
export function ConfirmProvider({ children }) {
  const [request, setRequest] = useState(null);
  const [typed, setTyped] = useState("");
  const resolver = useRef(null);

  const confirm = useCallback((options) => new Promise((resolve) => {
    resolver.current?.(false); // a dialog already open counts as cancelled
    resolver.current = resolve;
    setTyped("");
    setRequest(typeof options === "string" ? { message: options } : options);
  }), []);

  const close = (answer) => {
    resolver.current?.(answer);
    resolver.current = null;
    setRequest(null);
  };

  const needsText = request?.requireText;
  return (
    <ConfirmCtx.Provider value={confirm}>
      {children}
      {request && (
        <Modal
          title={request.title || t("Are you sure?")}
          onClose={() => close(false)}
          footer={(
            <>
              <button type="button" className="btn btn-secondary" onClick={() => close(false)} data-autofocus={needsText ? undefined : ""}>
                {request.cancelLabel || t("Cancel")}
              </button>
              <button
                type="button"
                className={`btn ${request.danger ? "btn-danger" : "btn-primary"}`}
                onClick={() => close(true)}
                disabled={needsText && typed !== request.requireText}
              >
                {request.confirmLabel || t("Confirm")}
              </button>
            </>
          )}
        >
          {request.message && <p className="confirm-message">{request.message}</p>}
          {needsText && (
            <div className="field">
              <label htmlFor="confirm-text">{t("Type “{word}” to confirm", { word: request.requireText })}</label>
              <input id="confirm-text" className="input" value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" />
            </div>
          )}
        </Modal>
      )}
    </ConfirmCtx.Provider>
  );
}

export function useConfirm() {
  const confirm = useContext(ConfirmCtx);
  if (!confirm) throw new Error("useConfirm needs a ConfirmProvider");
  return confirm;
}
