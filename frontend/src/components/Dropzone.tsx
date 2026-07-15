import { useCallback, useState } from "react";
import { useDropzone } from "react-dropzone";
import { FileText, Loader2, Sparkles, UploadCloud } from "lucide-react";

import { uploadFile } from "@/lib/api";
import { cn } from "@/lib/utils";

export function Dropzone({
  onUploaded,
  enhancedAvailable,
}: {
  onUploaded: () => void;
  enhancedAvailable: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [enhanced, setEnhanced] = useState(false);

  const onDrop = useCallback(
    async (files: File[]) => {
      if (files.length === 0) return;
      setError(null);
      setBusy(true);
      try {
        for (const file of files) {
          await uploadFile(file, enhanced && enhancedAvailable);
        }
        onUploaded();
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setBusy(false);
      }
    },
    [onUploaded, enhanced, enhancedAvailable],
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({ onDrop, disabled: busy });

  return (
    <div className="space-y-3">
      <div
        {...getRootProps()}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed border-input px-6 py-14 text-center transition-colors",
          "hover:border-primary/60 hover:bg-accent/40",
          isDragActive && "border-primary bg-primary/5",
          busy && "pointer-events-none opacity-60",
        )}
      >
        <input {...getInputProps()} />
        <div className="flex size-12 items-center justify-center rounded-full bg-primary/10 text-primary">
          {busy ? (
            <Loader2 className="size-6 animate-spin" />
          ) : isDragActive ? (
            <FileText className="size-6" />
          ) : (
            <UploadCloud className="size-6" />
          )}
        </div>
        <div>
          <p className="font-medium">
            {busy
              ? "Uploading…"
              : isDragActive
                ? "Drop to convert"
                : "Drag & drop a file, or click to browse"}
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            PDF, DOCX, PPTX, XLSX, audio and more — converted to clean Markdown
          </p>
        </div>
      </div>

      {enhancedAvailable && (
        <label className="flex cursor-pointer items-start gap-2.5 rounded-md border border-input bg-accent/30 px-3 py-2.5 text-sm">
          <input
            type="checkbox"
            checked={enhanced}
            onChange={(e) => setEnhanced(e.target.checked)}
            className="mt-0.5 size-4 accent-primary"
          />
          <span>
            <span className="inline-flex items-center gap-1.5 font-medium">
              <Sparkles className="size-3.5 text-primary" />
              Enhanced conversion
            </span>
            <span className="mt-0.5 block text-xs text-muted-foreground">
              Uses an LLM to read text inside images (screenshots, diagrams, scans). Much slower,
              and may contain OCR errors — verify critical values against the source.
            </span>
          </span>
        </label>
      )}

      {error && <p className="text-sm text-destructive">{error}</p>}
    </div>
  );
}
