import { useState, useEffect } from "react";

type Theme = "light" | "dark";

function prefersDark(): boolean {
  return typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function getInitialTheme(): Theme {
  const stored =
    typeof localStorage !== "undefined" ? localStorage.getItem("theme") : null;
  if (stored === "dark" || stored === "light") return stored;
  return prefersDark() ? "dark" : "light";
}

function applyTheme(theme: Theme) {
  if (theme === "dark") {
    document.documentElement.classList.add("dark");
  } else {
    document.documentElement.classList.remove("dark");
  }
}

export function useTheme(): { isDark: boolean; toggle: () => void } {
  const [theme, setTheme] = useState<Theme>(getInitialTheme);

  // Sync class on mount and whenever theme changes
  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  // Listen for OS preference changes when no manual override is set
  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
    const handleChange = (e: MediaQueryListEvent) => {
      if (!localStorage.getItem("theme")) {
        setTheme(e.matches ? "dark" : "light");
      }
    };
    mediaQuery.addEventListener("change", handleChange);
    return () => mediaQuery.removeEventListener("change", handleChange);
  }, []);

  const toggle = () => {
    setTheme((prev) => {
      const next = prev === "dark" ? "light" : "dark";
      localStorage.setItem("theme", next);
      return next;
    });
  };

  return { isDark: theme === "dark", toggle };
}
