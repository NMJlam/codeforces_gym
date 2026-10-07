<script lang="ts" generics="Value extends string">
	import { cn } from '#lib/utils.js';

	/**
	 * A pick-one control: a segmented row of radios. Not tabs — every segment
	 * shows the same region with different data, so there is no panel to move
	 * focus into. `role="radio"` is what the interaction actually is, and it
	 * reads correctly without a tabpanel.
	 */
	type Item = { value: Value; label: string; dot?: string };

	let {
		items,
		value = $bindable<Value | null>(null),
		label,
		class: className = ''
	}: { items: Item[]; value?: Value | null; label: string; class?: string } = $props();
</script>

<div
	class={cn(
		'bg-muted flex w-fit max-w-full flex-wrap items-center gap-x-0.5 gap-y-0.5 rounded-lg p-0.5',
		className
	)}
	role="radiogroup"
	aria-label={label}
>
	{#each items as item (item.value)}
		<button
			type="button"
			role="radio"
			aria-checked={value === item.value}
			class={cn(
				'flex h-7 items-center gap-1.5 rounded-md px-3 text-xs font-medium whitespace-nowrap transition-colors sm:text-sm',
				value === item.value
					? 'bg-background text-foreground shadow-sm'
					: 'text-muted-foreground hover:text-foreground'
			)}
			onclick={() => (value = item.value)}
		>
			{item.label}
			{#if item.dot}
				<span class="bg-primary size-1.5 rounded-full" title={item.dot}></span>
			{/if}
		</button>
	{/each}
</div>
