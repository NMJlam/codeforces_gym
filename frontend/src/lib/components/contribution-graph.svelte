<script lang="ts">
	import type { Attempt } from '#lib/api.js';

	/**
	 * GitHub-style activity calendar: one square per day, one column per week,
	 * shaded by how much was attempted that day. It is a pure view of the
	 * attempt log — contest replays from the seed land on the day the contest
	 * ran, because that is what their `started_at` holds.
	 */
	let { attempts, weeks = 53 }: { attempts: Attempt[]; weeks?: number } = $props();

	const MONTH = new Intl.DateTimeFormat(undefined, { month: 'short' });
	const DAY = new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
	const WEEKDAY_LABELS = ['', 'Mon', '', 'Wed', '', 'Fri', ''];
	const LEVEL_CLASS = [
		'bg-foreground/10',
		'bg-primary/25',
		'bg-primary/45',
		'bg-primary/70',
		'bg-primary'
	];

	type Day = { date: Date; attempts: number; solved: number; future: boolean };
	type Column = { label: string | null; days: Day[] };

	function startOfDay(date: Date): Date {
		const copy = new Date(date);
		copy.setHours(0, 0, 0, 0);
		return copy;
	}

	function dayKey(date: Date): string {
		const month = String(date.getMonth() + 1).padStart(2, '0');
		return `${date.getFullYear()}-${month}-${String(date.getDate()).padStart(2, '0')}`;
	}

	/** started_at (local day) -> what happened that day. */
	const tally = $derived.by(() => {
		const byDay = new Map<string, { attempts: number; solved: number }>();
		for (const attempt of attempts) {
			const key = dayKey(new Date(attempt.started_at));
			const entry = byDay.get(key) ?? { attempts: 0, solved: 0 };
			entry.attempts += 1;
			if (attempt.s === 1) entry.solved += 1;
			byDay.set(key, entry);
		}
		return byDay;
	});

	const columns = $derived.by(() => {
		const today = startOfDay(new Date());
		// Walk back to the Sunday that starts the first week, so the last column
		// is the current Sunday-to-Saturday week and every column is a real week.
		const start = new Date(today);
		start.setDate(start.getDate() - today.getDay() - (weeks - 1) * 7);

		const built: Column[] = [];
		let previousMonth = -1;
		for (let week = 0; week < weeks; week += 1) {
			const days: Day[] = [];
			for (let weekday = 0; weekday < 7; weekday += 1) {
				const date = new Date(start);
				date.setDate(start.getDate() + week * 7 + weekday);
				const entry = tally.get(dayKey(date));
				days.push({
					date,
					attempts: entry?.attempts ?? 0,
					solved: entry?.solved ?? 0,
					future: date.getTime() > today.getTime()
				});
			}
			// Label a column where the month changes, so the strip reads
			// "Nov Dec Jan …" instead of repeating the month every week.
			const month = days[0].date.getMonth();
			built.push({ label: month === previousMonth ? null : MONTH.format(days[0].date), days });
			previousMonth = month;
		}
		return built;
	});

	const busiest = $derived(Math.max(1, ...columns.flatMap((column) => column.days.map((d) => d.attempts))));
	const total = $derived(columns.reduce((sum, column) => sum + column.days.reduce((n, d) => n + d.attempts, 0), 0));

	function level(day: Day): number {
		if (day.attempts === 0) return 0;
		return Math.min(4, Math.max(1, Math.ceil((day.attempts / busiest) * 4)));
	}

	function title(day: Day): string {
		const when = DAY.format(day.date);
		if (day.future) return when;
		if (day.attempts === 0) return `No attempts on ${when}`;
		return `${day.attempts} attempt${day.attempts === 1 ? '' : 's'} · ${day.solved} solved on ${when}`;
	}
</script>

<div class="overflow-x-auto">
	<div class="flex w-fit gap-1.5">
		<div class="text-muted-foreground flex shrink-0 flex-col gap-[3px] pt-4 text-[10px] leading-[10px]">
			{#each WEEKDAY_LABELS as label, weekday (weekday)}
				<span class="h-[10px]">{label}</span>
			{/each}
		</div>

		<div class="flex flex-col gap-1">
			<div class="flex h-3 gap-[3px]">
				{#each columns as column, week (week)}
					<div class="relative w-[10px]">
						{#if column.label}
							<span class="text-muted-foreground absolute text-[10px] leading-3 whitespace-nowrap">
								{column.label}
							</span>
						{/if}
					</div>
				{/each}
			</div>

			<div
				class="flex gap-[3px]"
				role="img"
				aria-label="{total} attempt{total === 1 ? '' : 's'} in the last {weeks} weeks, shaded by attempts per day"
			>
				{#each columns as column, week (week)}
					<div class="flex flex-col gap-[3px]">
						{#each column.days as day (dayKey(day.date))}
							<span
								class="size-[10px] rounded-[2px] {day.future
									? 'bg-transparent'
									: LEVEL_CLASS[level(day)]}"
								title={title(day)}
							></span>
						{/each}
					</div>
				{/each}
			</div>
		</div>
	</div>

	<div class="text-muted-foreground mt-3 flex flex-wrap items-center justify-between gap-2 text-xs">
		<span>{total} attempt{total === 1 ? '' : 's'} in the last {weeks} weeks</span>
		<span class="flex items-center gap-1">
			Less
			{#each LEVEL_CLASS as shade, index (index)}
				<span class="size-[10px] rounded-[2px] {shade}"></span>
			{/each}
			More
		</span>
	</div>
</div>
