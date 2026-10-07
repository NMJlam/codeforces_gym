<script lang="ts">
	import AttemptCard from '#lib/components/attempt-card.svelte';
	import ProblemLine from '#lib/components/problem-line.svelte';
	import Button from '#lib/components/ui/button.svelte';
	import Panel from '#lib/components/ui/panel.svelte';
	import SegmentedControl from '#lib/components/segmented-control.svelte';
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import { api, type Me, type SessionSlot } from '#lib/api.js';
	import { current } from '#lib/current-session.svelte.js';
	import { SLOT_LABELS, formatChance, formatWhen } from '#lib/format.js';
	import { cn } from '#lib/utils.js';

	const SLOTS = ['warmup', 'main', 'stretch'] as const;
	const SLOT_HINTS: Record<SessionSlot, string> = {
		warmup: 'A solved warm-up moves on to main; a failed one earns another warm-up.',
		main: 'Roughly even odds.',
		stretch: 'You will usually miss a stretch problem. That is the point.'
	};

	// Only the no-session panel needs this, and only to choose between "start a
	// session" and "there is nothing to start yet": seeding is a hard
	// precondition of POST /sessions, so offering the button first would answer
	// with a 409. A failed /users/me leaves `me` null, which keeps the button —
	// the same thing the page did before it could ask.
	let me = $state<Me | null>(null);
	let meFailed = $state(false);
	$effect(() => {
		if (current.loaded && !current.session && me === null && !meFailed) void loadMe();
	});

	async function loadMe() {
		try {
			me = await api.me();
		} catch {
			meFailed = true;
		}
	}

	// The slot the picker will pick. It follows the session's suggestion until
	// the user moves it; after every pick the session reloads and resets it.
	let chosen = $state<SessionSlot | null>(null);

	const session = $derived(current.session);
	const pick = $derived(current.pick);
	const running = $derived(current.attempt);
	const scored = $derived(session?.attempts.filter((attempt) => attempt.scored_at !== null) ?? []);
	const offPlan = $derived(session?.next_slot != null && chosen !== session.next_slot);
	// `offPlan` implies a suggestion exists, which TS cannot see through a derived.
	const nextLabel = $derived(
		session?.next_slot ? SLOT_LABELS[session.next_slot].toLowerCase() : null
	);

	// Default the picker to whatever the session suggests, so the suggested
	// pick is still one click away.
	$effect(() => {
		chosen = session?.next_slot ?? null;
	});
</script>

<main class="space-y-6">
	{#if current.error}
		<p class="border-destructive/40 bg-destructive/10 text-destructive rounded-lg border p-3 text-sm">
			{current.error}
		</p>
	{/if}

	{#if !current.loaded}
		<p class="text-muted-foreground">Loading…</p>
	{:else}
		{#if running}
			<AttemptCard attempt={running} />
		{/if}

		{#if current.lastResult && session}
			<Panel
				title={current.lastResult.s === 1 ? 'Solved' : 'Failed'}
				description="Recorded against {current.lastResult.problem.name}"
			>
				<p class="text-sm">
					Overall rating
					{Math.round(current.lastResult.rating.rating)} ± {Math.round(current.lastResult.rating.rd)}
					{#if current.lastResult.overall_after !== null}
						(after this attempt: {Math.round(current.lastResult.overall_after)})
					{/if}
					{#if current.lastResult.s === 0}
						· add the key idea below while it is fresh.
					{/if}
				</p>
			</Panel>
		{/if}

		{#if !session}
			{#if me && !me.seeded}
				<Panel
					title="Set up first"
					description="Starting a session needs seeded ratings: the topic draw reads them. Seeding replays your Codeforces contests once."
				>
					<a href="/profile/setup">
						<Button>Set your handle and seed</Button>
					</a>
				</Panel>
			{:else}
				<Panel
					title="No session open"
					description="One topic, a warm-up you should mostly solve, a main problem at even odds, then a stretch."
				>
					<div class="flex flex-wrap items-center gap-3">
						<Button onclick={() => current.start()} disabled={current.busy}>Start a session</Button>
						<a class="text-muted-foreground text-sm hover:underline" href="/profile/setup">
							First time? Set your handle and seed the ratings.
						</a>
					</div>
				</Panel>
			{/if}
		{:else}
			<Panel
				description="Started {formatWhen(session.started_at)} · overall {Math.round(
					session.overall.rating
				)} ± {Math.round(session.overall.rd)}"
			>
				{#snippet actions()}
					<div class="flex items-center gap-2">
						<Button
							variant="outline"
							size="sm"
							disabled={current.busy || Boolean(running)}
							title={running ? 'Finish the running attempt first' : 'Close the session'}
							onclick={() => current.finish()}
						>
							Finish
						</Button>
					</div>
				{/snippet}
			</Panel>

			{#if !running}
				{#if pick}
					<Panel
						title="Picked for {SLOT_LABELS[pick.slot].toLowerCase()}"
						description="Nothing is timed yet: the clock starts when you open it."
					>
						{#snippet actions()}
							<div class="flex flex-wrap items-center gap-2">
								<Button
									variant="outline"
									class="px-2.5"
									onclick={() => current.cancelPick(pick.id)}
									disabled={current.busy}
									aria-label="Back"
									title="Back: drop this pick and choose a slot again. Nothing is recorded."
								>
									<ArrowLeft size={16} />
								</Button>
								<Button onclick={() => current.openPick(pick.id)} disabled={current.busy}>
									Open
								</Button>
								<Button
									variant="outline"
									onclick={() => current.replace(pick.slot)}
									disabled={current.busy}
									title="Mark this problem seen as a skip and pick another at the same chance"
								>
									Replace
								</Button>
							</div>
						{/snippet}
						<ProblemLine problem={pick.problem} />
						<p class="text-muted-foreground text-sm">
							target chance {formatChance(pick.target_probability)} · the model put you at {formatChance(
								pick.p_cal
							)} on this problem
						</p>
					</Panel>
				{:else}
					<Panel
						title={session.next_slot
							? `Next up: the ${SLOT_LABELS[session.next_slot].toLowerCase()} problem`
							: 'Every slot is done'}
						description={session.next_slot
							? 'The session suggests a slot; pick any of the three.'
							: 'The planned run is over — pick any slot, or finish the session.'}
					>
						<div class="flex flex-wrap items-center gap-3">
							<SegmentedControl
								bind:value={chosen}
								label="Slot"
								items={SLOTS.map((slot) => ({
									value: slot,
									label: SLOT_LABELS[slot],
									dot: slot === session.next_slot ? "The session's suggestion" : undefined
								}))}
							/>
							<Button
								onclick={() => chosen && current.next(chosen)}
								disabled={current.busy || !chosen}
							>
								Go
							</Button>
						</div>
						<p class={cn('mt-3 text-sm', offPlan ? 'text-foreground' : 'text-muted-foreground')}>
							{#if chosen === null}
								Pick a slot to continue, or finish the session.
							{:else if offPlan}
								<strong>Off-plan:</strong> the session suggests {nextLabel}. {SLOT_HINTS[chosen]}
							{:else}
								{SLOT_HINTS[chosen]}
							{/if}
						</p>
					</Panel>
				{/if}
			{/if}
		{/if}

		{#if scored.length}
			<section class="space-y-3">
				<h2 class="font-medium">This session</h2>
				{#each scored as attempt (attempt.id)}
					<AttemptCard {attempt} />
				{/each}
			</section>
		{/if}
	{/if}
</main>
