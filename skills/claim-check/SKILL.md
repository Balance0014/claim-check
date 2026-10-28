---
name: claim-check
description: Use before telling the user that work is done, fixed, deployed or passing, or that something does not exist or is not used. Requires proof from this turn, or an honest "not verified".
---

# claim-check

Two kinds of sentence cause most of the damage when they are wrong: "it's fixed" and "it isn't there". Before you write either one, have the proof in this turn.

## Before you say it's done, fixed, deployed or passing

1. After your last code or config edit, run the thing that proves it: the tests, the build, the command, a request to the live URL.
2. Put the result in your answer: how many tests passed, the status code, the commit, the exit code.
3. If you edited again after that run, run it again. A check from before the last edit proves nothing about the code now.
4. Re-reading the file you just edited is not a check.
5. If you can't run the check, say so: "changed, not verified yet". That is a complete, honest answer.

## Before you say something doesn't exist or isn't used

Look at least twice, in different ways: search for the name, then search for a likely alias or read the place it would be registered. If you only looked once, call it a guess.

## When "done" means a real fix

A real fix covers five things. Say which ones you did, and which you skipped:

1. **Cause.** You found why it broke, not only where.
2. **Prevention.** Something now stops the same failure, such as a test, a check or a guard.
3. **Siblings.** You looked for the same bug in similar places.
4. **Verification.** You ran the real thing and saw it work.
5. **Cleanup.** No temporary files, debug output or backup copies left behind.

Stopping the bleeding is useful. Call it that, not "fixed".

## If a hook blocked you

The claim-check hook found a claim without proof. Run the check and show the result, or rewrite the sentence as "not verified yet". It lets the second attempt through either way, so don't argue with it. Just do one of the two.
