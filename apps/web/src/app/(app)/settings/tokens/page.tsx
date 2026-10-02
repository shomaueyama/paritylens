import type { Metadata } from "next";

import { DeleteButton } from "@/components/delete-button";
import { Card, CardHeader, EmptyState } from "@/components/ui/card";
import { load, serverApi } from "@/lib/api/server";
import { formatDateTime } from "@/lib/result";

import { TokenForm } from "./token-form";

export const metadata: Metadata = { title: "API tokens" };

export default async function TokensPage() {
  const api = await serverApi();
  const tokens = await load(api.GET("/api/v1/api-tokens"));

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">API tokens</h1>
        <p className="mt-1 text-sm text-muted">
          For <code>paritylens run --upload-to</code>. Set one as{" "}
          <code>PARITYLENS_API_TOKEN</code>.
        </p>
      </div>
      <Card>
        <CardHeader title="New token" />
        <TokenForm />
      </Card>
      <Card>
        <CardHeader title="Tokens" />
        {tokens.length === 0 ? (
          <EmptyState>No tokens.</EmptyState>
        ) : (
          <ul className="divide-y divide-line">
            {tokens.map((token) => (
              <li key={token.id} className="flex flex-wrap items-center gap-4 px-4 py-2 text-sm">
                <span className="flex-1 font-medium">{token.name}</span>
                <code className="text-xs text-muted">{token.token_hint}…</code>
                <span className="text-xs text-muted">
                  {token.last_used_at
                    ? `last used ${formatDateTime(token.last_used_at)}`
                    : "never used"}
                </span>
                <DeleteButton
                  target={{ kind: "token", id: token.id }}
                  label="Revoke"
                  confirm={`Revoke "${token.name}"? Anything using it will stop working.`}
                />
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
