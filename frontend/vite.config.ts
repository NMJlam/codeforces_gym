import tailwindcss from '@tailwindcss/vite';
import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [
		tailwindcss(),
		sveltekit({
			compilerOptions: {
				// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
				runes: ({ filename }) =>
					filename.split(/[/\\]/).includes('node_modules') ? undefined : true
			},

			// Every page is client-rendered (`ssr = false` in routes/+layout.ts), so
			// there is nothing to prerender: adapter-static emits the app shell as
			// index.html and nginx serves it for every route. See frontend/nginx.conf
			// and frontend/Dockerfile.prod.
			adapter: adapter({ fallback: 'index.html' })
		})
	],
	server: {
		host: true, // reachable from outside the container
		proxy: { '/api': process.env.API_URL ?? 'http://localhost:5001' }
	}
});
