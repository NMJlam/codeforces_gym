<script lang="ts">
	import { cn } from '#lib/utils.js';
	import type { Snippet } from 'svelte';

	type Tone = 'neutral' | 'primary' | 'good' | 'bad' | 'warn' | 'muted';

	type Props = {
		tone?: Tone;
		title?: string;
		class?: string;
		children: Snippet;
	};

	let { tone = 'neutral', title = undefined, class: className = '', children }: Props = $props();

	const TONES: Record<Tone, string> = {
		neutral: 'bg-secondary text-secondary-foreground',
		primary: 'bg-primary/15 text-primary',
		good: 'bg-chart-3/15 text-chart-3',
		bad: 'bg-destructive/15 text-destructive',
		warn: 'bg-chart-5/15 text-chart-5',
		muted: 'text-muted-foreground border border-border'
	};
</script>

<span
	{title}
	class={cn(
		'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap',
		TONES[tone],
		className
	)}
>
	{@render children()}
</span>
