<script lang="ts">
	import { cn } from '#lib/utils.js';

	type Props = {
		value?: string;
		placeholder?: string;
		id?: string;
		disabled?: boolean;
		class?: string;
		onkeydown?: (event: KeyboardEvent) => void;
	};

	let {
		value = $bindable(''),
		placeholder = '',
		id = undefined,
		disabled = false,
		class: className = '',
		onkeydown
	}: Props = $props();
</script>

<input
	{id}
	{placeholder}
	{disabled}
	{onkeydown}
	bind:value
	class={cn(
		'border-input h-9 w-full min-w-0 rounded-md border bg-transparent px-3 py-1 text-sm outline-none transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/40 disabled:opacity-50',
		className
	)}
/>
