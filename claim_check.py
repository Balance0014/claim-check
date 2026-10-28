#!/usr/bin/env python3
"""claim-check: stop a coding agent from saying "done" (or "not found") without proof.

Claude Code runs this as a Stop hook when the agent tries to end its turn. It reads the
session transcript, looks at what the agent claimed in its final message, and checks what
the agent actually did since your last message:

  * "fixed / deployed / tests pass / done" needs a command that ran after the last file
    edit and did not fail. Reading the file you just edited is not proof.
  * "doesn't exist / not found / nothing calls it" needs at least two lookups.

Missing proof: it blocks once, says exactly what is missing, and the agent either runs
the check or says plainly that it has not verified. Saying "not verified" always passes.
It never blocks twice in a row and never blocks because of its own errors. Every block
is appended to a log so you can audit false positives.

Usage:
  claim_check.py                      Stop hook mode (reads the hook payload on stdin)
  claim_check.py check FILE.jsonl     Judge the last turn of a transcript, print the verdict
  claim_check.py replay [DIR]         Judge every turn in past transcripts (default
                                      ~/.claude/projects) and print how often claims had proof
  claim_check.py report               Summarize the block log

Standard library only. Python 3.9+.
"""
import glob
import json
import os
import re
import sys
from datetime import datetime, timezone

LOG = os.environ.get('CLAIM_CHECK_LOG') or os.path.expanduser('~/.claude/claim-check/blocks.jsonl')

EDIT_TOOLS = {'Edit', 'MultiEdit', 'Write', 'NotebookEdit'}
READ_TOOLS = {'Read', 'Grep', 'Glob', 'LS'}
# What can prove a claim: running something. Shell commands, MCP tools (browsers, APIs), fetching a URL, a subagent.
# Bookkeeping such as TodoWrite proves nothing.
RUN_TOOLS = {'Bash', 'BashOutput', 'PowerShell', 'WebFetch', 'Agent', 'Task'}
# What counts as looking something up: reading, searching, or running a command.
LOOKUP_TOOLS = READ_TOOLS | RUN_TOOLS | {'WebSearch', 'NotebookRead'}


def runs(name):
    return name in RUN_TOOLS or name.startswith('mcp__')


def looks(name):
    return name in LOOKUP_TOOLS or name.startswith('mcp__')
# Updating notes or docs after a check doesn't undo the check.
DOC_FILE = re.compile(r'\.(?:md|markdown|txt|rst|adoc)$', re.I)
# A status report with no tool calls passes if it cites its proof.
PROOF = re.compile(
    r'\b(?=[0-9a-f]*[a-f])(?=[0-9a-f]*[0-9])[0-9a-f]{7,40}\b'         # commit (letters and digits, so not a date)
    r'|\b\d+\s+(?:tests?\s+)?(?:passed|passing)\b|\b\d+\s+tests?\b.{0,20}\b(?:pass|ok|green)'
    r'|\bHTTP\s*/?[\d.]*\s*\d{3}\b|\b(?:200|201|204)\s+OK\b|\bexit(?: code| status)?\s*[=:]?\s*0\b'
    r'|\bCI\s+(?:is\s+)?(?:green|passed)|https?://\S+/(?:actions/runs|commit|pull)/\S+'
    r'|\d+\s*(?:条|项|个)\s*(?:测试)?\s*(?:全)?(?:过|通过)|全绿|退出码\s*0', re.I)

# "I did it" claims. Phrases, not single words, so "the fixed header" or "done()" don't count.
DONE = [
    r"\b(?:is|are|was|were|it's|that's|now|been|i've|i have|we've|we have|all|everything(?: is)?)\s+(?:now\s+)?"
    r"(?:fixed|resolved|deployed|shipped|live|done|complete|completed|working|in place|verified)\b",
    r"\b(?:i|we)\s+(?:fixed|deployed|shipped|verified|resolved|completed)\b",
    r"\btests?\s+(?:now\s+)?(?:pass|passes|passed|passing|are green|is green)\b",
    r"\bworks now\b|\bnow works\b|\bshould (?:now )?(?:work|pass|be fixed)\b",
    r"^\s*(?:[-*]\s*)?(?:✅\s*)?(?:done|fixed|deployed|shipped|all set|all done)(?:\s*(?:[.!:—-]|$)|\s+and\b)",
    # Chinese: "已验证的格式" is an adjective, "装修好了" contains "修好了"; neither is a claim.
    r"(?:已完成|已修复|已修好|(?<![装维])修好了|已上线|已部署|已解决|已恢复|已接通|已生效|已验证|测试通过|全部通过|搞定了)(?![的地得、]|成功的)",
]
# "It isn't there" claims.
ABSENT = [
    r"\b(?:does not|doesn't|did not|didn't|no longer)\s+exists?\b",
    r"\bno longer (?:used|referenced|called|imported|needed)\b",
    r"\b(?:is|are)\s*(?:not|n't)\s+(?:used|referenced|called|imported|running) anywhere\b",
    r"\bnot (?:found|used|referenced|called) anywhere\b",
    r"\bnothing (?:calls|uses|references|imports)\b",
    r"\b(?:there is|there's|there are) no (?:caller|callers|usage|usages|reference|references)\b",
    # Chinese: only first-person findings. "不存在" and "找不到" are too common in explanations to count.
    r"没找到|没搜到|没人调用|没有调用|没在跑|不在跑|没有用到|没用到",
]
# Honest uncertainty always passes.
HEDGE = (r"\b(?:not|haven't|have not|didn't|did not|couldn't|could not)\s+(?:yet\s+)?"
         r"(?:verified|verify|tested|test|checked|check|run (?:it|them|this|the tests?|the check))\b"
         r"|\b(?:not|haven't|didn't|did not)\s+re-?(?:run|ran|checked|verified|tested)\b"
         r"|\bunverified\b|\buntested\b|未验证|没验证|未验|没验|没测|未测试|没重新验|没复核")


def _text(entry):
    c = (entry.get('message') or {}).get('content')
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return '\n'.join(i.get('text', '') for i in c if isinstance(i, dict) and i.get('type') == 'text')
    return ''


def is_human(entry):
    """A message you typed: a user entry with text, not a tool result and not an injected note."""
    if entry.get('type') != 'user' or entry.get('isMeta'):
        return False
    c = (entry.get('message') or {}).get('content')
    if isinstance(c, str):
        return bool(c.strip())
    return isinstance(c, list) and any(isinstance(i, dict) and i.get('type') == 'text' for i in c)


def load(path):
    out = []
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def turns(entries):
    """Split a transcript into turns: each starts at a message you typed."""
    cur = None
    for e in entries:
        if is_human(e):
            if cur is not None:
                yield cur
            cur = [e]
        elif cur is not None:
            cur.append(e)
    if cur is not None:
        yield cur


def strip_quoted(text):
    """Drop code, quotes and blockquotes: a claim inside quotes is someone else's words."""
    text = re.sub(r'```.*?```', ' ', text, flags=re.S)
    text = re.sub(r'`[^`\n]*`', ' ', text)
    text = re.sub(r'"[^"\n]*"|“[^”\n]*”|「[^」\n]*」|『[^』\n]*』', ' ', text)
    return '\n'.join(l for l in text.split('\n') if not l.lstrip().startswith('>'))


def parse(turn):
    """What the agent did in this turn and what it said at the end."""
    actions, errors, final = [], set(), []
    for e in turn[1:]:
        c = (e.get('message') or {}).get('content')
        if e.get('type') == 'assistant' and isinstance(c, list):
            for i in c:
                if not isinstance(i, dict):
                    continue
                if i.get('type') == 'tool_use':
                    name = i.get('name') or ''
                    path = str((i.get('input') or {}).get('file_path') or '')
                    if name in EDIT_TOOLS and DOC_FILE.search(path):
                        name = 'EditDoc'
                    actions.append((i.get('id'), name))
                    final = []          # text before a tool call is narration, not the answer
                elif i.get('type') == 'text':
                    final.append(i.get('text', ''))
        elif e.get('type') == 'user' and isinstance(c, list):
            for i in c:
                if isinstance(i, dict) and i.get('type') == 'tool_result' and i.get('is_error'):
                    errors.add(i.get('tool_use_id'))
    return actions, errors, strip_quoted('\n'.join(final))


def judge(turn, final_text=None):
    """Return None if the turn is fine, else (kind, claim, what's missing).

    final_text: the agent's last message as Claude Code hands it to the hook. The transcript
    is written asynchronously and can miss that message, so it wins when present.
    """
    actions, errors, said = parse(turn)
    if final_text:
        said = strip_quoted(final_text)
    if not said.strip() or re.search(HEDGE, said, re.I):
        return None

    claim = _first(DONE, said)
    if claim and not actions:
        if not PROOF.search(said):
            return 'done', claim, 'it is a report from memory with no proof cited (no commit, test result or status code)'
    elif claim:
        last_edit = max((k for k, (_, n) in enumerate(actions) if n in EDIT_TOOLS), default=-1)
        after = [n for k, (i, n) in enumerate(actions) if k > last_edit and i not in errors and runs(n)]
        if not after:
            missing = ('nothing ran after the last edit' if last_edit >= 0
                       else 'no command ran in this turn')
            return 'done', claim, missing

    claim = _first(ABSENT, said)
    lookups = sum(1 for i, n in actions if i not in errors and looks(n))
    if claim and lookups < 2:
        return 'absent', claim, f'only {lookups} lookup{"" if lookups == 1 else "s"} in this turn'
    return None


def _first(patterns, text):
    # Sentence by sentence, skipping questions: "does it exist?" is not a claim.
    for sentence in re.findall(r'[^。！？!?\n]+[。！？!?]?', text):
        if sentence.rstrip().endswith(('?', '？')):
            continue
        for p in patterns:
            m = re.search(p, sentence, re.I)
            if m:
                return m.group(0).strip()
    return None


def message(kind, claim, missing):
    if kind == 'done':
        return (f'claim-check: you wrote "{claim}", but {missing}. '
                'Run the check that proves it (tests, the command, a request to the live URL) and show the result, '
                'or say plainly that it is not verified yet.')
    return (f'claim-check: you wrote "{claim}", but {missing}. '
            'Search or read at least twice before saying something is not there, '
            'or say it is a guess.')


def log_block(payload, kind, claim, missing):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps({'at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                                'kind': kind, 'claim': claim, 'missing': missing,
                                'session': payload.get('session_id'), 'cwd': payload.get('cwd')},
                               ensure_ascii=False) + '\n')
    except OSError:
        pass


def hook():
    try:
        payload = json.loads(sys.stdin.read() or '{}')
    except ValueError:
        return 0
    if payload.get('stop_hook_active') or os.environ.get('CLAIM_CHECK_OFF'):
        return 0                                    # already blocked once; let it stop
    path = payload.get('transcript_path')
    try:
        last = list(turns(load(path)))[-1]
        verdict = judge(last, payload.get('last_assistant_message'))
    except Exception:                               # never block because of our own bug
        return 0
    if verdict:
        log_block(payload, *verdict)
        print(json.dumps({'decision': 'block', 'reason': message(*verdict)}, ensure_ascii=False))
    return 0


def check(path):
    t = list(turns(load(path)))
    verdict = judge(t[-1]) if t else None
    print(message(*verdict) if verdict else 'claim-check: pass')
    return 1 if verdict else 0


def replay(root):
    files = glob.glob(os.path.join(root, '**', '*.jsonl'), recursive=True)
    n_turns = 0
    seen = {'done': [0, 0], 'absent': [0, 0]}      # turns with the claim, turns that would be blocked
    for f in files:
        try:
            ts = list(turns(load(f)))
        except OSError:
            continue
        for t in ts:
            n_turns += 1
            said = parse(t)[2]
            for kind, pats in (('done', DONE), ('absent', ABSENT)):
                if _first(pats, said):
                    seen[kind][0] += 1
            v = judge(t)
            if v:
                seen[v[0]][1] += 1
    print(f'{len(files)} transcripts, {n_turns} turns.')
    for kind, label in (('done', '"done / fixed / deployed"'), ('absent', '"not found / doesn\'t exist"')):
        c, b = seen[kind]
        print(f'  {label}: {c} turns end with the claim; {b} had no proof ({b / c:.0%}).' if c
              else f'  {label}: no such claims.')
    return 0


def report():
    try:
        rows = [json.loads(l) for l in open(LOG, encoding='utf-8') if l.strip()]
    except OSError:
        print(f'No blocks logged yet ({LOG}).')
        return 0
    by = {}
    for r in rows:
        by[r.get('kind')] = by.get(r.get('kind'), 0) + 1
    print(f'{len(rows)} blocks since {rows[0]["at"]}: ' + ', '.join(f'{k} {v}' for k, v in sorted(by.items())))
    print('Latest ten (check these for false positives):')
    for r in rows[-10:]:
        print(f'  {r["at"]}  {r["kind"]:6}  "{r["claim"]}"  ({r["missing"]})')
    return 0


def main(argv):
    if len(argv) > 1 and argv[1] == 'check' and len(argv) > 2:
        return check(argv[2])
    if len(argv) > 1 and argv[1] == 'replay':
        return replay(argv[2] if len(argv) > 2 else os.path.expanduser('~/.claude/projects'))
    if len(argv) > 1 and argv[1] == 'report':
        return report()
    if len(argv) > 1:
        print(__doc__)
        return 2
    return hook()


if __name__ == '__main__':
    sys.exit(main(sys.argv))
