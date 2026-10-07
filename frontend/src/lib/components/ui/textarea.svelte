<script lang="ts">
	import { cn } from '#lib/utils.js';

	type Props = {
		value?: string;
		placeholder?: string;
		rows?: number;
		id?: string;
		disabled?: boolean;
		onkeydown?: (event: KeyboardEvent) => void;
		class?: string;
	};

	let {
		value = $bindable(''),
		placeholder = '',
		rows = 3,
		id = undefined,
		disabled = false,
		onkeydown,
		class: className = ''
	}: Props = $props();
</script>

<textarea
	{id}
	{rows}
	{placeholder}
	{disabled}
	{onkeydown}
	bind:value
	class={cn(
		'border-input w-full rounded-md border bg-transparent px-3 py-2 text-sm outline-none transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/40 disabled:opacity-50',
		className
	)}
></textarea>
