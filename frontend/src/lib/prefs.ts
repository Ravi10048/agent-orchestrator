// Small, durable UI preferences (localStorage). Wrapped in try/catch so private-mode / SSR
// can never throw. Used to remember the last Telegram chat id across the Run modal + chat bench.
const CHAT_ID_KEY = "ao:telegramChatId";

export function getLastChatId(): string {
  try {
    return localStorage.getItem(CHAT_ID_KEY) ?? "";
  } catch {
    return "";
  }
}

export function saveLastChatId(value: string): void {
  try {
    const v = value.trim();
    if (v) localStorage.setItem(CHAT_ID_KEY, v);
  } catch {
    /* ignore */
  }
}
