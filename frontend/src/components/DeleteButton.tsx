import { useState } from "react";
import { Loader2, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
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
import { deleteJob } from "@/lib/api";

const DIALOG_EXIT_DURATION_MS = 200;

export function DeleteButton({
	jobId,
	filename,
	onDeleted,
}: {
	jobId: string;
	filename: string;
	onDeleted: () => void;
}) {
	const [open, setOpen] = useState(false);
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState<string | null>(null);

	function handleOpenChange(nextOpen: boolean) {
		if (busy) return;
		setOpen(nextOpen);
		if (nextOpen) setError(null);
	}

	async function remove() {
		if (busy) return;
		setBusy(true);
		setError(null);

		try {
			await deleteJob(jobId);
			setOpen(false);
			window.setTimeout(onDeleted, DIALOG_EXIT_DURATION_MS);
		} catch (cause) {
			setError(
				cause instanceof Error
					? cause.message
					: "The conversion could not be deleted.",
			);
		} finally {
			setBusy(false);
		}
	}

	return (
		<AlertDialog open={open} onOpenChange={handleOpenChange}>
			<AlertDialogTrigger asChild>
				<Button variant="ghost" size="icon" aria-label={`Delete ${filename}`}>
					<Trash2 />
				</Button>
			</AlertDialogTrigger>
			<AlertDialogContent
				onEscapeKeyDown={(event) => busy && event.preventDefault()}
			>
				<AlertDialogHeader>
					<AlertDialogTitle>Delete this conversion?</AlertDialogTitle>
					<AlertDialogDescription className="break-words">
						<span className="font-medium text-foreground">“{filename}”</span>{" "}
						and its converted Markdown will be permanently deleted. This can’t
						be undone.
					</AlertDialogDescription>
				</AlertDialogHeader>

				{error && (
					<p role="alert" className="text-sm text-destructive">
						{error}
					</p>
				)}

				<AlertDialogFooter>
					<AlertDialogCancel disabled={busy}>Cancel</AlertDialogCancel>
					<AlertDialogAction
						variant="destructive"
						disabled={busy}
						onClick={(event) => {
							event.preventDefault();
							void remove();
						}}
					>
						{busy && (
							<Loader2 data-icon="inline-start" className="animate-spin" />
						)}
						{busy ? "Deleting…" : "Delete"}
					</AlertDialogAction>
				</AlertDialogFooter>
			</AlertDialogContent>
		</AlertDialog>
	);
}
