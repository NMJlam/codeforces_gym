<script lang="ts">
	import AttemptCard from '#lib/components/attempt-card.svelte';
	import ProblemLine from '#lib/components/problem-line.svelte';
	import Button from '#lib/components/ui/button.svelte';
	import Input from '#lib/components/ui/input.svelte';
	import Panel from '#lib/components/ui/panel.svelte';
	import SegmentedControl from '#lib/components/segmented-control.svelte';
	import * as Tabs from '#lib/components/ui/tabs/index.js';
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

	let problemId = $state('');
	// Two ways to get a problem: the session's just-in-time pick, or one you
	// bring yourself. The picker is the first thing on the page, so neither is
	// hidden behind the other.
	let mode = $state<'recommended' | 'self'>('recommended');
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

	// A self-selected attempt has no session, so it is the only thing in play:
	// open on that picker rather than making the user find it.
	$effect(() => {
		if (current.standalone) mode = 'self';
	});

	// Default the picker to whatever the session suggests, so the recommended
	// pick is still one click away.
	$effect(() => {
		chosen = session?.next_slot ?? null;
	});

	// Digits only, so a typo cannot become a request that silently does nothing.
	const validId = $derived(/^\d+$/.test(problemId.trim()) && Number(problemId) > 0);

	function openChosenProblem() {
		if (validId) void current.openProblem(Number(problemId));
	}
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

		<Tabs.Root bind:value={mode} class="gap-6">
			<div class="flex flex-wrap items-center justify-between gap-3">
				<Tabs.List>
					<Tabs.Tab value="recommended">Recommended</Tabs.Tab>
					<Tabs.Tab value="self">Self-picked</Tabs.Tab>
				</Tabs.List>
				<p class="text-muted-foreground text-sm">
					{#if mode === 'self'}
						Your own problem, rated but never used to refit the calibration.
					{:else}
						One topic, a warm-up you should mostly solve, a main problem at even odds, then a stretch.
					{/if}
				</p>
			</div>

			<Tabs.Panel value="self" class="space-y-6">
				{#if !running}
					<Panel
						title="Your own problem"
						description="Needs the catalog’s problem id; unrated, untagged or already seen problems are refused. The clock starts the moment you open it."
					>
						<div class="flex flex-wrap gap-2">
							<Input
								bind:value={problemId}
								placeholder="problem id"
								class="max-w-40"
								onkeydown={(event) => event.key === 'Enter' && openChosenProblem()}
							/>
							<Button onclick={openChosenProblem} disabled={current.busy || !validId}>
								Start the timer
							</Button>
						</div>
						{#if problemId.trim() && !validId}
							<p class="text-destructive text-sm">A catalog problem id is digits only.</p>
						{/if}
					</Panel>
				{/if}
			</Tabs.Panel>

			<Tabs.Panel value="recommended" class="space-y-6">
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
							description="Start one to get a topic and a warm-up picked for you."
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
			</Tabs.Panel>
		</Tabs.Root>

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
