/**
 * Date, duration and slot formatting. Intl handles locales; these exist because
 * the app shows the same handful of shapes everywhere (a countdown, a "3 days
 * ago", the name of a slot) and they should not drift between pages.
 */

import type { Slot } from '#lib/api.js';

/** Slot keys are API values ("warmup"); the UI never shows them raw. */
export const SLOT_LABELS: Record<Slot, string> = {
	warmup: 'Warm-up',
	main: 'Main',
	stretch: 'Stretch',
	recall: 'Recall'
};

const DATE_TIME = new Intl.DateTimeFormat(undefined, {
	day: 'numeric',
	month: 'short',
	year: 'numeric',
	hour: '2-digit',
	minute: '2-digit'
});

const DAY = new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short', year: 'numeric' });

export function formatWhen(iso: string | null): string {
	return iso ? DATE_TIME.format(new Date(iso)) : '—';
}

export function formatDay(iso: string | null): string {
	return iso ? DAY.format(new Date(iso)) : '—';
}

/** "in 3 days" / "2 hours ago", coarse enough to stay readable. */
export function formatRelative(iso: string, now = Date.now()): string {
	const seconds = (new Date(iso).getTime() - now) / 1000;
	const units: [Intl.RelativeTimeFormatUnit, number][] = [
		['second', 60],
		['minute', 60],
		['hour', 24],
		['day', 30],
		['month', 12],
		['year', Number.POSITIVE_INFINITY]
	];
	const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });
	let value = seconds;
	for (const [unit, size] of units) {
		if (Math.abs(value) < size) return rtf.format(Math.round(value), unit);
		value /= size;
	}
	return rtf.format(Math.round(value), 'year');
}

/** The 45-minute countdown. Negative input clamps to 00:00. */
export function formatCountdown(ms: number): string {
	const total = Math.max(0, Math.floor(ms / 1000));
	const minutes = Math.floor(total / 60);
	const seconds = total % 60;
	return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}

/** 0.8 -> "80%", 0.805 -> "81%". */
export function formatChance(fraction: number): string {
	return `${Math.round(fraction * 100)}%`;
}
