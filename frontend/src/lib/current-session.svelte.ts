/**
 * The open session and the attempt being timed, shared by the dashboard and the
 * session page.
 *
 * The timer is server-authoritative: the countdown here is only a view of the
 * attempt's `deadline`, and when it reaches zero the store asks the API for the
 * session — every endpoint that touches an attempt scores a run-out timer
 * first, so the failure is recorded without the client having to decide.
 *
 * Pausing is the same idea from the other side: the server freezes the deadline
 * while `paused_at` is set, so the countdown here freezes at that instant and
 * resumes against the extended deadline.
 */

import { api, errorText, type Attempt, type ScoredAttempt, type Session, type SessionSlot } from '#lib/api.js';
import { SLOT_LABELS, formatCountdown } from '#lib/format.js';

const TICK_MS = 1000;

class CurrentSession {
	/** The open session, or null when there is none. */
	session = $state<Session | null>(null);
	/** A self-selected attempt has no session, so it is tracked separately. */
	standalone = $state<Attempt | null>(null);
	/** The last scored attempt, so its result stays on screen after scoring. */
	lastResult = $state<ScoredAttempt | null>(null);
	/** A request is in flight: the buttons disable. */
	busy = $state(false);
	/** The last failure, shown next to whatever caused it. */
	error = $state('');
	/** Once loaded, "no session" is a fact rather than "still loading". */
	loaded = $state(false);
	/** Ticks once a second; the countdown and the expiry check both read it. */
	now = $state(Date.now());

	clock: number | null = null;
	expiryAsked = false;

	/** The attempt being timed right now, if any. */
	get attempt(): Attempt | null {
		return this.session?.attempts.find((attempt) => attempt.scored_at === null) ?? this.standalone;
	}

	/** The picked problem waiting to be opened (the API allows one at a time). */
	get pick() {
		return this.session?.picks[0] ?? null;
	}

	get remaining(): number {
		const attempt = this.attempt;
		if (!attempt) return 0;
		// While paused the deadline stops moving, so the countdown is frozen at
		// the moment of the pause rather than following the wall clock.
		const at = attempt.paused_at ? new Date(attempt.paused_at).getTime() : this.now;
		return new Date(attempt.deadline).getTime() - at;
	}

	get headline(): string {
		if (this.attempt) return `Attempt running — ${formatCountdown(this.remaining)} left`;
		if (!this.session) return 'No session open';
		if (this.session.ended_at) return 'Session finished';
		if (this.pick) return `A ${SLOT_LABELS[this.pick.slot].toLowerCase()} problem is picked and waiting`;
		if (this.session.next_slot) return `Next up: the ${SLOT_LABELS[this.session.next_slot].toLowerCase()} problem`;
		return 'Every slot is done — finish the session';
	}

	async load() {
		try {
			const session = await api.currentSession();
			this.session = session;
			if (session) {
				this.standalone = null;
			} else {
				// An orphan self-selected attempt is invisible to /sessions/current
				// and blocks starting a session, so find it in the attempt log.
				const history = await api.history();
				this.standalone = history.attempts.find((attempt) => attempt.scored_at === null) ?? null;
			}
			this.error = '';
		} catch (failure) {
			this.error = errorText(failure);
		} finally {
			this.loaded = true;
			if (this.attempt) this.startClock();
			else this.stopClock();
		}
	}

	async start() {
		const session = await this.run(() => api.startSession());
		if (session) {
			this.session = session;
			this.standalone = null;
			this.lastResult = null;
		}
	}

	async next(slot?: SessionSlot) {
		const session = this.session;
		if (!session) return;
		if (await this.run(() => api.nextPick(session.id, slot))) await this.load();
	}

	async replace(slot: SessionSlot) {
		const session = this.session;
		if (!session) return;
		if (await this.run(() => api.replacePick(session.id, slot))) await this.load();
	}

	/** Go back to the slot picker: drop a pick that was never opened. */
	async cancelPick(pickId: number) {
		const session = this.session;
		if (!session) return;
		const updated = await this.run(() => api.cancelPick(session.id, pickId));
		if (updated) this.session = updated;
	}

	async openPick(pickId: number) {
		const attempt = await this.run(() => api.openPick(pickId));
		if (attempt) {
			this.lastResult = null;
			await this.load();
		}
	}

	async openProblem(problemId: number) {
		const attempt = await this.run(() => api.openProblem(problemId));
		if (attempt) {
			this.standalone = attempt;
			this.lastResult = null;
			this.startClock();
		}
	}

	async done() {
		await this.score((attemptId) => api.done(attemptId));
	}

	async giveUp() {
		await this.score((attemptId) => api.giveUp(attemptId));
	}

	async pause() {
		const attempt = this.attempt;
		if (!attempt) return;
		if (await this.run(() => api.pause(attempt.id))) await this.load();
	}

	async resume() {
		const attempt = this.attempt;
		if (!attempt) return;
		if (await this.run(() => api.resume(attempt.id))) await this.load();
	}

	async annotate(
		attemptId: number,
		body: { key_idea?: string | null; upsolved?: boolean }
	): Promise<boolean> {
		// The caller closes whatever it opened on a successful save, so it needs
		// to know whether the write actually landed.
		if (await this.run(() => api.annotate(attemptId, body))) {
			await this.load();
			return true;
		}
		return false;
	}

	async finish() {
		const session = this.session;
		if (!session) return;
		// The finished session lives in History; this page only shows live state.
		if (await this.run(() => api.finishSession(session.id))) {
			this.lastResult = null;
			await this.load();
		}
	}

	/** Run a mutating call with one busy flag and one place for its error. */
	async run<T>(action: () => Promise<T>): Promise<T | null> {
		this.busy = true;
		this.error = '';
		try {
			return await action();
		} catch (failure) {
			this.error = errorText(failure);
			return null;
		} finally {
			this.busy = false;
		}
	}

	async score(call: (attemptId: number) => Promise<ScoredAttempt>) {
		const attempt = this.attempt;
		if (!attempt) return;
		const result = await this.run(() => call(attempt.id));
		if (result) {
			this.lastResult = result;
			await this.load();
		}
	}

	startClock() {
		if (this.clock) return;
		// Refresh before the first frame, so a countdown never renders against a
		// clock that has been sitting still since the page loaded.
		this.now = Date.now();
		this.clock = window.setInterval(() => this.tick(), TICK_MS);
	}

	/** Nothing is timed: stop ticking, so an idle tab does no work per second. */
	stopClock() {
		if (this.clock === null) return;
		window.clearInterval(this.clock);
		this.clock = null;
		this.expiryAsked = false;
	}

	tick() {
		this.now = Date.now();
		if (!this.attempt) {
			this.stopClock();
			return;
		}
		if (this.remaining <= 0 && !this.expiryAsked && !this.attempt.paused_at) {
			this.expiryAsked = true;
			void this.load();
		}
	}
}

export const current = new CurrentSession();
