<script lang="ts">
	import type { Attempt } from '#lib/api.js';
	import Badge from '#lib/components/ui/badge.svelte';
	import Button from '#lib/components/ui/button.svelte';
	import NoteEditor from '#lib/components/note-editor.svelte';
	import ProblemLine from '#lib/components/problem-line.svelte';
	import { current } from '#lib/current-session.svelte.js';
	import { SLOT_LABELS, formatChance, formatCountdown, formatWhen } from '#lib/format.js';

	let { attempt }: { attempt: Attempt } = $props();

	const running = $derived(attempt.scored_at === null);
	const remaining = $derived(
		new Date(attempt.deadline).getTime() -
			(attempt.paused_at ? new Date(attempt.paused_at).getTime() : current.now)
	);
	// Slot for a session attempt, otherwise what the attempt was: a contest
	// replay or a problem the user chose.
	const kind = $derived(
		attempt.slot
			? SLOT_LABELS[attempt.slot]
			: attempt.source === 'contest'
				? 'contest'
				: 'self-selected'
	);
</script>

<article class="space-y-3 rounded-lg border p-3 {running ? 'border-primary/40 bg-primary/5' : ''}">
	<header class="flex flex-wrap items-start justify-between gap-3">
		<div class="min-w-0 space-y-1">
			<ProblemLine problem={attempt.problem} />
			<div class="flex flex-wrap items-center gap-2">
				<Badge tone="muted">{kind}</Badge>
				{#if attempt.p_cal !== null}
					<Badge tone="muted" title="Calibrated chance when it was picked">
						picked at {formatChance(attempt.p_cal)}
					</Badge>
				{/if}
				{#if running}
					<Badge tone={attempt.paused_at ? 'warn' : 'primary'}>
						{attempt.paused_at ? 'paused' : 'running'}
					</Badge>
				{:else if attempt.s === 1}
					<Badge tone="good">solved</Badge>
				{:else}
					<Badge tone="bad">failed</Badge>
				{/if}
				{#if attempt.overall_after !== null}
					<Badge tone="muted" title="Overall rating after this attempt">
						rating {Math.round(attempt.overall_after)}
					</Badge>
				{/if}
			</div>
		</div>

		{#if running}
			<div class="flex items-center gap-2">
				<span class="text-2xl font-semibold tabular-nums">{formatCountdown(remaining)}</span>
				{#if attempt.paused_at}
					<Button onclick={() => current.resume()} disabled={current.busy}>Resume</Button>
				{:else}
					<Button onclick={() => current.done()} disabled={current.busy}>Done</Button>
					<Button variant="outline" onclick={() => current.pause()} disabled={current.busy}>
						Pause
					</Button>
				{/if}
				<Button variant="outline" onclick={() => current.giveUp()} disabled={current.busy}>
					Give up
				</Button>
			</div>
		{/if}
	</header>

	{#if running}
		<p class="text-muted-foreground text-sm">
			{#if attempt.paused_at}
				Paused {formatWhen(attempt.paused_at)}. The clock is frozen; Resume picks it up where it
				stopped.
			{:else}
				Timer started {formatWhen(attempt.started_at)}. Pause the timer when you are interrupted.
				Done asks Codeforces for an Accepted inside these 45 minutes; letting it run out scores it
				as failed.
			{/if}
		</p>
	{:else}
		<div class="flex flex-wrap items-center gap-3 text-sm">
			{#if attempt.accepted_submission_id !== null}
				<a
					class="text-primary hover:underline"
					target="_blank"
					rel="noreferrer"
					href="https://codeforces.com/contest/{attempt.problem.contest_id}/submission/{attempt
						.accepted_submission_id}"
				>
					submission {attempt.accepted_submission_id}
				</a>
			{/if}
			{#if attempt.e_model !== null}
				<span class="text-muted-foreground" title="The model's chance before the attempt">
					model {formatChance(attempt.e_model)}
				</span>
			{/if}
			<span class="text-muted-foreground">scored {formatWhen(attempt.scored_at)}</span>
			{#if attempt.problem.editorial_search}
				<a
					class="text-primary hover:underline"
					target="_blank"
					rel="noreferrer"
					href="https://duckduckgo.com/?q={encodeURIComponent(attempt.problem.editorial_search)}"
				>
					{attempt.problem.editorial_search}
				</a>
			{/if}
		</div>

		<details class="text-sm">
			<summary class="text-muted-foreground cursor-pointer select-none hover:text-foreground">
				Notes{#if attempt.key_idea}&nbsp;· saved{/if}{#if attempt.upsolved_at}&nbsp;· upsolved{/if}
			</summary>
			<div class="mt-2 space-y-2">
				<NoteEditor {attempt} />
				<div class="flex flex-wrap gap-2">
					<Button
						size="sm"
						variant={attempt.upsolved_at ? 'primary' : 'outline'}
						title="Upsolving is logged but never rated"
						onclick={() => current.annotate(attempt.id, { upsolved: attempt.upsolved_at === null })}
						disabled={current.busy}
					>
						{attempt.upsolved_at ? 'Upsolved' : 'Mark upsolved'}
					</Button>
				</div>
			</div>
		</details>
	{/if}
</article>
