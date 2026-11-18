import { useEffect, useState } from "react";

const QUERY = "(pointer: coarse)";

/** True on touch-first devices (phones, tablets): the reader adapts its controls to the thumb. */
export function useCoarsePointer(): boolean {
  const [coarse, setCoarse] = useState(() => typeof window !== "undefined" && window.matchMedia(QUERY).matches);
  useEffect(() => {
    const mq = window.matchMedia(QUERY);
    const onChange = () => setCoarse(mq.matches);
    onChange();
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return coarse;
}
