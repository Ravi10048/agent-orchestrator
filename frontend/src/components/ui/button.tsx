import { type ButtonHTMLAttributes, forwardRef } from "react";

import { cn } from "@/lib/cn";

const VARIANTS = {
  primary: "bg-primary text-primary-fg hover:brightness-110 shadow-glow",
  secondary: "bg-surface text-fg border border-border hover:border-border-strong hover:bg-card",
  outline: "border border-border text-fg hover:border-border-strong hover:bg-surface",
  ghost: "text-muted hover:bg-surface hover:text-fg",
  destructive: "bg-destructive text-white hover:brightness-110",
} as const;

const SIZES = {
  sm: "h-8 px-3 text-[13px]",
  md: "h-9 px-4 text-sm",
  lg: "h-10 px-5 text-sm",
  icon: "h-9 w-9 p-0",
} as const;

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: keyof typeof VARIANTS;
  size?: keyof typeof SIZES;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "primary", size = "md", ...props }, ref) => (
    <button
      ref={ref}
      className={cn(
        "inline-flex select-none items-center justify-center gap-2 rounded-lg font-medium",
        "transition active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2",
        "focus-visible:ring-[hsl(var(--ring))] focus-visible:ring-offset-2 focus-visible:ring-offset-bg",
        "disabled:opacity-50 disabled:pointer-events-none",
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      {...props}
    />
  ),
);
Button.displayName = "Button";
