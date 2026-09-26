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
        accent: { DEFAULT: "#1D7A85", fg: "#FAF9F6" },
        warn: "#B8862B",
        danger: "#B0473F",
        success: "#3F7A5C",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        display: ["Fraunces", "serif"],
      },
    },
  },
} satisfies Config;
