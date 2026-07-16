import { CircleStop, Loader2 } from "lucide-react";
import { useState } from "react";

import {
	AlertDialog,
	AlertDialogAction,
	AlertDialogCancel,
	AlertDialogContent,
	AlertDialogDescription,
	AlertDialogFooter,
	AlertDialogHeader,
	AlertDialogTitle,
	AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { ApiError, cancelJob } from "@/lib/api";

const DIALOG_EXIT_DURATION_MS = 200;

export function StopButton({
	jobId,
	filename,
	onStopped,
}: {
	jobId: string;
	filename: string;
	onStopped: (jobId: string) => void | Promise<void>;
}) {
	const [open, setOpen] = useState(false);
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState<string | null>(null);

	function handleOpenChange(nextOpen: boolean) {
		if (busy) return;
		setOpen(nextOpen);
		if (nextOpen) setError(null);
	}

	async function stop() {
		if (busy) return;
		setBusy(true);
		setError(null);

		try {
			await cancelJob(jobId);
			setOpen(false);
			window.setTimeout(() => void onStopped(jobId), DIALOG_EXIT_DURATION_MS);
		} catch (cause) {
			// A 404 is a benign stale-row race. Keep 409 visible: it means queued
			// Standard/audio work started before the request and is still running.
			if (cause instanceof ApiError && cause.status === 404) {
				setOpen(false);
				window.setTimeout(() => void onStopped(jobId), DIALOG_EXIT_DURATION_MS);
				return;
			}
			setError(
				cause instanceof Error
					? cause.message
					: "The conversion could not be stopped.",
			);
		} finally {
			setBusy(false);
		}
	}

	return (
		<AlertDialog open={open} onOpenChange={handleOpenChange}>
			<AlertDialogTrigger asChild>
				<Button
					variant="ghost"
					size="icon"
					aria-label={`Stop converting ${filename}`}
				>
					<CircleStop />
				</Button>
			</AlertDialogTrigger>
			<AlertDialogContent
				onEscapeKeyDown={(event) => busy && event.preventDefault()}
			>
				<AlertDialogHeader>
					<AlertDialogTitle>Stop this conversion?</AlertDialogTitle>
					<AlertDialogDescription className="break-words">
						<span className="font-medium text-foreground">“{filename}”</span>{" "}
						will stop immediately. The uploaded copy will be discarded, and
						you’ll need to upload it again to restart the conversion.
					</AlertDialogDescription>
				</AlertDialogHeader>

				{error && (
					<p role="alert" className="text-sm text-destructive">
						{error}
					</p>
				)}

				<AlertDialogFooter>
					<AlertDialogCancel disabled={busy}>Keep running</AlertDialogCancel>
					<AlertDialogAction
						variant="destructive"
						disabled={busy}
						onClick={(event) => {
							event.preventDefault();
							void stop();
						}}
					>
						{busy && (
							<Loader2 data-icon="inline-start" className="animate-spin" />
						)}
						{busy ? "Stopping…" : "Stop conversion"}
					</AlertDialogAction>
				</AlertDialogFooter>
			</AlertDialogContent>
		</AlertDialog>
	);
}
