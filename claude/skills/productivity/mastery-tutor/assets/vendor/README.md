# Local rendering dependencies

Pinned npm distribution files; no CDN or runtime network dependency.
Downloaded and verified against npm's SHA-512 distribution integrity on 2026-11-06.

- [Marked](https://github.com/markedjs/marked) 18.1.3, MIT. `marked/marked.umd.js`, original LICENSE.
  Tarball integrity: `sha512-9ChMH8EVVgjgID49nsL6IWxWk5c6GtAsq/xw7U1ggkjkU5AGuv68oLTVlFRtvcUYZtpbNyjyvGo3YDu0fGapiw==`.
- [DOMPurify](https://github.com/cure53/DOMPurify) 3.4.17, Apache-2.0 OR MPL-2.0.
  `dompurify/purify.min.js`, original LICENSE and LICENSE-MPL.
  Tarball integrity: `sha512-B/pSlYVHQ58kqISD/yDjuJ1yfzI34m1gF4lAod2bwSRhiN4K5Cl3H8Af7hqB2PmTL911tdEudnnXn5FnhRoz0w==`.

Keep vendored distributions unchanged. Custom rendering belongs in `../study_markdown.js`.
