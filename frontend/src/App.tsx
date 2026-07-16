import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";

import { Dropzone } from "@/components/Dropzone";
import { JobHistory } from "@/components/JobHistory";
import { ThemeToggle } from "@/components/ThemeToggle";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useJobs } from "@/hooks/useJobs";
import { fetchCapabilities } from "@/lib/api";

export default function App() {
  const { jobs, error, refresh } = useJobs();
  const [llmAvailable, setLlmAvailable] = useState(false);
  const [version, setVersion] = useState<string | null>(null);

  useEffect(() => {
    fetchCapabilities()
      .then((c) => {
        setLlmAvailable(c.llm_available);
        setVersion(c.version);
      })
      .catch(() => setLlmAvailable(false));
  }, []);

  return (
    <div className="min-h-screen">
      <header className="border-b">
        <div className="mx-auto flex max-w-3xl items-center justify-between px-4 py-4">
          <div className="flex items-center gap-2.5">
            <img src="/favicon.svg" alt="" className="size-7" />
            <div>
              <h1 className="text-base font-semibold leading-tight">Markloom</h1>
              <p className="text-xs text-muted-foreground">Documents → Markdown</p>
            </div>
          </div>
          <ThemeToggle />
        </div>
      </header>

      <main className="mx-auto max-w-3xl space-y-6 px-4 py-8">
        <Card>
          <CardContent className="pt-6">
            <Dropzone onUploaded={refresh} enhancedAvailable={llmAvailable} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle className="text-base">History</CardTitle>
            <Button variant="ghost" size="sm" onClick={() => void refresh()}>
              <RefreshCw />
              Refresh
            </Button>
          </CardHeader>
          <CardContent>
            {error ? (
              <p className="py-8 text-center text-sm text-destructive">{error}</p>
            ) : (
              <JobHistory jobs={jobs} onChanged={refresh} />
            )}
          </CardContent>
        </Card>

        <footer className="flex items-center justify-between text-xs text-muted-foreground">
          <span>
            Markloom{version ? ` ${version === "dev" ? "dev" : `v${version}`}` : ""}
          </span>
          <span>
            Powered by{" "}
            <a
              className="underline underline-offset-2 hover:text-foreground"
              href="https://github.com/microsoft/markitdown"
              target="_blank"
              rel="noreferrer"
            >
              MarkItDown
            </a>
          </span>
        </footer>
      </main>
    </div>
  );
}
