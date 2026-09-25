import type { Config } from "tailwindcss";

// Colors resolve to CSS variables (see app/globals.css) so light/dark themes
// swap in one place and components never hard-code hex values.
const token = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./features/**/*.{ts,tsx}"],
  darkMode: "media",
  theme: {
    extend: {
      colors: {
        canvas: token("canvas"),
        surface: token("surface"),
        sunken: token("sunken"),
        line: token("line"),
        "line-strong": token("line-strong"),
        ink: { DEFAULT: token("ink"), 2: token("ink-2"), 3: token("ink-3") },
        brand: { DEFAULT: token("brand"), soft: token("brand-soft"), ink: token("brand-ink") },
        rail: { DEFAULT: token("rail"), 2: token("rail-2"), ink: token("rail-ink"), mute: token("rail-mute") },
        mark: token("mark"),
        danger: { DEFAULT: token("danger"), soft: token("danger-soft") },
        warn: { DEFAULT: token("warn"), soft: token("warn-soft") },
        ok: { DEFAULT: token("ok"), soft: token("ok-soft") },
        info: { DEFAULT: token("info"), soft: token("info-soft") },
      },
      fontFamily: {
        sans: ["Inter Variable", "Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        serif: ["Fraunces Variable", "Fraunces", "ui-serif", "Georgia", "serif"],
        mono: ["JetBrains Mono Variable", "JetBrains Mono", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem" }],
      },
      boxShadow: {
        card: "0 1px 0 rgb(var(--shadow) / 0.04), 0 1px 3px rgb(var(--shadow) / 0.06)",
        lift: "0 8px 24px -8px rgb(var(--shadow) / 0.18), 0 2px 6px rgb(var(--shadow) / 0.06)",
        paper: "0 1px 2px rgb(var(--shadow) / 0.06), 0 12px 32px -12px rgb(var(--shadow) / 0.22)",
      },
      keyframes: {
        "fade-up": { from: { opacity: "0", transform: "translateY(6px)" }, to: { opacity: "1", transform: "none" } },
        shimmer: { from: { backgroundPosition: "-200% 0" }, to: { backgroundPosition: "200% 0" } },
        pulse_dot: { "0%,100%": { opacity: "1" }, "50%": { opacity: "0.35" } },
      },
      animation: {
        "fade-up": "fade-up 320ms cubic-bezier(.2,.7,.2,1) both",
        shimmer: "shimmer 1.6s linear infinite",
        "pulse-dot": "pulse_dot 1.4s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};

export default config;
