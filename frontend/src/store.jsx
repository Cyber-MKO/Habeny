import React, { createContext, useContext, useReducer, useCallback } from "react";

const Ctx = createContext();

const initial = {
  toasts: [],
  agents: [],
  agentsStats: null,
  health: null,
  simulations: [],
  groups: [],
  siemStats: {},
};

function reducer(state, action) {
  switch (action.type) {
    case "SET":
      return { ...state, [action.key]: action.value };
    case "TOAST": {
      const id = Date.now();
      return { ...state, toasts: [...state.toasts, { id, ...action.payload }] };
    }
    case "DISMISS_TOAST":
      return { ...state, toasts: state.toasts.filter((t) => t.id !== action.id) };
    default:
      return state;
  }
}

export function AppProvider({ children }) {
  const [state, dispatch] = useReducer(reducer, initial);

  const set = useCallback((key, value) => dispatch({ type: "SET", key, value }), []);
  const toast = useCallback(
    (message, variant = "info") => {
      const id = Date.now();
      dispatch({ type: "TOAST", payload: { message, variant } });
      setTimeout(() => dispatch({ type: "DISMISS_TOAST", id }), 5000);
    },
    []
  );
  const dismissToast = useCallback((id) => dispatch({ type: "DISMISS_TOAST", id }), []);

  return (
    <Ctx.Provider value={{ ...state, set, toast, dismissToast }}>
      {children}
    </Ctx.Provider>
  );
}

export const useStore = () => useContext(Ctx);
