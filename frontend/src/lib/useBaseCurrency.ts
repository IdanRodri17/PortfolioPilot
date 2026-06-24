"use client";

import { useEffect, useState } from "react";
import type { BaseCurrency } from "@/lib/money";

/**
 * The report's display base currency (V17), persisted in localStorage so the
 * choice sticks across reports and pages. Defaults to USD.
 */
export function useBaseCurrency(): [BaseCurrency, (b: BaseCurrency) => void] {
  const [base, setBaseState] = useState<BaseCurrency>("USD");

  useEffect(() => {
    // SSR-safe: render the default, then adopt the persisted choice on mount.
    const saved = localStorage.getItem("base_currency");
    if (saved === "USD" || saved === "ILS") {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setBaseState(saved);
    }
  }, []);

  function setBase(b: BaseCurrency) {
    setBaseState(b);
    try {
      localStorage.setItem("base_currency", b);
    } catch {
      /* ignore (private mode, storage disabled) */
    }
  }

  return [base, setBase];
}
