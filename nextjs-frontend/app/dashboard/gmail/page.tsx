import { MailCheck } from "lucide-react";

import {
  connectGmail,
  fetchGmailStatus,
} from "@/components/actions/gmail-action";
import { Button } from "@/components/ui/button";
import { GmailPanel } from "./gmail-panel";

type GmailPageProps = {
  searchParams: Promise<{
    connected?: string;
    error?: string;
  }>;
};

export default async function GmailPage({ searchParams }: GmailPageProps) {
  const params = await searchParams;
  const status = await fetchGmailStatus();

  return (
    <div className="grid gap-6">
      {params.connected ? (
        <div className="rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm font-medium text-emerald-700">
          Gmail connected.
        </div>
      ) : null}

      {params.error ? (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm font-medium text-red-700">
          {params.error}
        </div>
      ) : null}

      {!status.connected ? (
        <section className="rounded-lg border bg-white p-6 shadow-sm">
          <div className="flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="text-xl font-semibold">Gmail Priority Sorter</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                High, Medium, and Low labels for the inbox that matters today.
              </p>
            </div>
            <form action={connectGmail}>
              <Button type="submit" className="gap-2">
                <MailCheck className="h-4 w-4" />
                Connect Gmail
              </Button>
            </form>
          </div>
        </section>
      ) : null}

      <GmailPanel status={status} />
    </div>
  );
}
