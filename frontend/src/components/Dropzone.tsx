import { useCallback, useState } from "react";
import { useDropzone } from "react-dropzone";
import { FileText, Loader2, Sparkles, UploadCloud } from "lucide-react";

import { Switch } from "@/components/ui/switch";
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

	const { getRootProps, getInputProps, isDragActive } = useDropzone({
		onDrop,
		disabled: busy,
	});

	return (
		<div className="flex flex-col gap-3">
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
				<div className="flex items-start justify-between gap-4 rounded-md border border-input bg-accent/30 px-3 py-2.5">
					<div className="flex min-w-0 flex-col gap-1">
						<label
							htmlFor="enhanced-conversion"
							className="inline-flex cursor-pointer items-center gap-1.5 text-sm font-medium"
						>
							<Sparkles className="size-3.5 text-primary" />
							Enhanced conversion
						</label>
						<p
							id="enhanced-conversion-description"
							className="text-xs text-muted-foreground"
						>
							Uses an LLM to read text inside images (screenshots, diagrams,
							scans). Much slower, and may contain OCR errors — verify critical
							values against the source.
						</p>
					</div>
					<Switch
						id="enhanced-conversion"
						className="mt-0.5"
						checked={enhanced}
						onCheckedChange={setEnhanced}
						disabled={busy}
						aria-describedby="enhanced-conversion-description"
					/>
				</div>
			)}

			{error && <p className="text-sm text-destructive">{error}</p>}
		</div>
	);
}
