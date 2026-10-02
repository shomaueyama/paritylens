import type { InputHTMLAttributes, ReactNode, TextareaHTMLAttributes } from "react";

const CONTROL =
  "w-full rounded-md border border-line bg-surface px-3 py-1.5 text-sm " +
  "placeholder:text-muted focus-visible:outline-2 focus-visible:outline-accent " +
  "aria-invalid:border-critical";

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`${CONTROL} ${props.className ?? ""}`} />;
}

export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={`${CONTROL} font-mono ${props.className ?? ""}`} />;
}

/** A labelled form control with room for a hint and an error message. */
export function Field({
  label,
  htmlFor,
  hint,
  error,
  children,
}: {
  label: string;
  htmlFor: string;
  hint?: string;
  error?: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={htmlFor} className="text-sm font-medium">
        {label}
      </label>
      {children}
      {hint && !error ? <p className="text-xs text-muted">{hint}</p> : null}
      {error ? (
        <p role="alert" className="text-xs text-critical">
          {error}
        </p>
      ) : null}
    </div>
  );
}
