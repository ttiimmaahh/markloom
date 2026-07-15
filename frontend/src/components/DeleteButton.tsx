import { useState } from "react";
import { Loader2, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { deleteJob } from "@/lib/api";

/** Trash button with an inline two-step confirm (no dialog dependency). */
export function DeleteButton({ jobId, onDeleted }: { jobId: string; onDeleted: () => void }) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);

  async function remove() {
    setBusy(true);
    try {
      await deleteJob(jobId);
      onDeleted();
    } catch {
      // leave the row in place if the delete failed
      setBusy(false);
      setConfirming(false);
    }
  }

  if (confirming) {
    return (
      <span className="inline-flex items-center justify-end gap-1">
        <Button variant="destructive" size="sm" onClick={remove} disabled={busy}>
          {busy && <Loader2 className="animate-spin" />}
          Delete
        </Button>
        <Button variant="ghost" size="sm" onClick={() => setConfirming(false)} disabled={busy}>
          Cancel
        </Button>
      </span>
    );
  }

  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label="Delete conversion"
      onClick={() => setConfirming(true)}
    >
      <Trash2 />
    </Button>
  );
}
