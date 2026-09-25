import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: ["class", '[data-theme="dark"]'],
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
