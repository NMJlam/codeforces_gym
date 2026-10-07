import { redirect } from '@sveltejs/kit';

// The top-level nav picks between Session and Profile, so `/` only exists to
// land on the profile's default tab.
export const load = () => {
	throw redirect(307, '/profile/dashboard');
};
