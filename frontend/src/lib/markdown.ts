/**
 * Key-idea notes are markdown. What they usually hold is a handful of
 * observations — the trick, the edge case, why the first idea failed — and a
 * wall of plain text hides that structure.
 *
 * `html: false` is the whole safety story for putting the rendered string in
 * `{@html}`: raw HTML in a note stays text, and markdown-it's own link
 * validator refuses `javascript:`/`data:` URLs, so no sanitizer pass is needed
 * on top.
 */

import MarkdownIt from 'markdown-it';

export const markdown = new MarkdownIt({ html: false, breaks: true, linkify: true });

// A note's links point at Codeforces, an editorial or a blog post: open them in
// a new tab like every other link in the app, never inside the SPA.
markdown.renderer.rules.link_open = (tokens, idx, options, _env, self) => {
	tokens[idx].attrSet('target', '_blank');
	tokens[idx].attrSet('rel', 'noreferrer');
	return self.renderToken(tokens, idx, options);
};
