<script lang="ts">
	import { cn } from '#lib/utils.js';
	import type { Snippet } from 'svelte';

	type Props = {
		title?: string;
		description?: string;
		class?: string;
		/** Rendered opposite the title (buttons, tabs). */
		actions?: Snippet;
		/** A header-only panel is fine: some panels are just a title and an action. */
		children?: Snippet;
	};

	let { title = '', description = '', class: className = '', actions, children }: Props = $props();
</script>

<section class={cn('space-y-3 rounded-xl border bg-card p-4', className)}>
	{#if title || description || actions}
		<header class="flex flex-wrap items-start justify-between gap-3">
			<div class="space-y-0.5">
				{#if title}<h2 class="font-medium">{title}</h2>{/if}
				{#if description}<p class="text-muted-foreground text-sm">{description}</p>{/if}
			</div>
			{#if actions}{@render actions()}{/if}
		</header>
	{/if}
	{@render children?.()}
</section>
