<script lang="ts">
	import AttemptNotesDialog from '#lib/components/attempt-notes-dialog.svelte';
	import ProblemLine from '#lib/components/problem-line.svelte';
	import Badge from '#lib/components/ui/badge.svelte';
	import Button from '#lib/components/ui/button.svelte';
	import Input from '#lib/components/ui/input.svelte';
	import Panel from '#lib/components/ui/panel.svelte';
	import { api, errorText, type Attempt, type History } from '#lib/api.js';
	import { SLOT_LABELS, formatWhen } from '#lib/format.js';

	// One page of the log per request. Searching is the server's job — problem
	// name, "1234A" handle, index, key idea — so a log that only grows never
	// travels to the browser whole.
	const PER_PAGE = 25;
	const SEARCH_DEBOUNCE_MS = 250;

	let history = $state<History | null>(null);
	let error = $state('');
	let loading = $state(false);

	/** What is in the search box. */
	let query = $state('');
	/** The settled box and the page are the request the table is showing. */
	let search = $state('');
	let page = $state(1);

	let notes = $state<Attempt | null>(null);
	let notesOpen = $state(false);

	function openNotes(attempt: Attempt) {
		notes = attempt;
		notesOpen = true;
	}

	// Typing restarts the timer; only the settled value becomes a request, and a
	// new search always starts at the first page.
	$effect(() => {
		const next = query.trim();
		const handle = setTimeout(() => {
			if (next === search) return;
			search = next;
			page = 1;
		}, SEARCH_DEBOUNCE_MS);
		return () => clearTimeout(handle);
	});

	// One request counter for the whole page: a reply that a newer request has
	// superseded is dropped, so keystrokes cannot land out of order.
	let latest = 0;

	async function load(wanted: string, wantedPage: number) {
		const id = ++latest;
		loading = true;
		try {
			const body = await api.history({ q: wanted, page: wantedPage, per_page: PER_PAGE });
			if (id !== latest) return;
			history = body;
			// The note dialog stays open across a save, so its row has to become the
			// freshly-stored one. A row that is not on this page (the log moved on)
			// leaves the dialog's copy alone: it is still the right attempt.
			notes = body.attempts.find((row) => row.id === notes?.id) ?? notes;
			error = '';
		} catch (failure) {
			if (id === latest) error = errorText(failure);
		} finally {
			if (id === latest) loading = false;
		}
	}

	$effect(() => {
		void load(search, page);
	});

	const attempts = $derived(history?.attempts ?? []);
	const total = $derived(history?.attempts_total ?? 0);
	const pages = $derived(Math.max(1, Math.ceil(total / PER_PAGE)));
	const first = $derived(total === 0 ? 0 : (history?.page ?? 1) * PER_PAGE - PER_PAGE + 1);
	const last = $derived(total === 0 ? 0 : first + attempts.length - 1);
	// The pager describes the response that is on screen, never the request in
	// flight: during a load, "26–50 of 156" and its rows still agree.
	const shown = $derived(history?.page ?? 1);
	// An empty log and an empty search are different pages: only the first one
	// gets "start a session".
	const nothingYet = $derived(history !== null && total === 0 && history.q === '');
</script>

<main class="space-y-6">
	{#if error}
		<p class="text-destructive">{error}</p>
	{:else if !history}
		<p class="text-muted-foreground">Loading…</p>
	{:else if nothingYet}
		<Panel title="Nothing yet" description="Attempts show up here as soon as a timer starts.">
			<a class="text-primary text-sm hover:underline" href="/session">Start a session</a>
		</Panel>
	{:else}
		<Panel
			title="History"
			description="{history.rated_total} rated attempt(s), {history.solved_total} solved. Contest
				replays from the seed are included."
		>
			<p class="text-muted-foreground text-sm">
				Problems never carry their tags here, and an attempt that is still running shows no
				editorial until it is scored.
			</p>
		</Panel>

		<Panel title="Every attempt" description="Newest first.">
			{#snippet actions()}
				<div class="flex items-center gap-2">
					<label class="sr-only" for="attempt-search">Search attempts</label>
					<Input
						id="attempt-search"
						bind:value={query}
						placeholder="Problem name, 1234A or a note"
						class="w-64"
					/>
					{#if query}
						<Button variant="ghost" size="sm" onclick={() => (query = '')}>Clear</Button>
					{/if}
				</div>
			{/snippet}

			{#if attempts.length}
				<div class="overflow-x-auto">
					<table class="w-full text-sm">
						<thead class="text-muted-foreground text-left text-xs">
							<tr class="border-b">
								<th class="px-2.5 py-2 font-medium">When</th>
								<th class="px-2.5 py-2 font-medium">Problem</th>
								<th class="px-2.5 py-2 font-medium">Source</th>
								<th class="px-2.5 py-2 font-medium">Result</th>
								<th class="px-2.5 py-2 text-right font-medium">Rating after</th>
								<th class="px-2.5 py-2 font-medium">Notes</th>
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
												: attempt.source === 'contest'
													? 'contest'
													: 'self-selected'}
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
										{#if attempt.scored_at === null}
											<span class="text-muted-foreground" title="Notes open once it is scored"
												>—</span
											>
										{:else}
											<Button variant="ghost" size="sm" onclick={() => openNotes(attempt)}>
												{attempt.key_idea ? 'View notes' : 'Add note'}
											</Button>
										{/if}
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
			{/if}

			{#if total > 0}
				<div class="flex flex-wrap items-center justify-between gap-3 text-sm">
					<p class="text-muted-foreground">
						{first}–{last} of {total} attempt{total === 1 ? '' : 's'}{history.q
							? ` matching “${history.q}”`
							: ''}
					</p>
					<div class="flex items-center gap-2">
						<Button
							variant="outline"
							size="sm"
							disabled={shown <= 1 || loading}
							onclick={() => (page = shown - 1)}
						>
							Previous
						</Button>
						<span class="text-muted-foreground tabular-nums">Page {shown} of {pages}</span>
						<Button
							variant="outline"
							size="sm"
							disabled={shown >= pages || loading}
							onclick={() => (page = shown + 1)}
						>
							Next
						</Button>
					</div>
				</div>
			{:else}
				<p class="text-muted-foreground text-sm">No attempt matches “{history.q}”.</p>
			{/if}
		</Panel>
	{/if}

	<AttemptNotesDialog
		attempt={notes}
		bind:open={notesOpen}
		onsaved={() => void load(search, page)}
	/>
</main>
