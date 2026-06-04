"use client";

import { useActionState } from "react";
import { Mail, Play, ShieldCheck } from "lucide-react";

import {
  GmailStatus,
  triageConnectedGmail,
} from "@/components/actions/gmail-action";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type GmailPanelProps = {
  status: GmailStatus;
};

export function GmailPanel({ status }: GmailPanelProps) {
  const [state, action, pending] = useActionState(triageConnectedGmail, {});

  return (
    <div className="grid gap-6">
      <section className="rounded-lg border bg-white p-6 shadow-sm">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-md bg-emerald-100 text-emerald-700">
              <Mail className="h-5 w-5" />
            </div>
            <div>
              <h2 className="text-xl font-semibold">Gmail Priority Sorter</h2>
              <p className="text-sm text-muted-foreground">
                {status.connected
                  ? status.email_address
                  : "Connect a Gmail account"}
              </p>
            </div>
          </div>
          {status.connected ? (
            <span className="inline-flex items-center gap-2 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm font-medium text-emerald-700">
              <ShieldCheck className="h-4 w-4" />
              Connected
            </span>
          ) : null}
        </div>
      </section>

      {status.connected ? (
        <form action={action} className="rounded-lg border bg-white p-6 shadow-sm">
          <div className="grid gap-5">
            <div className="grid gap-2">
              <Label htmlFor="search_query">Mailbox scope</Label>
              <Input
                id="search_query"
                name="search_query"
                defaultValue="newer_than:1d"
              />
            </div>

            <div className="grid gap-2 sm:max-w-48">
              <Label htmlFor="max_results">Batch size</Label>
              <Input
                id="max_results"
                name="max_results"
                type="number"
                min={1}
                max={200}
                defaultValue={50}
              />
            </div>

            <div className="grid gap-2">
              <Label htmlFor="user_focus">Priority rules</Label>
              <textarea
                id="user_focus"
                name="user_focus"
                className="min-h-28 rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                defaultValue={
                  "Prioritize direct human requests, legal or finance issues, deadlines, customer issues, action items, and emails with specific dates or times. Updates are medium unless action is needed. Promotions default low, but can be medium or high for urgent deadlines, account/payment/legal/security relevance, important senders, or content matching my active focus."
                }
              />
            </div>

            <label className="flex items-center gap-3 text-sm font-medium">
              <input
                type="checkbox"
                name="dry_run"
                defaultChecked
                className="h-4 w-4 rounded border-gray-300"
              />
              Dry run
            </label>

            <Button type="submit" disabled={pending} className="w-fit gap-2">
              <Play className="h-4 w-4" />
              {pending ? "Sorting..." : "Sort inbox"}
            </Button>

            {state.message ? (
              <p className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                {state.message}
              </p>
            ) : null}
          </div>
        </form>
      ) : null}

      {state.result ? (
        <section className="rounded-lg border bg-white p-6 shadow-sm">
          <h3 className="mb-3 text-lg font-semibold">Triage report</h3>
          <pre className="max-h-[520px] overflow-auto whitespace-pre-wrap rounded-md bg-neutral-950 p-4 text-sm leading-6 text-neutral-50">
            {state.result}
          </pre>
        </section>
      ) : null}
    </div>
  );
}
