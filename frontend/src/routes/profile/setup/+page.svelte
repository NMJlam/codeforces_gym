<script lang="ts">
	import Badge from '#lib/components/ui/badge.svelte';
	import Button from '#lib/components/ui/button.svelte';
	import Input from '#lib/components/ui/input.svelte';
	import Panel from '#lib/components/ui/panel.svelte';
	import { api, errorText, type Counts, type Me, type SeedResult } from '#lib/api.js';

	let me = $state<Me | null>(null);
	let error = $state('');
	let notice = $state('');
	let busy = $state('');
	let handle = $state('');
	let seedResult = $state<SeedResult | null>(null);
	let syncResult = $state<{ label: string; counts: Counts } | null>(null);

	async function loadMe() {
		try {
			const loaded = await api.me();
			me = loaded;
			// Only seed the input: a background refresh must never overwrite what
			// the user is typing.
			if (!handle) handle = loaded.cf_handle ?? '';
		} catch (failure) {
			error = errorText(failure);
		}
	}

	/** One busy flag and one error slot for every button on the page. */
	async function run<T>(label: string, action: () => Promise<T>): Promise<T | null> {
		busy = label;
		error = '';
		notice = '';
		try {
			return await action();
		} catch (failure) {
			error = errorText(failure);
			return null;
		} finally {
			busy = '';
		}
	}

	async function saveHandle() {
		const saved = await run('handle', () => api.setHandle(handle));
		if (saved) {
			notice = `Saved “${saved.cf_handle}”.`;
			await loadMe();
		}
	}

	async function seed() {
		const result = await run('seed', () => api.seed());
		if (result) {
			seedResult = result;
			await loadMe();
		}
	}

	async function sync(label: string, action: () => Promise<Counts>) {
		const counts = await run(label, action);
		if (counts) syncResult = { label, counts };
	}

	$effect(() => {
		void loadMe();
	});
</script>

<main class="space-y-6">
	{#if error}
		<p class="border-destructive/40 bg-destructive/10 text-destructive rounded-lg border p-3 text-sm">
			{error}
		</p>
	{/if}

	<Panel
		title="Codeforces handle"
		description="Used for every Codeforces API call: seeding, Done checks, submissions and contests."
	>
		<div class="flex flex-wrap items-center gap-2">
			<Input bind:value={handle} placeholder="your CF handle" class="max-w-64" />
			<Button onclick={saveHandle} disabled={busy !== '' || !handle.trim()}>
				{busy === 'handle' ? 'Saving…' : 'Save handle'}
			</Button>
			{#if me}
				<span class="text-muted-foreground text-sm">signed in as {me.email}</span>
			{/if}
		</div>
		{#if notice}
			<p class="text-sm">{notice}</p>
		{/if}
		<p class="text-muted-foreground text-sm">
			Changing it is refused (409) once your ratings are seeded: the seeded history belongs to one
			Codeforces account, and mixing two would corrupt every later contest check.
		</p>
	</Panel>

	<Panel
		title="Seed the ratings"
		description="One-time. Replays your Codeforces contest history as rated attempts and starts the calibration at its priors."
	>
		<div class="flex flex-wrap items-center gap-3">
			<Button onclick={seed} disabled={busy !== '' || !me?.cf_handle || me?.seeded}>
				{busy === 'seed' ? 'Replaying…' : 'Seed from Codeforces'}
			</Button>
			{#if !me?.cf_handle}
				<span class="text-muted-foreground text-sm">Save a handle first.</span>
			{:else if me.seeded}
				<span class="text-muted-foreground text-sm">
					Already seeded. This is one-time: the replay is what the ratings are built from.
				</span>
			{/if}
		</div>
		<p class="text-muted-foreground text-sm">
			Runs a handful of Codeforces calls (paced at ~1 call / 2 s), so expect a few seconds. It needs
			the catalog synced for the contests you entered, and it stays one transaction: a failure
			leaves nothing half-seeded.
		</p>
		{#if seedResult}
			<div class="flex flex-wrap gap-2">
				<Badge tone="primary">
					rating {Math.round(seedResult.rating.rating)} ± {Math.round(seedResult.rating.rd)}
				</Badge>
				<Badge tone="muted">contests replayed {seedResult.contests.replayed}</Badge>
				<Badge tone="muted">contests skipped {seedResult.contests.skipped}</Badge>
				<Badge tone="good">problems solved {seedResult.problems.solved}</Badge>
				<Badge tone="muted">problems replayed {seedResult.problems.replayed}</Badge>
				<Badge tone="muted">problems skipped {seedResult.problems.skipped}</Badge>
			</div>
		{/if}
	</Panel>

	<Panel title="Synchronisation" description="Always explicit — nothing polls Codeforces in the background.">
		<div class="flex flex-wrap gap-2">
			<Button
				variant="outline"
				onclick={() => sync('catalog', api.syncCatalog)}
				disabled={busy !== ''}
			>
				{busy === 'catalog' ? 'Syncing…' : 'Sync catalog'}
			</Button>
			<Button
				variant="outline"
				onclick={() => sync('submissions', api.syncSubmissions)}
				disabled={busy !== '' || !me?.cf_handle}
			>
				{busy === 'submissions' ? 'Syncing…' : 'Sync submissions'}
			</Button>
			<Button
				variant="outline"
				onclick={() => sync('contests', api.syncContests)}
				disabled={busy !== '' || !me?.cf_handle}
			>
				{busy === 'contests' ? 'Replaying…' : 'Sync contests'}
			</Button>
		</div>
		<dl class="text-muted-foreground grid gap-1 text-sm">
			<div>
				<dt class="text-foreground inline font-medium">Catalog</dt>
				<dd class="inline">
					problems, tags, contest metadata and each tag's emergence rating. The slowest one.
				</dd>
			</div>
			<div>
				<dt class="text-foreground inline font-medium">Submissions</dt>
				<dd class="inline">
					problems you already solved outside a session become seen (and never rated).
				</dd>
			</div>
			<div>
				<dt class="text-foreground inline font-medium">Contests</dt>
				<dd class="inline">
					replays rounds you entered that have no attempts yet, recording solves and failures
					alike. Safe to repeat.
				</dd>
			</div>
		</dl>
		{#if syncResult}
			<div class="flex flex-wrap items-center gap-2">
				<Badge tone="primary">{syncResult.label}</Badge>
				{#each Object.entries(syncResult.counts) as [key, value] (key)}
					<Badge tone="muted">{key.replaceAll('_', ' ')}: {value}</Badge>
				{/each}
			</div>
		{/if}
	</Panel>
</main>
