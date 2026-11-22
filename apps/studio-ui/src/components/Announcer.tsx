import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";

type Announce = (message: string) => void;

const AnnouncerContext = createContext<Announce>(() => {});

/** One visible, polite live region for confirmations ("Saved", "Archived"). */
export function AnnouncerProvider({ children }: { children: ReactNode }) {
  const [message, setMessage] = useState("");
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const announce = useCallback<Announce>((text) => {
    setMessage("");
    // Re-set on the next frame so identical messages are re-announced.
    requestAnimationFrame(() => setMessage(text));
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setMessage(""), 5000);
  }, []);

  useEffect(() => () => clearTimeout(timer.current), []);

  return (
    <AnnouncerContext.Provider value={announce}>
      {children}
      <div className="toast" role="status" aria-live="polite">
        {message}
      </div>
    </AnnouncerContext.Provider>
  );
}

export function useAnnounce(): Announce {
  return useContext(AnnouncerContext);
}
