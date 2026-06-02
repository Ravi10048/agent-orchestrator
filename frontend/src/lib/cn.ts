import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/** Merge Tailwind classes with conditional logic + conflict resolution. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/** Stable 8-hue tint for an agent name — same agent gets the same color everywhere. */
const AGENT_HUES = [243, 199, 152, 280, 33, 0, 320, 175];
export function agentHue(name: string): number {
  let h = 0;
  for (const c of name) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return AGENT_HUES[h % AGENT_HUES.length];
}
