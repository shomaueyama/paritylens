import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "secondary" | "danger" | "ghost";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-accent text-accent-foreground hover:opacity-90",
  secondary: "border border-line bg-surface hover:bg-neutral-soft",
  danger: "border border-critical text-critical hover:bg-critical-soft",
  ghost: "text-muted hover:text-foreground hover:bg-neutral-soft",
};

export function buttonClass(variant: Variant = "secondary", className = ""): string {
  return [
    "inline-flex items-center justify-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium",
    "transition-colors disabled:cursor-not-allowed disabled:opacity-50",
    "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
    VARIANTS[variant],
    className,
  ].join(" ");
}

export function Button({
  variant = "secondary",
  className,
  type = "button",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  // type defaults to "button": inside a form, a bare <button> submits it.
  return <button type={type} className={buttonClass(variant, className)} {...props} />;
}
