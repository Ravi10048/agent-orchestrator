import { create } from "zustand";

export type Theme = "dark" | "light";

function apply(theme: Theme) {
  const el = document.documentElement;
  el.classList.toggle("light", theme === "light"); // dark = no class (tokens on :root)
  el.style.colorScheme = theme;
}

const initial: Theme =
  (typeof localStorage !== "undefined" && (localStorage.getItem("theme") as Theme)) || "dark";
apply(initial);

export const useTheme = create<{ theme: Theme; toggle: () => void }>((set, get) => ({
  theme: initial,
  toggle: () => {
    const next: Theme = get().theme === "dark" ? "light" : "dark";
    try {
      localStorage.setItem("theme", next);
    } catch {
      /* ignore */
    }
    apply(next);
    set({ theme: next });
  },
}));
