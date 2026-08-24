# Runbook — GitHub Account Verification

**Run this before every repository creation, remote change or push. No exceptions.**

KalpaMani is owned exclusively by the GitHub account **`sap4naga-svg`**. It must never be
created, pushed, forked or configured under any other account — in particular not under
the account used for car-wash software.

```
AUTHORIZED GITHUB OWNER:  sap4naga-svg
EXPECTED REMOTE:          sap4naga-svg/KalpaMani
VISIBILITY:               PRIVATE
DEFAULT BRANCH:           main
```

---

## 1. Check the active account

```bash
gh auth status
```

Read the line marked `Active account: true`. That is the account `gh repo create` and
`git push` will use.

- **If it is exactly `sap4naga-svg`** → continue to step 2.
- **If it is anything else** → **STOP.** Do not create a repository. Do not push.
  Go to *Switching accounts* below.

Never print, echo or copy the token value. `gh auth status` masks it; keep it that way.

---

## 2. Verify the remote

```bash
git remote -v
```

Both fetch and push must point at `sap4naga-svg/KalpaMani`. If `origin` points anywhere
else, **STOP** and correct it before pushing:

```bash
git remote set-url origin https://github.com/sap4naga-svg/KalpaMani.git
```

---

## 3. Verify repository ownership and privacy

```bash
gh repo view sap4naga-svg/KalpaMani --json nameWithOwner,visibility,defaultBranchRef
```

Expected: owner `sap4naga-svg`, name `KalpaMani`, visibility `PRIVATE`, default branch
`main`.

---

## Switching accounts

If another account is active, **switch** rather than logging out — do not disturb other
authenticated accounts.

```bash
# List authenticated accounts
gh auth status

# If sap4naga-svg is already authenticated, just switch:
gh auth switch --hostname github.com --user sap4naga-svg

# If it is NOT authenticated yet, log in interactively (browser flow):
gh auth login --hostname github.com --web --scopes repo
```

**The operator performs this step personally.** Never paste a GitHub password, PAT, OAuth
token or 2FA code into an AI chat session, a script, a log or a committed file.

After switching, re-run step 1 and confirm before proceeding.

---

## Git identity

Do **not** change global Git identity — other projects depend on it. KalpaMani sets its
identity at repository scope only:

```bash
git config --local user.name  "<name for sap4naga-svg>"
git config --local user.email "<email for sap4naga-svg>"

# Verify what this repository will actually use:
git config user.name
git config user.email
```

Confirm the values before the first commit. Commits attributed to the wrong account are
the exact cross-contamination this runbook exists to prevent.

---

## Verification checklist

- [ ] `gh auth status` active account is `sap4naga-svg`
- [ ] `git config user.email` (repo scope) is the KalpaMani identity, not another project's
- [ ] `git remote -v` points to `sap4naga-svg/KalpaMani`
- [ ] `gh repo view` reports `PRIVATE`
- [ ] Default branch is `main`
- [ ] `git status` is clean
- [ ] No secrets in tracked files
