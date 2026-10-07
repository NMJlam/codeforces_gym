<script lang="ts">
	import './layout.css';
	import favicon from '#lib/assets/favicon.svg';
	import type { LayoutProps } from './$types';
	import Badge from '#lib/components/ui/badge.svelte';
	import SegmentedNav from '#lib/components/segmented-nav.svelte';
	import { current } from '#lib/current-session.svelte.js';
	import { formatCountdown } from '#lib/format.js';

	let { children }: LayoutProps = $props();

	// Two top-level pickers and nothing else: everything about the account —
	// dashboard, topics, history, setup — lives behind Profile, so the nav never
	// grows a third destination.
	const PICKERS = [
		{ href: '/session', label: 'Session' },
		{ href: '/profile', label: 'Profile' }
	];

	// The session is app state, not page state: load it once so the nav can warn
	// about a running timer from anywhere.
	$effect(() => {
		void current.load();
	});
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
	<title>Codeforces Gym</title>
</svelte:head>

<div class="background-gradient pointer-events-none fixed inset-0 -z-10"></div>
<div class="background-grid pointer-events-none fixed inset-0 -z-10"></div>

<div class="mx-auto flex max-w-5xl flex-col gap-6 p-6">
	<div class="flex flex-wrap items-center gap-3 border-b pb-3">
		<SegmentedNav items={PICKERS} size="lg" class="w-full max-w-64" />
		{#if current.attempt}
			<a
				href="/session"
				class="ml-auto"
				title={current.attempt.paused_at ? 'The attempt timer is paused' : 'An attempt is running'}
			>
				<Badge tone={current.attempt.paused_at ? 'warn' : 'primary'}>
					{current.attempt.paused_at ? '❚❚' : '●'}
					{formatCountdown(current.remaining)} left
				</Badge>
			</a>
		{/if}
	</div>

	{@render children()}
</div>
