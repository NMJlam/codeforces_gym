<script lang="ts">
	import { cn } from '#lib/utils.js';
	import type { Snippet } from 'svelte';
	import type { SvelteHTMLElements } from 'svelte/elements';

	type Variant = 'primary' | 'outline' | 'ghost' | 'danger';
	type Size = 'sm' | 'md' | 'lg';

	// Everything a plain <button> takes (aria-label, aria-pressed, …) passes
	// through; only the look is decided here.
	type Props = Omit<SvelteHTMLElements['button'], 'class' | 'children'> & {
		variant?: Variant;
		size?: Size;
		class?: string;
		children: Snippet;
	};

	let {
		variant = 'primary',
		size = 'md',
		type = 'button',
		disabled = false,
		title = undefined,
		class: className = '',
		onclick,
		children,
		...props
	}: Props = $props();

	const VARIANTS: Record<Variant, string> = {
		primary: 'bg-primary text-primary-foreground hover:bg-primary/90',
		outline: 'border border-border hover:bg-accent hover:text-accent-foreground',
		ghost: 'hover:bg-accent hover:text-accent-foreground',
		danger: 'bg-destructive/15 text-destructive hover:bg-destructive/25'
	};
	const SIZES: Record<Size, string> = {
		sm: 'h-8 gap-1.5 px-3 text-xs',
		md: 'h-9 gap-2 px-4 text-sm',
		lg: 'h-11 gap-2 px-6 text-base'
	};
</script>

<button
	{type}
	{disabled}
	{title}
	{onclick}
	class={cn(
		'inline-flex items-center justify-center rounded-md font-medium whitespace-nowrap transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring/60 disabled:pointer-events-none disabled:opacity-50',
		VARIANTS[variant],
		SIZES[size],
		className
	)}
	{...props}
>
	{@render children()}
</button>
