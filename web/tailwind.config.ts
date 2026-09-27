import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  // Same rule as design-system/tokens.css: follow the OS colour scheme, unless
  // <html data-theme="light|dark"> forces one.
  darkMode: [
    "variant",
    [
      '@media (prefers-color-scheme: dark) { &:not([data-theme="light"] *) }',
      '&:is([data-theme="dark"] *)',
    ],
  ],
  theme: {
    extend: {
      colors: {
        ink: "#12151A",
        paper: "#FAF9F6",
        // `bright` shades are for text on the dark background: the default
        // shades fall below WCAG AA contrast (4.5:1) on ink.
        accent: { DEFAULT: "#1D7A85", fg: "#FAF9F6", bright: "#5FBFCB" },
        warn: { DEFAULT: "#B8862B", bright: "#E0B45C" },
        danger: { DEFAULT: "#B0473F", bright: "#E58A82" },
        success: { DEFAULT: "#3F7A5C", bright: "#7CC29B" },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        display: ["Fraunces", "serif"],
      },
    },
  },
} satisfies Config;
