<script lang="ts">
	import type { Problem } from '#lib/api.js';

	let { problem, class: className = '' }: { problem: Problem; class?: string } = $props();

	// Codeforces puts problemset problems at /problemset/problem/{contest}/{index}.
	const href = $derived(
		`https://codeforces.com/problemset/problem/${problem.contest_id}/${problem.index}`
	);
</script>

<a
	{href}
	target="_blank"
	rel="noreferrer"
	class="inline-flex min-w-0 flex-wrap items-baseline gap-x-2 hover:underline {className}"
>
	<span class="font-medium">{problem.name}</span>
	<span class="text-muted-foreground text-xs tabular-nums">
		{problem.contest_id}{problem.index} · {problem.rating ?? 'unrated'}
	</span>
</a>
