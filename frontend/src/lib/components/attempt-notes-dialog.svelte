<script lang="ts">
	import type { Attempt } from '#lib/api.js';
	import Dialog from '#lib/components/ui/dialog.svelte';
	import NoteEditor from '#lib/components/note-editor.svelte';
	import ProblemLine from '#lib/components/problem-line.svelte';
	import { current } from '#lib/current-session.svelte.js';
	import { SLOT_LABELS, formatWhen } from '#lib/format.js';

	type Props = {
		/** Whose notes are open. Kept after closing so the dialog does not blank out. */
		attempt: Attempt | null;
		open: boolean;
		/** Called after a save lands, so the page can re-read the row it came from. */
		onsaved?: () => void;
	};

	let { attempt = null, open = $bindable(false), onsaved }: Props = $props();
</script>

<Dialog bind:open title="Notes">
	{#if attempt}
		<div class="flex min-h-0 flex-col gap-3">
			<div class="space-y-1">
				<ProblemLine problem={attempt.problem} />
				<p class="text-muted-foreground text-sm">
					{attempt.slot ? SLOT_LABELS[attempt.slot] : attempt.source === 'contest' ? 'contest' : 'self-selected'}
					·
					{attempt.scored_at
						? `scored ${formatWhen(attempt.scored_at)}`
						: 'still running'}
				</p>
			</div>

			{#if attempt.scored_at === null}
				<p class="text-muted-foreground text-sm">
					The timer is still running: notes open once the attempt is scored.
				</p>
			{:else}
				<!-- One height for both views: the note area absorbs the difference, so
				     switching Display/Source never moves the box. The 10rem is the
				     title, the problem line and the padding, which the dialog's 90vh
				     cap also has to cover — otherwise the box overflows and the X
				     falls below the fold. A save leaves the dialog open: the note is
				     right there to keep working on. -->
				<div class="flex h-[min(calc(90vh-10rem),42rem)] min-h-0 flex-col gap-3">
					<NoteEditor {attempt} class="min-h-0 flex-1" {onsaved} />
					{#if current.error}
						<p class="text-destructive text-sm">{current.error}</p>
					{/if}
				</div>
			{/if}
		</div>
	{/if}
</Dialog>
