<script lang="ts">
	import { cn } from '#lib/utils.js';
	import Button from '#lib/components/ui/button.svelte';
	import X from '@lucide/svelte/icons/x';
	import type { Snippet } from 'svelte';

	type Props = {
		/** Two-way: the X, Escape and a backdrop click close the dialog by setting this. */
		open?: boolean;
		title?: string;
		class?: string;
		children: Snippet;
	};

	let { open = $bindable(false), title = '', class: className = '', children }: Props = $props();

	let dialog = $state<HTMLDialogElement | null>(null);

	// showModal is what makes it modal: the top layer, an inert page behind it,
	// Escape and ::backdrop. The `open` attribute alone leaves it in flow.
	// It also focuses the first focusable child — here that would be the X — so
	// focus is moved to the dialog itself and the first Tab lands in the content.
	$effect(() => {
		if (!dialog) return;
		if (open && !dialog.open) {
			dialog.showModal();
			dialog.focus();
		} else if (!open && dialog.open) {
			dialog.close();
		}
	});

	// Escape fires `close`; the handler is the one place that syncs `open` back.
	function onclose() {
		open = false;
	}

	// A click that targets the <dialog> itself is the backdrop — content lives in
	// child elements, so a click inside never targets it.
	function onclick(event: MouseEvent) {
		if (event.target === dialog) open = false;
	}
</script>

<dialog
	bind:this={dialog}
	tabindex="-1"
	{onclose}
	{onclick}
	class={cn(
		'bg-card text-card-foreground outline-none m-auto max-h-[90vh] w-[min(60rem,calc(100vw-2rem))] overflow-y-auto rounded-xl border p-5 shadow-xl backdrop:bg-black/60',
		className
	)}
>
	<header class="mb-3 flex items-start justify-between gap-2">
		<h2 class="font-medium">{title}</h2>
		<Button
			variant="ghost"
			size="sm"
			class="-mt-1 -mr-1 px-2"
			aria-label="Close"
			onclick={() => (open = false)}
		>
			<X size={16} />
		</Button>
	</header>
	{@render children()}
</dialog>
