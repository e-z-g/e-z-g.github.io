# Splitting `cythera/` into its own repository

A runbook. Everything that could be prepared in advance has been; what is left
is the part that needs a repository to exist. **Delete this file once the split
has happened.**

The procedure below has been rehearsed end to end against this tree: the split
was performed, the URLs rewritten, the submodule initialised and the full suite
run from the result — **14 ok, 0 failed, 1 skipped**, with decoder snapshots
identical to the ones produced here.

## Why the new repo must be called `cythera`

GitHub Pages serves a project repo at `<user>.github.io/<repo>/`. These pages
already live at `e-z-g.github.io/cythera/…` because they sit in a `cythera/`
folder of the user site. Name the new repo **`cythera`** and every public URL
stays byte-identical — the four links in the site's `index.html` are relative
(`cythera/cythera_data_viewer.html`) and the ones in `README.md` are absolute to
that same path. Neither file needs editing. Nobody's bookmark breaks.

Any other name means editing both files and breaking every existing link.

## Already done

Staged inside `cythera/`, inert where they sit, correct the moment they are a
repository root:

- `.nojekyll` — without it Pages runs Jekyll and mangles anything with an
  underscore or braces in it. The site's own `.nojekyll` is at its root and
  does not come along.
- `.gitignore` — the same exclusions, said relatively.
- `.gitmodules` — pointing at `reference/delvmod`. Git reads this file only at
  a repository root, so it does nothing until it is one. A subtree split keeps
  the submodule's gitlink but not the root file that names it, which is the
  thing most likely to be missed.
- `CLAUDE.md` — the cythera half of the site's, made standalone. It overlaps
  with the root one until the split.

## What is left

### 1. Split, with history

`git subtree split` rewrites the cythera commits as a standalone history, so
`git log` still explains why things are the way they are — which matters more
here than usual, given how much of this codebase's reasoning lives in its
commit messages. It carried 40 commits in rehearsal.

```sh
# in a clone of e-z-g.github.io, on an up-to-date main
git subtree split -P cythera -b cythera-only
```

### 2. Create `e-z-g/cythera` on GitHub

Empty — no README, no .gitignore, no licence. Anything it adds is a commit the
split history has to be merged around.

```sh
git push git@github.com:e-z-g/cythera.git cythera-only:main
```

### 3. Rewrite the four pinned URLs

In a fresh clone of the new repo. These are the only cross-references the move
breaks: all four are in `cythera_data_viewer.html`, all four pinned to the user
site's `main`, so they move with the repo.

| Line | What it fetches |
|---|---|
| 63 | `res/ArgosANouveau.woff2` — the Argos font face |
| 84 | `res/Dialogue_Background.png` — dialogue panel fill |
| 156 | `res/Dialogue_Background.png` — the frame's border-image |
| 3598 | `res/Cythera%20Data` — `DEFAULT_ARCHIVE_URL` |

One command does all four. The `cythera/` path segment disappears as the repo
prefix gains it:

```sh
sed -i '' 's#raw\.githubusercontent\.com/e-z-g/e-z-g\.github\.io/main/cythera/#raw.githubusercontent.com/e-z-g/cythera/main/#g' cythera_data_viewer.html
```

(Drop the `''` after `-i` on GNU sed.) Then confirm nothing was missed:

```sh
grep -c 'e-z-g.github.io/main/cythera' cythera_data_viewer.html   # expect 0
grep -c 'e-z-g/cythera/main/res' cythera_data_viewer.html         # expect 4
```

### 4. Bring up the submodule and check

```sh
git submodule update --init reference/delvmod
node utilities/check_all.mjs          # expect 14 ok, 0 failed, 1 skipped
```

The one skip is infinite-mac, which is gitignored on purpose.

### 5. Enable Pages, then verify against the live site

Settings → Pages → deploy from `main`. Then load
`e-z-g.github.io/cythera/cythera_data_viewer.html` and confirm three things
that only the live page can show: the Argos font renders, the dialogue frame
has its border image, and the default archive loads on its own.

Those URLs are pinned to `main`, so **the live page keeps loading the old ones
until the new repo's `main` exists with `res/` in it.** This step is the gate.

### 6. Only then, remove the folder here

Delete `cythera/` from `e-z-g.github.io` and push. Leave `index.html` and
`README.md` alone — their links already point where they need to.

Do not leave both in place: a folder and a project repo claiming the same path
is ambiguous, and which one wins is not worth discovering in production.
