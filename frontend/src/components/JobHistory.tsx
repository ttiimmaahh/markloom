import { useRef } from "react";
import { CircleStop, Download, FileText, Sparkles } from "lucide-react";

import { DeleteButton } from "@/components/DeleteButton";
import { StatusBadge } from "@/components/StatusBadge";
import { StopButton } from "@/components/StopButton";
import { Button, buttonVariants } from "@/components/ui/button";
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "@/components/ui/table";
import type { Job } from "@/lib/api";
import { formatBytes, formatRelativeTime } from "@/lib/format";

function DownloadLink({ href }: { href: string }) {
	return (
		<a
			href={href}
			className={buttonVariants({ variant: "outline", size: "sm" })}
		>
			<Download />
			Download
		</a>
	);
}

export function JobHistory({
	jobs,
	onChanged,
}: {
	jobs: Job[];
	onChanged: () => void | Promise<void>;
}) {
	const historyRegionRef = useRef<HTMLDivElement>(null);

	async function handleDeleted() {
		await onChanged();
		historyRegionRef.current?.focus();
	}

	async function handleStopped(jobId: string) {
		await onChanged();
		const row = document.querySelector<HTMLElement>(
			`[data-job-row="${jobId}"]`,
		);
		(row ?? historyRegionRef.current)?.focus();
	}

	return (
		<div
			ref={historyRegionRef}
			tabIndex={-1}
			role="region"
			aria-label="Conversion history"
			className="rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
		>
			{jobs.length === 0 ? (
				<div className="flex flex-col items-center gap-2 py-12 text-center text-muted-foreground">
					<FileText className="size-8 opacity-40" />
					<p className="text-sm">
						No conversions yet. Drop a file above to get started.
					</p>
				</div>
			) : (
				<Table>
					<TableHeader>
						<TableRow>
							<TableHead>File</TableHead>
							<TableHead>Status</TableHead>
							<TableHead className="hidden sm:table-cell">Size</TableHead>
							<TableHead className="hidden sm:table-cell">When</TableHead>
							<TableHead className="text-right">Markdown</TableHead>
							<TableHead className="w-0">
								<span className="sr-only">Actions</span>
							</TableHead>
						</TableRow>
					</TableHeader>
					<TableBody>
						{jobs.map((job) => (
							<TableRow
								key={job.id}
								data-job-row={job.id}
								tabIndex={-1}
								className="focus:outline-none focus:ring-2 focus:ring-inset focus:ring-ring"
							>
								<TableCell className="max-w-[16rem]">
									<div className="flex items-center gap-2">
										<FileText className="size-4 shrink-0 text-muted-foreground" />
										<span
											className="truncate font-medium"
											title={job.orig_filename}
										>
											{job.orig_filename}
										</span>
										{job.mode === "enhanced" && (
											<span
												className="inline-flex shrink-0 items-center gap-1 rounded-full bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary"
												title="Converted with Enhanced (LLM OCR)"
											>
												<Sparkles className="size-2.5" />
												Enhanced
											</span>
										)}
									</div>
									{job.status === "failed" && job.error && (
										<p
											className="mt-1 truncate text-xs text-destructive"
											title={job.error}
										>
											{job.error}
										</p>
									)}
								</TableCell>
								<TableCell>
									<StatusBadge status={job.status} />
								</TableCell>
								<TableCell className="hidden text-muted-foreground sm:table-cell">
									{formatBytes(job.size_bytes)}
								</TableCell>
								<TableCell className="hidden text-muted-foreground sm:table-cell">
									{formatRelativeTime(job.created_at)}
								</TableCell>
								<TableCell className="text-right">
									{job.download_url ? (
										<DownloadLink href={job.download_url} />
									) : (
										<span className="text-xs text-muted-foreground">—</span>
									)}
								</TableCell>
								<TableCell className="text-right">
									{job.can_cancel ? (
										<StopButton
											jobId={job.id}
											filename={job.orig_filename}
											onStopped={handleStopped}
										/>
									) : job.status === "processing" ? (
										<Button
											variant="ghost"
											size="icon"
											className="cursor-not-allowed opacity-50 hover:bg-transparent"
											aria-disabled="true"
											aria-label={`Standard and audio conversions can’t be stopped after processing begins: ${job.orig_filename}`}
											title="Standard and audio conversions can’t be stopped after processing begins"
											onClick={(event) => event.preventDefault()}
										>
											<CircleStop />
										</Button>
									) : (
										<DeleteButton
											jobId={job.id}
											filename={job.orig_filename}
											onDeleted={handleDeleted}
										/>
									)}
								</TableCell>
							</TableRow>
						))}
					</TableBody>
				</Table>
			)}
		</div>
	);
}
