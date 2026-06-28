import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        canvas:             "var(--canvas)",
        "surface-soft":     "var(--surface-soft)",
        "surface-card":     "var(--surface-card)",
        "surface-strong":   "var(--surface-cream-strong)",
        "surface-dark":     "var(--surface-dark)",
        "surface-dark-soft":"var(--surface-dark-soft)",
        "surface-dark-elevated": "var(--surface-dark-elevated)",
        ink:                "var(--ink)",
        "body-strong":      "var(--body-strong)",
        body:               "var(--body)",
        muted:              "var(--muted)",
        "muted-soft":       "var(--muted-soft)",
        "on-primary":       "var(--on-primary)",
        "on-dark":          "var(--on-dark)",
        "on-dark-soft":     "var(--on-dark-soft)",
        primary:            "var(--primary)",
        "primary-active":   "var(--primary-active)",
        "primary-disabled": "var(--primary-disabled)",
        "accent-teal":      "var(--accent-teal)",
        "accent-amber":     "var(--accent-amber)",
        hairline:           "var(--hairline)",
        "hairline-soft":    "var(--hairline-soft)",
        success:            "var(--success)",
        warning:            "var(--warning)",
        error:              "var(--error)",
      },
      fontFamily: {
        display: ["Cormorant Garamond", "Garamond", "Times New Roman", "serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
