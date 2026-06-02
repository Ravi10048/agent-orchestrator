import type { Config } from "tailwindcss";

// Linear-style dark design system. Semantic colors map to CSS variables (index.css).
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "hsl(var(--bg))",
        surface: "hsl(var(--surface))",
        card: "hsl(var(--card))",
        border: "hsl(var(--border))",
        "border-strong": "hsl(var(--border-strong))",
        fg: "hsl(var(--fg))",
        muted: "hsl(var(--muted))",
        primary: { DEFAULT: "hsl(var(--primary))", fg: "hsl(var(--primary-fg))" },
        success: "hsl(var(--success))",
        warning: "hsl(var(--warning))",
        destructive: "hsl(var(--destructive))",
        info: "hsl(var(--info))",
      },
      borderRadius: {
        xl: "calc(var(--radius) + 4px)",
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
      boxShadow: {
        soft: "0 1px 2px rgb(0 0 0 / 0.08), 0 2px 6px rgb(0 0 0 / 0.10)",
        pop: "0 16px 50px -12px rgb(0 0 0 / 0.45)",
        glow: "0 8px 24px -8px hsl(var(--primary) / 0.55)",
      },
      keyframes: {
        "fade-in": { from: { opacity: "0", transform: "translateY(3px)" }, to: { opacity: "1", transform: "none" } },
      },
      animation: { "fade-in": "fade-in 0.18s ease-out" },
    },
  },
  plugins: [],
} satisfies Config;
