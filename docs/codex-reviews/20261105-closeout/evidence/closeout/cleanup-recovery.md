# Recovery instructions

Private backup (0700). Never copy bundle, tar, patches, ignored credentials or contents into the source repo or notifications.

## Standalone recovery in a NEW empty bare repository

```sh
git init --bare /ABS/NEW/restore.git
git --git-dir=/ABS/NEW/restore.git -c gc.auto=0 fetch --no-auto-maintenance --no-write-fetch-head /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/repository.bundle '+refs/*:refs/*'
git --git-dir=/ABS/NEW/restore.git fsck --full --strict
```

Actually executed successfully in /private/tmp/trade-cleanup-restore-20261105T175548-390bd6-5ccv7mn6/restore.git. No alternates, no external prerequisite commits; all frozen refs and four stash backup refs fetched.

## Restore exact deleted local branch refs

Check that the branch name is still absent. Run from a protected source worktree:

```sh
git fetch --no-auto-maintenance --no-write-fetch-head /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/repository.bundle refs/heads/feat/codex-evidence-fix-20261104:refs/heads/feat/codex-evidence-fix-20261104
git fetch --no-auto-maintenance --no-write-fetch-head /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/repository.bundle refs/heads/feat/codex-f01-fof-batch-signal-20261104:refs/heads/feat/codex-f01-fof-batch-signal-20261104
git fetch --no-auto-maintenance --no-write-fetch-head /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/repository.bundle refs/heads/feat/codex-f03-digest-atomic-20261104:refs/heads/feat/codex-f03-digest-atomic-20261104
git fetch --no-auto-maintenance --no-write-fetch-head /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/repository.bundle refs/heads/feat/codex-f04-r2-barrier-lock-20261104:refs/heads/feat/codex-f04-r2-barrier-lock-20261104
git fetch --no-auto-maintenance --no-write-fetch-head /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/repository.bundle refs/heads/feat/codex-handoff-ack-20261104:refs/heads/feat/codex-handoff-ack-20261104
git fetch --no-auto-maintenance --no-write-fetch-head /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/repository.bundle refs/heads/feat/codex-s01s02-annotation-20261104:refs/heads/feat/codex-s01s02-annotation-20261104
git fetch --no-auto-maintenance --no-write-fetch-head /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/repository.bundle refs/heads/feat/ledger-l56-20261104:refs/heads/feat/ledger-l56-20261104
git fetch --no-auto-maintenance --no-write-fetch-head /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/repository.bundle refs/heads/worktree-agent-a16f4a9524c45bb75:refs/heads/worktree-agent-a16f4a9524c45bb75
git fetch --no-auto-maintenance --no-write-fetch-head /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/repository.bundle refs/heads/worktree-agent-a1a34ccc1bd94e1c3:refs/heads/worktree-agent-a1a34ccc1bd94e1c3
git fetch --no-auto-maintenance --no-write-fetch-head /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/repository.bundle refs/heads/worktree-agent-a4387b6c00013d425:refs/heads/worktree-agent-a4387b6c00013d425
git fetch --no-auto-maintenance --no-write-fetch-head /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/repository.bundle refs/heads/worktree-agent-a497cea4f459ac420:refs/heads/worktree-agent-a497cea4f459ac420
git fetch --no-auto-maintenance --no-write-fetch-head /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/repository.bundle refs/heads/worktree-agent-a50d6e1b8bab9beac:refs/heads/worktree-agent-a50d6e1b8bab9beac
git fetch --no-auto-maintenance --no-write-fetch-head /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/repository.bundle refs/heads/worktree-agent-a5b5908105e357067:refs/heads/worktree-agent-a5b5908105e357067
git fetch --no-auto-maintenance --no-write-fetch-head /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/repository.bundle refs/heads/worktree-agent-a6c7a58dac27aff23:refs/heads/worktree-agent-a6c7a58dac27aff23
git fetch --no-auto-maintenance --no-write-fetch-head /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/repository.bundle refs/heads/worktree-agent-a6f893a931a38a74a:refs/heads/worktree-agent-a6f893a931a38a74a
git fetch --no-auto-maintenance --no-write-fetch-head /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/repository.bundle refs/heads/worktree-agent-a7bf9d554f800a85a:refs/heads/worktree-agent-a7bf9d554f800a85a
git fetch --no-auto-maintenance --no-write-fetch-head /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/repository.bundle refs/heads/worktree-agent-a85949bb84ebe6fb7:refs/heads/worktree-agent-a85949bb84ebe6fb7
git fetch --no-auto-maintenance --no-write-fetch-head /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/repository.bundle refs/heads/worktree-agent-a86a71e6c82fec435:refs/heads/worktree-agent-a86a71e6c82fec435
git fetch --no-auto-maintenance --no-write-fetch-head /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/repository.bundle refs/heads/worktree-agent-a92740fbdd863923a:refs/heads/worktree-agent-a92740fbdd863923a
git fetch --no-auto-maintenance --no-write-fetch-head /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/repository.bundle refs/heads/worktree-agent-a9e30b8fe959164bb:refs/heads/worktree-agent-a9e30b8fe959164bb
git fetch --no-auto-maintenance --no-write-fetch-head /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/repository.bundle refs/heads/worktree-agent-ab3be0d77f2e065a3:refs/heads/worktree-agent-ab3be0d77f2e065a3
git fetch --no-auto-maintenance --no-write-fetch-head /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/repository.bundle refs/heads/worktree-agent-ab74b841cccab25f6:refs/heads/worktree-agent-ab74b841cccab25f6
git fetch --no-auto-maintenance --no-write-fetch-head /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/repository.bundle refs/heads/worktree-agent-abfdee5da64e2037c:refs/heads/worktree-agent-abfdee5da64e2037c
git fetch --no-auto-maintenance --no-write-fetch-head /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/repository.bundle refs/heads/worktree-agent-acbf114aa56b9db87:refs/heads/worktree-agent-acbf114aa56b9db87
git fetch --no-auto-maintenance --no-write-fetch-head /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/repository.bundle refs/heads/worktree-agent-ad043a71a1d661ed0:refs/heads/worktree-agent-ad043a71a1d661ed0
git fetch --no-auto-maintenance --no-write-fetch-head /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/repository.bundle refs/heads/worktree-agent-afdb97bbaa529d08b:refs/heads/worktree-agent-afdb97bbaa529d08b
git fetch --no-auto-maintenance --no-write-fetch-head /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/repository.bundle refs/heads/feat/backend-p2-fixes-20261105:refs/heads/feat/backend-p2-fixes-20261105
git fetch --no-auto-maintenance --no-write-fetch-head /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/repository.bundle refs/heads/feat/fix-a657-artifacts-20261105:refs/heads/feat/fix-a657-artifacts-20261105
git fetch --no-auto-maintenance --no-write-fetch-head /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/repository.bundle refs/heads/feat/fix-bump-products-20261105:refs/heads/feat/fix-bump-products-20261105
git fetch --no-auto-maintenance --no-write-fetch-head /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/repository.bundle refs/heads/feat/fix-main-merge-selfupdate-20261105:refs/heads/feat/fix-main-merge-selfupdate-20261105
git fetch --no-auto-maintenance --no-write-fetch-head /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/repository.bundle refs/heads/feat/ledger-l57-20261105:refs/heads/feat/ledger-l57-20261105
git fetch --no-auto-maintenance --no-write-fetch-head /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/repository.bundle refs/heads/feat/preexisting-same-class-20261105:refs/heads/feat/preexisting-same-class-20261105
git fetch --no-auto-maintenance --no-write-fetch-head /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/repository.bundle refs/heads/feat/selfupdate-notes-20261105:refs/heads/feat/selfupdate-notes-20261105
```

## Restore original four-entry stash reflog in a NEW restoration repo

The source stash list was never modified. Only after the standalone fetch above, in the NEW bare repo:

```sh
mkdir -p /ABS/NEW/restore.git/logs/refs
cp /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/git-metadata/logs/refs/stash /ABS/NEW/restore.git/logs/refs/stash
git --git-dir=/ABS/NEW/restore.git reflog show refs/stash
```

Frozen SHA/order: frozen-stashes.json. Saved temporary refs: stash-analysis.json. Do not replay stash store into the live source list or overwrite its log.

## Restore worktree files and registration

Raw recovery: `mkdir -m700 /NEW/EMPTY/DIR; tar -xpf ARCHIVE -C /NEW/EMPTY/DIR` recovers all files, ignored/untracked entries and symlinks. The archived `.git` file is historical; for a working Git registration use the commands below. No symlinks were followed during archive creation.

Restore missing branch refs first, then choose original paths only when absent:

```sh
git worktree add --no-checkout /Users/linhuichen/code/trade/.claude/worktrees/agent-a1a34ccc1bd94e1c3 feat/backend-p2-fixes-20261105
cp /Users/linhuichen/code/trade/.claude/worktrees/agent-a1a34ccc1bd94e1c3/.git /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/recovery-pointer-0.gitfile
tar -xpf /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/worktrees/agent-a1a34ccc1bd94e1c3.tar -C /Users/linhuichen/code/trade/.claude/worktrees/agent-a1a34ccc1bd94e1c3
cp /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/recovery-pointer-0.gitfile /Users/linhuichen/code/trade/.claude/worktrees/agent-a1a34ccc1bd94e1c3/.git
git -C /Users/linhuichen/code/trade/.claude/worktrees/agent-a1a34ccc1bd94e1c3 read-tree af6fddf10c1e5a43af71bdd15888e6d319f277a0
git -C /Users/linhuichen/code/trade/.claude/worktrees/agent-a1a34ccc1bd94e1c3 status --porcelain=v1 --untracked-files=all
```

```sh
git worktree add --no-checkout /Users/linhuichen/code/trade/.claude/worktrees/agent-afdb97bbaa529d08b feat/fix-bump-products-20261105
cp /Users/linhuichen/code/trade/.claude/worktrees/agent-afdb97bbaa529d08b/.git /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/recovery-pointer-1.gitfile
tar -xpf /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/worktrees/agent-afdb97bbaa529d08b.tar -C /Users/linhuichen/code/trade/.claude/worktrees/agent-afdb97bbaa529d08b
cp /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/recovery-pointer-1.gitfile /Users/linhuichen/code/trade/.claude/worktrees/agent-afdb97bbaa529d08b/.git
git -C /Users/linhuichen/code/trade/.claude/worktrees/agent-afdb97bbaa529d08b read-tree 32785ab20959cf5e53edc3944fd828b36fdbe5bc
git -C /Users/linhuichen/code/trade/.claude/worktrees/agent-afdb97bbaa529d08b status --porcelain=v1 --untracked-files=all
```

```sh
git worktree add --no-checkout /Users/linhuichen/code/trade/.claude/worktrees/agent-a4387b6c00013d425 feat/fix-main-merge-selfupdate-20261105
cp /Users/linhuichen/code/trade/.claude/worktrees/agent-a4387b6c00013d425/.git /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/recovery-pointer-2.gitfile
tar -xpf /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/worktrees/agent-a4387b6c00013d425.tar -C /Users/linhuichen/code/trade/.claude/worktrees/agent-a4387b6c00013d425
cp /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/recovery-pointer-2.gitfile /Users/linhuichen/code/trade/.claude/worktrees/agent-a4387b6c00013d425/.git
git -C /Users/linhuichen/code/trade/.claude/worktrees/agent-a4387b6c00013d425 read-tree 5e0d90b7d0d1ee4f9647f6b2bab4b74d2cab6d35
git -C /Users/linhuichen/code/trade/.claude/worktrees/agent-a4387b6c00013d425 status --porcelain=v1 --untracked-files=all
```

```sh
git worktree add --no-checkout /Users/linhuichen/code/trade/.claude/worktrees/agent-a7bf9d554f800a85a feat/ledger-l57-20261105
cp /Users/linhuichen/code/trade/.claude/worktrees/agent-a7bf9d554f800a85a/.git /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/recovery-pointer-3.gitfile
tar -xpf /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/worktrees/agent-a7bf9d554f800a85a.tar -C /Users/linhuichen/code/trade/.claude/worktrees/agent-a7bf9d554f800a85a
cp /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/recovery-pointer-3.gitfile /Users/linhuichen/code/trade/.claude/worktrees/agent-a7bf9d554f800a85a/.git
git -C /Users/linhuichen/code/trade/.claude/worktrees/agent-a7bf9d554f800a85a read-tree 2da56696147b47e9ec27d44a27d02a6ac5edd78c
git -C /Users/linhuichen/code/trade/.claude/worktrees/agent-a7bf9d554f800a85a status --porcelain=v1 --untracked-files=all
```

```sh
git worktree add --no-checkout --detach /private/tmp/rev-p2 af6fddf10c1e5a43af71bdd15888e6d319f277a0
cp /private/tmp/rev-p2/.git /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/recovery-pointer-4.gitfile
tar -xpf /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/worktrees/rev-p2.tar -C /private/tmp/rev-p2
cp /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/recovery-pointer-4.gitfile /private/tmp/rev-p2/.git
git -C /private/tmp/rev-p2 read-tree af6fddf10c1e5a43af71bdd15888e6d319f277a0
git -C /private/tmp/rev-p2 status --porcelain=v1 --untracked-files=all
```

```sh
git worktree add --no-checkout /Users/linhuichen/code/trade/.claude/worktrees/agent-acbf114aa56b9db87 feat/fix-a657-artifacts-20261105
cp /Users/linhuichen/code/trade/.claude/worktrees/agent-acbf114aa56b9db87/.git /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/recovery-pointer-5.gitfile
tar -xpf /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/worktrees/agent-acbf114aa56b9db87.tar -C /Users/linhuichen/code/trade/.claude/worktrees/agent-acbf114aa56b9db87
cp /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/recovery-pointer-5.gitfile /Users/linhuichen/code/trade/.claude/worktrees/agent-acbf114aa56b9db87/.git
git -C /Users/linhuichen/code/trade/.claude/worktrees/agent-acbf114aa56b9db87 read-tree c508c0a728802324860d79c2874f07cfde691026
git -C /Users/linhuichen/code/trade/.claude/worktrees/agent-acbf114aa56b9db87 status --porcelain=v1 --untracked-files=all
```

```sh
git worktree add --no-checkout /Users/linhuichen/code/trade/.claude/worktrees/agent-ab74b841cccab25f6 feat/preexisting-same-class-20261105
cp /Users/linhuichen/code/trade/.claude/worktrees/agent-ab74b841cccab25f6/.git /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/recovery-pointer-6.gitfile
tar -xpf /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/worktrees/agent-ab74b841cccab25f6.tar -C /Users/linhuichen/code/trade/.claude/worktrees/agent-ab74b841cccab25f6
cp /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/recovery-pointer-6.gitfile /Users/linhuichen/code/trade/.claude/worktrees/agent-ab74b841cccab25f6/.git
git -C /Users/linhuichen/code/trade/.claude/worktrees/agent-ab74b841cccab25f6 read-tree 897b566242c19e0ecce09f01314c42ca9a2a2acb
git -C /Users/linhuichen/code/trade/.claude/worktrees/agent-ab74b841cccab25f6 status --porcelain=v1 --untracked-files=all
```

```sh
git worktree add --no-checkout /Users/linhuichen/code/trade/.claude/worktrees/agent-ad043a71a1d661ed0 feat/selfupdate-notes-20261105
cp /Users/linhuichen/code/trade/.claude/worktrees/agent-ad043a71a1d661ed0/.git /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/recovery-pointer-7.gitfile
tar -xpf /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/worktrees/agent-ad043a71a1d661ed0.tar -C /Users/linhuichen/code/trade/.claude/worktrees/agent-ad043a71a1d661ed0
cp /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/recovery-pointer-7.gitfile /Users/linhuichen/code/trade/.claude/worktrees/agent-ad043a71a1d661ed0/.git
git -C /Users/linhuichen/code/trade/.claude/worktrees/agent-ad043a71a1d661ed0 read-tree a206dc06f2579dc2135256a27805929b0c09d3b6
git -C /Users/linhuichen/code/trade/.claude/worktrees/agent-ad043a71a1d661ed0 status --porcelain=v1 --untracked-files=all
```

```sh
git worktree add --no-checkout --detach /private/tmp/rev-preissue 897b566242c19e0ecce09f01314c42ca9a2a2acb
cp /private/tmp/rev-preissue/.git /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/recovery-pointer-8.gitfile
tar -xpf /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/worktrees/rev-preissue.tar -C /private/tmp/rev-preissue
cp /Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6/recovery-pointer-8.gitfile /private/tmp/rev-preissue/.git
git -C /private/tmp/rev-preissue read-tree 897b566242c19e0ecce09f01314c42ca9a2a2acb
git -C /private/tmp/rev-preissue status --porcelain=v1 --untracked-files=all
```

Saving/restoring the new `.git` pointer avoids obsolete administrative paths. `read-tree` restores the clean index without rewriting source files. Each immutable tar retains its original `.git`, all ignored files and metadata. These restoration commands are documented for future recovery, not executed against the source.
