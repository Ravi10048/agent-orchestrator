import { create } from "zustand";

export type ToastTone = "success" | "error" | "info";
interface Toast {
  id: number;
  title: string;
  tone: ToastTone;
}
interface ToastState {
  toasts: Toast[];
  push: (t: { title: string; tone?: ToastTone }) => void;
  dismiss: (id: number) => void;
}

let counter = 0;

export const useToasts = create<ToastState>((set) => ({
  toasts: [],
  push: ({ title, tone = "info" }) => {
    const id = ++counter;
    set((s) => ({ toasts: [...s.toasts, { id, title, tone }] }));
    setTimeout(() => set((s) => ({ toasts: s.toasts.filter((x) => x.id !== id) })), 4000);
  },
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((x) => x.id !== id) })),
}));

export const toast = {
  success: (title: string) => useToasts.getState().push({ title, tone: "success" }),
  error: (title: string) => useToasts.getState().push({ title, tone: "error" }),
  info: (title: string) => useToasts.getState().push({ title, tone: "info" }),
};
