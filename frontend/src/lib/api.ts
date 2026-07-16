export type JobStatus =
	| "queued"
	| "processing"
	| "done"
	| "failed"
	| "canceled";
export type ConversionMode = "standard" | "enhanced";

export interface Job {
	id: string;
	orig_filename: string;
	file_type: string;
	size_bytes: number;
	status: JobStatus;
	mode: ConversionMode;
	can_cancel: boolean;
	error: string | null;
	created_at: string;
	completed_at: string | null;
	download_url: string | null;
}

export interface Capabilities {
	llm_available: boolean;
	/** Release version baked into the image (e.g. "1.2.0"), or "dev". */
	version: string;
}

export class ApiError extends Error {
	constructor(
		message: string,
		readonly status: number,
	) {
		super(message);
		this.name = "ApiError";
	}
}

async function handle<T>(res: Response): Promise<T> {
	if (!res.ok) {
		let message = `${res.status} ${res.statusText}`;
		try {
			const body = await res.json();
			if (body?.detail) message = body.detail;
		} catch {
			// non-JSON error body; keep the status text
		}
		throw new ApiError(message, res.status);
	}
	return res.json() as Promise<T>;
}

export function uploadFile(file: File, enhanced = false): Promise<Job> {
	const form = new FormData();
	form.append("file", file);
	if (enhanced) form.append("enhanced", "true");
	return fetch("/api/convert", { method: "POST", body: form }).then((r) =>
		handle<Job>(r),
	);
}

export function fetchCapabilities(): Promise<Capabilities> {
	return fetch("/api/capabilities").then((r) => handle<Capabilities>(r));
}

export function fetchJobs(): Promise<Job[]> {
	return fetch("/api/jobs").then((r) => handle<Job[]>(r));
}

export function fetchJob(id: string): Promise<Job> {
	return fetch(`/api/jobs/${id}`).then((r) => handle<Job>(r));
}

export function cancelJob(id: string): Promise<Job> {
	return fetch(`/api/jobs/${id}/cancel`, { method: "POST" }).then((r) =>
		handle<Job>(r),
	);
}

export async function deleteJob(id: string): Promise<void> {
	const res = await fetch(`/api/jobs/${id}`, { method: "DELETE" });
	if (!res.ok) {
		let message = `${res.status} ${res.statusText}`;
		try {
			const body = await res.json();
			if (body?.detail) message = body.detail;
		} catch {
			// 204 has no body; nothing to parse
		}
		throw new Error(message);
	}
}
