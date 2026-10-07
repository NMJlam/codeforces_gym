<script lang="ts">
	import type { LayoutProps } from './$types';
	import SegmentedNav from '#lib/components/segmented-nav.svelte';

	let { children }: LayoutProps = $props();

	// The whole account, one slider: the dashboard is the landing tab, and the
	// other three are one click away from anywhere inside the profile.
	const TABS = [
		{ href: '/profile/dashboard', label: 'Dashboard' },
		{ href: '/profile/topics', label: 'Topics' },
		{ href: '/profile/history', label: 'History' },
		{ href: '/profile/setup', label: 'Setup' }
	];
</script>

<div class="flex flex-col gap-6">
	<SegmentedNav items={TABS} class="w-full max-w-lg" />
	{@render children()}
</div>
