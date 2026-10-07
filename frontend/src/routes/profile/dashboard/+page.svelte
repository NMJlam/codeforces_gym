<script lang="ts">
	import { AreaChart, BarChart, LineChart, defaultChartPadding } from 'layerchart';
	import { curveLinearClosed } from 'd3-shape';
	import { goto } from '$app/navigation';
	import * as Tabs from '#lib/components/ui/tabs/index.js';
	import Button from '#lib/components/ui/button.svelte';
	import Panel from '#lib/components/ui/panel.svelte';
	import ContributionGraph from '#lib/components/contribution-graph.svelte';
	import SegmentedControl from '#lib/components/segmented-control.svelte';
	import { api, errorText, type Attempt, type Me } from '#lib/api.js';
	import { current } from '#lib/current-session.svelte.js';
	import { formatCountdown } from '#lib/format.js';

	const DAYS = { week: 7, month: 30, year: 365 } as const;

	let me = $state<Me | null>(null);
	let attempts = $state<Attempt[]>([]);
	let error = $state('');
	let activityError = $state('');
	let skillView = $state('radar');
	let sortBy = $state('name');
	let range = $state<keyof typeof DAYS>('month');

	async function loadMe() {
		try {
			me = await api.me();
		} catch (failure) {
			error = errorText(failure);
		}
	}

	// The calendar is the attempt log, not a separate endpoint: /history already
	// returns every attempt newest-first.
	async function loadActivity() {
		try {
			attempts = (await api.history()).attempts;
			activityError = '';
		} catch (failure) {
			activityError = errorText(failure);
		}
	}

	async function startSession() {
		await current.start();
		if (current.session) await goto('/session');
	}

	$effect(() => {
		void loadMe();
		void loadActivity();
	});

	// Radar is always A–Z: sorting its axes by rating turns every shape into the
	// same spiral, and a fixed order keeps it comparable across visits.
	const byRating = $derived(skillView === 'bars' && sortBy === 'rating');
	const groups = $derived(
		[...(me?.groups ?? [])]
			.sort((a, b) => (byRating ? b.rating - a.rating : a.name.localeCompare(b.name)))
			.map((g) => ({ ...g, rating: Math.round(g.rating) }))
	);
	// Radar starts just below the weakest group, so differences are visible.
	const radarDomain = $derived(
		groups.length
			? [
					Math.min(...groups.map((g) => g.rating)) - 100,
					Math.max(...groups.map((g) => g.rating)) + 50
				]
			: [0, 100]
	);
	// The radar's tick labels sit under the shape, so this is where its scale is
	// stated in words.
	const radarLabel = $derived(
		`Topic group ratings on a radar, from ${Math.round(radarDomain[0])} to ${Math.round(radarDomain[1])}`
	);
	// Rating is a step function: it holds between attempts. Pin both ends of
	// the range so the line spans it even with few (or no) attempts.
	const history = $derived.by(() => {
		if (!me) return [];
		const now = Date.now();
		const start = now - DAYS[range] * 86_400_000;
		const points = me.history.map((h) => ({ date: new Date(h.t), rating: Math.round(h.rating) }));
		const inRange = points.filter((p) => p.date.getTime() >= start);
		const current_rating = Math.round(me.rating.rating);
		const atStart =
			points.findLast((p) => p.date.getTime() < start)?.rating ?? inRange[0]?.rating ?? current_rating;
		return [
			{ date: new Date(start), rating: atStart },
			...inRange,
			{ date: new Date(now), rating: current_rating }
		];
	});
	// Not a guess any more: the server says whether the seed has ever run, which
	// the rating and group offsets cannot tell apart from the new-user prior.
	const unseeded = $derived(me !== null && !me.seeded);
	// The header's line is about the rating still being the prior, which a seed
	// that replayed no contest also leaves in place.
	const provisional = $derived(me !== null && me.history.length === 0);
</script>

<main class="space-y-6">
	{#if error}
		<p class="text-destructive">{error}</p>
	{:else if !me}
		<p class="text-muted-foreground">Loading…</p>
	{:else}
		<header class="space-y-1">
			{#if me.cf_handle}
				<a
					class="text-muted-foreground text-sm hover:underline"
					href="https://codeforces.com/profile/{me.cf_handle}"
					target="_blank"
					rel="noreferrer"
				>
					{me.cf_handle}
				</a>
			{:else}
				<p class="text-muted-foreground text-sm">{me.email}</p>
			{/if}
			<h1 class="text-5xl font-semibold tabular-nums">
				{Math.round(me.rating.rating)}
				<span class="text-muted-foreground text-xl">± {Math.round(me.rating.rd)}</span>
			</h1>
			{#if !me.cf_handle}
				<p class="text-destructive text-sm">
					No Codeforces handle yet — set one on the
					<a class="underline" href="/profile/setup">setup page</a> before seeding.
				</p>
			{:else if provisional}
				<p class="text-muted-foreground text-sm">Provisional: no rated attempts yet.</p>
			{/if}
		</header>

		<Panel title="Today" description={current.headline}>
			{#snippet actions()}
				{#if current.attempt}
					<span class="text-3xl font-semibold tabular-nums">
						{formatCountdown(current.remaining)}
					</span>
				{:else if current.session}
					<Button onclick={() => goto('/session')} disabled={current.busy}>Continue session</Button>
				{:else if unseeded}
					<Button onclick={() => goto('/profile/setup')}>Set up</Button>
				{:else}
					<Button onclick={startSession} disabled={current.busy}>Start a session</Button>
				{/if}
			{/snippet}
			<div class="flex flex-wrap items-center gap-3 text-sm">
				<a class="text-primary hover:underline" href="/session">Session</a>
				<a class="text-muted-foreground hover:underline" href="/profile/topics">Topics</a>
				<a class="text-muted-foreground hover:underline" href="/profile/history">History</a>
				{#if unseeded}
					<span class="text-muted-foreground">
						Unseeded — replay your Codeforces contests on
						<a class="underline" href="/profile/setup">setup</a> to get real ratings.
					</span>
				{/if}
			</div>
			{#if current.error}
				<p class="text-destructive text-sm">{current.error}</p>
			{/if}
		</Panel>

		<Panel
			title="Activity"
			description="One square per day, shaded by how much you attempted. Seeded contest replays sit on the day the contest ran."
		>
			{#if activityError}
				<p class="text-destructive text-sm">{activityError}</p>
			{:else}
				<ContributionGraph {attempts} />
			{/if}
		</Panel>

		<Tabs.Root bind:value={skillView} class="contents">
			<Panel title="Topic groups">
				{#snippet actions()}
					<div class="flex flex-wrap gap-3">
						{#if skillView === 'bars'}
							<SegmentedControl
								bind:value={sortBy}
								label="Sort groups"
								items={[
									{ value: 'name', label: 'A–Z' },
									{ value: 'rating', label: 'By rating' }
								]}
							/>
						{/if}
						<Tabs.List>
							<Tabs.Tab value="radar">Radar</Tabs.Tab>
							<Tabs.Tab value="bars">Bars</Tabs.Tab>
						</Tabs.List>
					</div>
				{/snippet}
				<Tabs.Panel value="radar" class="space-y-3">
					<LineChart
						data={groups}
						x="name"
						y="rating"
						yDomain={radarDomain}
						radial
						series={[
							{ key: 'rating', color: 'var(--color-primary)', props: { class: 'fill-primary/30' } }
						]}
						props={{
							spline: { curve: curveLinearClosed },
							// width enables word-wrap; truncate:false stops layerchart from
							// ellipsizing to that width instead (e.g. "Constructive & interactive")
							xAxis: { tickLength: 0, tickLabelProps: { width: 110, truncate: false } },
							// The radial y ticks are drawn down the middle, where the polygon
							// covers them, so they are blanked and the range is stated below.
							yAxis: { ticks: 4, format: () => '' },
							grid: { radialY: 'linear' },
							highlight: { lines: false },
							tooltip: { context: { mode: 'voronoi' } },
							svg: { role: 'img', 'aria-label': radarLabel }
						}}
						padding={defaultChartPadding({ top: 30, bottom: 30 })}
						height={380}
					/>
				</Tabs.Panel>
				<Tabs.Panel value="bars" class="space-y-3">
					<BarChart
						data={groups}
						x="name"
						y="rating"
						labels
						props={{
							xAxis: { tickLabelProps: { width: 110, truncate: false } },
							svg: { role: 'img', 'aria-label': 'Topic group ratings, one bar per group' }
						}}
						height={340}
					/>
				</Tabs.Panel>
				<p class="text-muted-foreground text-sm">
					Ratings run {Math.round(radarDomain[0])}–{Math.round(radarDomain[1])}. Per-tag states live on
					<a class="underline" href="/profile/topics">Topics</a>.
				</p>
			</Panel>
		</Tabs.Root>

		<Panel title="Rating over time">
			{#snippet actions()}
				<SegmentedControl
					bind:value={range}
					label="Range"
					items={[
						{ value: 'week', label: 'Week' },
						{ value: 'month', label: 'Month' },
						{ value: 'year', label: 'Year' }
					]}
				/>
			{/snippet}
			<AreaChart
				data={history}
				x="date"
				y="rating"
				brush
				motion={{ type: 'spring' }}
				props={{
					xAxis: { tickMultiline: true },
					svg: {
						class: 'cursor-crosshair',
						role: 'img',
						'aria-label': `Overall rating over the last ${range}`
					}
				}}
				padding={defaultChartPadding({ left: 25 })}
				height={300}
			/>
		</Panel>
	{/if}
</main>
