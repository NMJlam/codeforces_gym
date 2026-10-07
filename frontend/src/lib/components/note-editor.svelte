<script lang="ts">
	import type { Attempt } from '#lib/api.js';
	import Button from '#lib/components/ui/button.svelte';
	import SegmentedControl from '#lib/components/segmented-control.svelte';
	import Textarea from '#lib/components/ui/textarea.svelte';
	import { current } from '#lib/current-session.svelte.js';
	import { markdown } from '#lib/markdown.js';
	import { cn } from '#lib/utils.js';
	import { onDestroy } from 'svelte';

	type View = 'display' | 'source';

	type Props = {
		attempt: Attempt;
		/** Height of the source box, in rows, when the host lets the editor size itself. */
		rows?: number;
		/** `min-h-0 flex-1` from the dialog, so the editor fills a fixed-size box. */
		class?: string;
		/** Called after a save lands, so the host can re-read what it is showing. */
		onsaved?: () => void;
	};

	let { attempt, rows = 6, class: className = '', onsaved }: Props = $props();

	// `draft` is what is being typed; `baseline` is what the server holds. Unsaved
	// is then a comparison rather than a flag, and a save moves the baseline —
	// which is what lets the editor stay open and put the button back to rest.
	let baseline = $state('');
	let draft = $state('');

	// One view per attempt, chosen when it opens: a note that exists shows how it
	// reads, a blank one opens in the box — the failure prompt is asking for text.
	let view = $state<View>('display');
	let openedFor = $state<number | null>(null);

	$effect(() => {
		const note = attempt.key_idea ?? '';
		baseline = note;
		draft = note;
		if (openedFor === attempt.id) return;
		openedFor = attempt.id;
		view = note.trim() ? 'display' : 'source';
	});

	// The preview renders the draft, not the stored copy: switching to Display
	// before saving is how you check the markdown.
	const html = $derived(markdown.render(draft));
	const dirty = $derived(draft !== baseline);

	// A save stays put, so it needs to say it landed: the button going quiet is
	// not something anyone notices.
	let justSaved = $state(false);
	let savedTimer: ReturnType<typeof setTimeout> | undefined;
	onDestroy(() => clearTimeout(savedTimer));

	async function save() {
		if (!(await current.annotate(attempt.id, { key_idea: draft }))) return;
		baseline = draft;
		view = 'display';
		justSaved = true;
		clearTimeout(savedTimer);
		savedTimer = setTimeout(() => (justSaved = false), 2500);
		onsaved?.();
	}
</script>

<div class={cn('flex min-h-0 flex-col gap-2', className)}>
	<SegmentedControl
		label="Note view"
		bind:value={view}
		items={[
			{ value: 'display', label: 'Display' },
			{ value: 'source', label: 'Source' }
		]}
	/>

	{#if view === 'display'}
		{#if draft.trim()}
			<div class="note-markdown min-h-0 flex-1 overflow-y-auto">{@html html}</div>
		{:else}
			<p class="text-muted-foreground min-h-0 flex-1 text-sm">
				Nothing saved yet — switch to <span class="text-foreground">Source</span> and write it in
				markdown: lists, bold, code and links all work.
			</p>
		{/if}
	{:else}
		<Textarea
			bind:value={draft}
			{rows}
			class="min-h-0 flex-1 resize-none font-mono text-[13px] leading-relaxed"
			placeholder="- the trick&#10;- what the naive idea gets wrong&#10;- the edge case"
		/>
		<p class="text-muted-foreground text-xs">
			Markdown: <code>-</code> lists, <code>**bold**</code>, <code>`code`</code>,
			<code>[link](url)</code>
		</p>
	{/if}

	<div class="flex flex-wrap items-center justify-end gap-3">
		{#if justSaved}
			<span class="text-muted-foreground text-xs">Saved</span>
		{/if}
		<Button size="sm" onclick={save} disabled={current.busy || !dirty}>Save key idea</Button>
	</div>
</div>
