# Splitting `cythera/` into its own repository

This is a runbook, not a description of something already done. Delete it once
the split has happened.

## Why the new repo must be called `cythera`

GitHub Pages serves a project repo at `<user>.github.io/<repo>/`. The pages
currently live at `e-z-g.github.io/cythera/…` because they sit in a `cythera/`
folder of the user site. Name the new repo **`cythera`** and every public URL
stays byte-identical — the four links in the site's `index.html` are relative
(`cythera/cythera_data_viewer.html`), and the absolute ones in `README.md`
already point at `e-z-g.github.io/cythera/…`. Nobody's bookmark breaks.

Any other name means editing both files and breaking every existing link.

Remove the `cythera/` folder from the user site in the same change that brings
the new repo up, so there is never a period where a folder and a project repo
both claim that path.

## What actually has to change

Exactly four URLs, all in `cythera_data_viewer.html`. They are pinned to the
user site's `main` branch, so they move with the repo:

| Line | What it fetches |
|---|---|
| 63 | `res/ArgosANouveau.woff2` — the Argos font face |
| 84 | `res/Dialogue_Background.png` — dialogue panel fill |
| 156 | `res/Dialogue_Background.png` — the frame's border-image |
| 3598 | `res/Cythera%20Data` — `DEFAULT_ARCHIVE_URL` |

Rewrite each from

    raw.githubusercontent.com/e-z-g/e-z-g.github.io/main/cythera/res/…

to

    raw.githubusercontent.com/e-z-g/cythera/main/res/…

Note the `cythera/` path segment disappears as the repo prefix gains it.

These are pinned to `main`, so **the live page keeps loading the old URLs until
the new repo's `main` exists and has `res/` in it.** Bring the new repo up
first, verify the four assets resolve, and only then delete the folder here.

## Doing it with history

`git subtree split` rewrites the cythera commits as a standalone history, so
`git log` on the new repo still explains why things are the way they are —
which matters more here than usual, given how much of this codebase's reasoning
lives in commit messages and comments.

```sh
# in a clone of e-z-g.github.io, on an up-to-date main
git subtree split -P cythera -b cythera-only

# create an empty e-z-g/cythera on GitHub first (no README, no .gitignore)
git push git@github.com:e-z-g/cythera.git cythera-only:main
```

Then, in a fresh clone of the new repo:

1. Re-add the delvmod submodule — `git subtree split` does not carry
   `.gitmodules`, which lives at the old repo's root:
   ```sh
   git submodule add https://github.com/e-z-g/delvmod reference/delvmod
   ```
2. Copy across the `.gitignore` lines that were about cythera
   (`infinite-mac`, `sources`), plus `.DS_Store`.
3. Add a `.nojekyll` at the new root. The old one was at the user site's root
   and does not come along; without it Pages runs Jekyll and anything with an
   underscore or braces in it can be mangled.
4. Move the cythera part of the root `CLAUDE.md` into a `CLAUDE.md` here. The
   three-code-regimes section matters: this repo is entirely regime 3, classic
   scripts that must keep working from `file://`.
5. Rewrite the four URLs above.
6. Enable Pages (Settings → Pages → deploy from `main`), then check that
   `e-z-g.github.io/cythera/cythera_data_viewer.html` loads with its font,
   its frame and its default archive.
7. `node utilities/check_all.mjs` — expect **14 ok, 0 failed, 1 skipped**.

Only once that is all green: delete `cythera/` from `e-z-g.github.io`, and
leave `index.html` and `README.md` alone, because their links already point at
the right place.
