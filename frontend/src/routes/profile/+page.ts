import { redirect } from '@sveltejs/kit';

// `/profile` is the picker's target; the tabs themselves live one segment down.
export const load = () => {
	throw redirect(307, '/profile/dashboard');
};
