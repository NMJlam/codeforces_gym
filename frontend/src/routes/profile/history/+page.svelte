<script lang="ts">
	import AttemptCard from '#lib/components/attempt-card.svelte';
	import ProblemLine from '#lib/components/problem-line.svelte';
	import Badge from '#lib/components/ui/badge.svelte';
	import Panel from '#lib/components/ui/panel.svelte';
	import { api, errorText, type History } from '#lib/api.js';
	import { SLOT_LABELS, formatWhen } from '#lib/format.js';

	let history = $state<History | null>(null);
	let error = $state('');

	$effect(() => {
		api
			.history()
			.then((body) => (history = body))
			.catch((failure) => (error = errorText(failure)));
	});

	// A session counts once something was attempted in it. One that was opened and
	// closed with nothing in it is not history, so it is not listed.
	const sessions = $derived(
		(history?.sessions ?? []).filter((session) => session.attempts.length > 0)
	);
	const attempts = $derived(history?.attempts ?? []);
	const rated = $derived(attempts.filter((attempt) => attempt.scored_at !== null));
</script>

<main class="space-y-6">
	{#if error}
		<p class="text-destructive">{error}</p>
	{:else if !history}
		<p class="text-muted-foreground">Loading…</p>
	{:else if !attempts.length}
		<Panel title="Nothing yet" description="Attempts show up here as soon as a timer starts.">
			<a class="text-primary text-sm hover:underline" href="/session">Start a session</a>
		</Panel>
	{:else}
		<Panel
			title="History"
			description="{rated.length} rated attempt(s), {rated.filter((attempt) => attempt.s === 1)
				.length} solved. Contest replays from the seed are included."
		>
			<p class="text-muted-foreground text-sm">
				Problems never carry their tags here, and an attempt that is still running shows no
				editorial until it is scored.
			</p>
		</Panel>

		{#if sessions.length}
			<details class="rounded-xl border">
				<summary
					class="cursor-pointer px-4 py-3 text-sm font-medium select-none hover:text-muted-foreground"
				>
					Sessions ({sessions.length})
				</summary>
				<div class="space-y-6 p-4 pt-0">
					{#each sessions as session (session.id)}
						<Panel
							title={session.tag ?? 'session'}
							description="Started {formatWhen(session.started_at)} · {session.ended_at
								? `ended ${formatWhen(session.ended_at)}`
								: 'still open'}"
						>
							<details>
								<summary
									class="text-muted-foreground cursor-pointer text-sm select-none hover:text-foreground"
								>
									{session.attempts.length} attempt{session.attempts.length === 1 ? '' : 's'} ·
									{session.attempts.filter((attempt) => attempt.s === 1).length} solved
								</summary>
								<div class="mt-3 space-y-3">
									{#each session.attempts as attempt (attempt.id)}
										<AttemptCard {attempt} />
									{/each}
								</div>
							</details>
						</Panel>
					{/each}
				</div>
			</details>
		{/if}

		<Panel title="Every attempt" description="Newest first.">
			<div class="overflow-x-auto">
				<table class="w-full text-sm">
					<thead class="text-muted-foreground text-left text-xs">
						<tr class="border-b">
							<th class="px-2.5 py-2 font-medium">When</th>
							<th class="px-2.5 py-2 font-medium">Problem</th>
							<th class="px-2.5 py-2 font-medium">Source</th>
							<th class="px-2.5 py-2 font-medium">Result</th>
							<th class="px-2.5 py-2 text-right font-medium">Rating after</th>
							<th class="px-2.5 py-2 font-medium">Editorial</th>
						</tr>
					</thead>
					<tbody>
						{#each attempts as attempt (attempt.id)}
							<tr class="border-b border-border/50">
								<td class="text-muted-foreground px-2.5 py-2 whitespace-nowrap">
									{formatWhen(attempt.started_at)}
								</td>
								<td class="px-2.5 py-2"><ProblemLine problem={attempt.problem} /></td>
								<td class="px-2.5 py-2">
									<Badge tone="muted">
										{attempt.source === 'session'
											? (attempt.slot ? SLOT_LABELS[attempt.slot] : 'session')
											: attempt.source}
									</Badge>
								</td>
								<td class="px-2.5 py-2">
									{#if attempt.scored_at === null}
										<Badge tone="primary">running</Badge>
									{:else if attempt.s === 1}
										<Badge tone="good">solved</Badge>
									{:else}
										<Badge tone="bad">failed</Badge>
									{/if}
								</td>
								<td class="px-2.5 py-2 text-right tabular-nums">
									{attempt.overall_after === null ? '—' : Math.round(attempt.overall_after)}
								</td>
								<td class="px-2.5 py-2">
									{#if attempt.problem.editorial_search}
										<a
											class="text-primary hover:underline"
											target="_blank"
											rel="noreferrer"
											href="https://duckduckgo.com/?q={encodeURIComponent(
												attempt.problem.editorial_search
											)}"
										>
											search
										</a>
									{:else}
										<span class="text-muted-foreground">—</span>
									{/if}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</Panel>
	{/if}
</main>
