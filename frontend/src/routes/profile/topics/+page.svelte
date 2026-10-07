<script lang="ts">
	import * as Table from '#lib/components/ui/table/index.js';
	import Badge from '#lib/components/ui/badge.svelte';
	import Input from '#lib/components/ui/input.svelte';
	import Panel from '#lib/components/ui/panel.svelte';
	import SegmentedControl from '#lib/components/segmented-control.svelte';
	import { api, errorText, type SkillState, type Skills } from '#lib/api.js';

	type Tone = 'good' | 'bad' | 'warn' | 'muted';

	const TONE: Record<SkillState, Tone> = {
		strong: 'good',
		weak: 'bad',
		unknown: 'muted',
		not_yet_relevant: 'warn'
	};
	const LABEL: Record<SkillState, string> = {
		strong: 'strong',
		weak: 'weak',
		unknown: 'unknown',
		not_yet_relevant: 'not yet relevant'
	};

	let skills = $state<Skills | null>(null);
	let error = $state('');
	let filter = $state<'all' | SkillState>('all');
	let query = $state('');

	$effect(() => {
		api
			.skills()
			.then((body) => (skills = body))
			.catch((failure) => (error = errorText(failure)));
	});

	const counts = $derived.by(() => {
		const tally: Record<string, number> = { all: skills?.tags.length ?? 0 };
		for (const tag of skills?.tags ?? []) tally[tag.state] = (tally[tag.state] ?? 0) + 1;
		return tally;
	});

	const rows = $derived(
		[...(skills?.tags ?? [])]
			.filter((tag) => filter === 'all' || tag.state === filter)
			.filter((tag) => {
				const needle = query.trim().toLowerCase();
				return (
					!needle ||
					tag.tag.toLowerCase().includes(needle) ||
					tag.group.toLowerCase().includes(needle)
				);
			})
			.sort((a, b) => b.rating - a.rating)
	);
</script>

<main class="space-y-6">
	{#if error}
		<p class="text-destructive">{error}</p>
	{:else if !skills}
		<p class="text-muted-foreground">Loading…</p>
	{:else}
		<Panel
			title="Topic states"
			description="Overall {Math.round(skills.overall.rating)}. A topic appears once it has emerged
			at your level; its rating is the overall plus its own offset, and the RD is aged to now."
		>
			{#snippet actions()}
				<div class="flex flex-wrap items-center gap-3">
					<SegmentedControl
						bind:value={filter}
						label="Topic state"
						items={[
							{ value: 'all', label: `All (${counts.all ?? 0})` },
							{ value: 'weak', label: `Weak (${counts.weak ?? 0})` },
							{ value: 'strong', label: `Strong (${counts.strong ?? 0})` },
							{ value: 'unknown', label: `Unknown (${counts.unknown ?? 0})` },
							{ value: 'not_yet_relevant', label: `Not yet (${counts.not_yet_relevant ?? 0})` }
						]}
					/>
					<Input bind:value={query} placeholder="filter tags…" class="w-48" />
				</div>
			{/snippet}

			{#if rows.length}
				<Table.Root variant="card">
					<Table.Header>
						<Table.Row>
							<Table.Head>Tag</Table.Head>
							<Table.Head>Group</Table.Head>
							<Table.Head class="text-right">Rating</Table.Head>
							<Table.Head class="text-right">RD</Table.Head>
							<Table.Head>State</Table.Head>
						</Table.Row>
					</Table.Header>
					<Table.Body>
						{#each rows as tag (tag.tag)}
							<Table.Row>
								<Table.Cell>{tag.tag}</Table.Cell>
								<Table.Cell class="text-muted-foreground">{tag.group}</Table.Cell>
								<Table.Cell class="text-right tabular-nums">{Math.round(tag.rating)}</Table.Cell>
								<Table.Cell class="text-muted-foreground text-right tabular-nums">
									{Math.round(tag.rd)}
								</Table.Cell>
								<Table.Cell>
									<Badge tone={TONE[tag.state]}>{LABEL[tag.state]}</Badge>
								</Table.Cell>
							</Table.Row>
						{/each}
					</Table.Body>
				</Table.Root>
			{:else}
				<p class="text-muted-foreground text-sm">No tag matches that filter.</p>
			{/if}
		</Panel>

		<Panel title="What the states mean">
			<dl class="grid gap-2 text-sm sm:grid-cols-2">
				<div>
					<dt class="font-medium">Not yet relevant</dt>
					<dd class="text-muted-foreground">
						The topic emerges above your overall rating, so it is not eligible yet.
					</dd>
				</div>
				<div>
					<dt class="font-medium">Unknown</dt>
					<dd class="text-muted-foreground">
						Never practised, or the estimate has faded out (RD ≥ 120).
					</dd>
				</div>
				<div>
					<dt class="font-medium">Weak</dt>
					<dd class="text-muted-foreground">At least 100 points below your overall rating.</dd>
				</div>
				<div>
					<dt class="font-medium">Strong</dt>
					<dd class="text-muted-foreground">Measured, and not below the overall rating.</dd>
				</div>
			</dl>
		</Panel>
	{/if}
</main>
