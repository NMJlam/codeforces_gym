/**
 * Typed client for the Flask API under /api.
 *
 * One module so the contract lives in one place: paths, bodies, and the error
 * path. The API answers a refusal as JSON `{ message }` written for a human
 * ("cf_handle already in use", "no accepted submission in this attempt's
 * window"), so the client shows that sentence verbatim — the fallbacks below
 * only cover responses that carry no body (a proxy error, a 403 from the auth
 * hook, say).
 */

export type Rating = { rating: number; rd: number };
/** Every slot the database stores. A scored attempt reports `recall`; nothing else does. */
export type Slot = 'warmup' | 'main' | 'stretch' | 'recall';
/** The three slots the picker serves: `recall` is handed out by the revisit queue instead. */
export type SessionSlot = 'warmup' | 'main' | 'stretch';
export type Source = 'session' | 'self_selected' | 'contest';
export type SkillState = 'not_yet_relevant' | 'unknown' | 'weak' | 'strong';

export type Problem = {
	contest_id: number;
	index: string;
	name: string;
	rating: number | null;
	/** Present only once the attempt is scored: no hints during the attempt. */
	editorial_search?: string;
};

export type Pick = {
	id: number;
	session_id: number;
	position: number;
	slot: SessionSlot;
	problem: Problem;
	target_probability: number;
	p_cal: number;
	picked_at: string;
};

export type Attempt = {
	id: number;
	source: Source;
	slot: Slot | null;
	problem: Problem;
	started_at: string;
	deadline: string;
	/** When the running timer was paused, or null while it is ticking. */
	paused_at: string | null;
	scored_at: string | null;
	accepted_at: string | null;
	accepted_submission_id: number | null;
	s: 0 | 1 | null;
	rated: boolean;
	p_cal: number | null;
	e_model: number | null;
	problem_rating: number | null;
	effective_rating: number | null;
	overall_after: number | null;
	key_idea: string | null;
	upsolved_at: string | null;
};

export type ScoredAttempt = Attempt & { rating: Rating };

export type Session = {
	id: number;
	tag: string;
	started_at: string;
	ended_at: string | null;
	next_slot: SessionSlot | null;
	picks: Pick[];
	attempts: Attempt[];
	overall: Rating;
};

export type Me = {
	id: number;
	email: string;
	cf_handle: string | null;
	/** The server's word on whether the rating seed has ever run. */
	seeded: boolean;
	rating: Rating;
	groups: { name: string; rating: number }[];
	history: { t: string; rating: number }[];
};

export type Skills = {
	overall: { rating: number };
	groups: { name: string; rating: number }[];
	tags: { tag: string; group: string; rating: number; rd: number; state: SkillState }[];
};

export type History = {
	sessions: {
		id: number;
		tag: string | null;
		started_at: string;
		ended_at: string | null;
		attempts: Attempt[];
	}[];
	attempts: Attempt[];
};

export type SeedResult = {
	rating: Rating;
	contests: { replayed: number; skipped: number };
	problems: { replayed: number; skipped: number; solved: number };
};

export type Counts = Record<string, number>;

const STATUS_TEXT: Record<number, string> = {
	400: 'That request was not valid.',
	403: 'You are not signed in through Cloudflare Access.',
	404: 'Not found.',
	405: 'That method is not allowed here.',
	409: 'That is not possible right now.',
	422: 'Nothing is available for that request.',
	500: 'The server hit an error.',
	502: 'Codeforces could not be reached.'
};

export class ApiError extends Error {
	readonly status: number;

	constructor(status: number, message: string) {
		super(message);
		this.name = 'ApiError';
		this.status = status;
	}
}

type Options = {
	method?: 'GET' | 'POST' | 'PUT' | 'PATCH';
	body?: unknown;
};

async function failureMessage(response: Response): Promise<string> {
	try {
		const body = await response.json();
		if (typeof body?.message === 'string' && body.message) return body.message;
	} catch {
		// Not JSON at all (a proxy's error page): fall through to the status text.
	}
	return STATUS_TEXT[response.status] ?? `Request failed (${response.status}).`;
}

async function request<T>(path: string, options: Options = {}): Promise<T> {
	const response = await fetch(`/api${path}`, {
		method: options.method ?? 'GET',
		headers: options.body === undefined ? undefined : { 'content-type': 'application/json' },
		body: options.body === undefined ? undefined : JSON.stringify(options.body)
	});
	if (!response.ok) throw new ApiError(response.status, await failureMessage(response));
	return (await response.json()) as T;
}

export const api = {
	me: () => request<Me>('/users/me'),

	setHandle: (cf_handle: string) =>
		request<{ cf_handle: string }>('/users/me', { method: 'PUT', body: { cf_handle } }),

	seed: () => request<SeedResult>('/users/me/seed', { method: 'POST' }),

	startSession: () => request<Session>('/sessions', { method: 'POST' }),

	/** null when no session is open (the normal state, not an error). */
	async currentSession(): Promise<Session | null> {
		try {
			return await request<Session>('/sessions/current');
		} catch (error) {
			if (error instanceof ApiError && error.status === 404) return null;
			throw error;
		}
	},

	nextPick: (sessionId: number, slot?: SessionSlot) =>
		request<Pick>(`/sessions/${sessionId}/next`, {
			method: 'POST',
			body: slot ? { slot } : undefined
		}),

	replacePick: (sessionId: number, slot: SessionSlot) =>
		request<Pick>(`/sessions/${sessionId}/slots/${slot}/replace`, { method: 'POST' }),

	cancelPick: (sessionId: number, pickId: number) =>
		request<Session>(`/sessions/${sessionId}/picks/${pickId}/cancel`, { method: 'POST' }),

	finishSession: (sessionId: number) =>
		request<Session>(`/sessions/${sessionId}/finish`, { method: 'POST' }),

	openPick: (pickId: number) =>
		request<Attempt>('/attempts', { method: 'POST', body: { pick_id: pickId } }),

	openProblem: (problemId: number) =>
		request<Attempt>('/attempts', { method: 'POST', body: { problem_id: problemId } }),

	done: (attemptId: number) =>
		request<ScoredAttempt>(`/attempts/${attemptId}/done`, { method: 'POST' }),

	giveUp: (attemptId: number) =>
		request<ScoredAttempt>(`/attempts/${attemptId}/give-up`, { method: 'POST' }),

	pause: (attemptId: number) =>
		request<Attempt>(`/attempts/${attemptId}/pause`, { method: 'POST' }),

	resume: (attemptId: number) =>
		request<Attempt>(`/attempts/${attemptId}/resume`, { method: 'POST' }),

	annotate: (attemptId: number, body: { key_idea?: string | null; upsolved?: boolean }) =>
		request<Attempt>(`/attempts/${attemptId}`, { method: 'PATCH', body }),

	skills: () => request<Skills>('/skills'),
	history: () => request<History>('/history'),

	syncCatalog: () => request<Counts>('/sync/catalog', { method: 'POST' }),
	syncSubmissions: () => request<Counts>('/sync/submissions', { method: 'POST' }),
	syncContests: () => request<Counts>('/sync/contests', { method: 'POST' })
};

/** Human-readable text for anything thrown by the client. */
export function errorText(error: unknown): string {
	if (error instanceof ApiError) return error.message;
	if (error instanceof Error) return error.message;
	return 'Something went wrong.';
}
