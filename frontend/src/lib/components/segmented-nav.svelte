<script lang="ts">
	import { page } from '$app/state';
	import { cn } from '#lib/utils.js';

	/**
	 * A row of equal-width links with a pill that slides under the active one.
	 * Plain anchors, not buttons: these are routes, so a middle-click and a
	 * "open in new tab" have to keep working. The pill is positioned from the
	 * active index alone, so it never depends on measuring the DOM.
	 */
	type Item = { href: string; label: string };

	let {
		items,
		size = 'default',
		class: className = ''
	}: { items: Item[]; size?: 'default' | 'lg'; class?: string } = $props();

	function isActive(href: string): boolean {
		const path = page.url.pathname.replace(/\/+$/, '') || '/';
		return path === href || path.startsWith(`${href}/`);
	}

	const activeIndex = $derived(Math.max(0, items.findIndex((item) => isActive(item.href))));
</script>

<nav
	class={cn('relative grid rounded-lg bg-muted p-0.5', className)}
	style="grid-template-columns: repeat({items.length}, minmax(0, 1fr))"
>
	<span
		aria-hidden="true"
		class="pointer-events-none absolute inset-y-0.5 left-0.5 rounded-md bg-background shadow-sm transition-transform duration-200 ease-in-out"
		style="width: calc((100% - 4px) / {items.length}); transform: translateX(calc({activeIndex} * 100%))"
	></span>
	{#each items as item (item.href)}
		<a
			href={item.href}
			aria-current={isActive(item.href) ? 'page' : undefined}
			class={cn(
				'relative z-10 flex items-center justify-center whitespace-nowrap rounded-md font-medium transition-colors',
				size === 'lg' ? 'h-8.5 px-3 text-sm' : 'h-7 px-2.5 text-xs sm:text-sm',
				isActive(item.href)
					? 'text-foreground'
					: 'text-muted-foreground hover:text-foreground'
			)}
		>
			{item.label}
		</a>
	{/each}
</nav>
