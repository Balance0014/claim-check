"""Each rule has a case it must catch and a case it must let through. No network, no real transcripts."""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import claim_check as C  # noqa: E402

N = iter(range(10**6))


def you(text):
    return {'type': 'user', 'message': {'role': 'user', 'content': text}}


def tool(name, error=False, **inp):
    i = f'toolu_{next(N)}'
    return [{'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'id': i, 'name': name, 'input': inp}]}},
            {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': i, 'is_error': error,
                                                      'content': 'boom' if error else 'ok'}]}}]


def say(text):
    return {'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': text}]}}


def turn(*parts):
    out = [you('fix the login bug')]
    for p in parts:
        out.extend(p if isinstance(p, list) else [p])
    return out


class Done(unittest.TestCase):
    def test_edit_then_claim_is_blocked(self):
        v = C.judge(turn(tool('Edit', file_path='app.py'), say('Fixed. The login bug is fixed.')))
        self.assertEqual(v[0], 'done')
        self.assertIn('nothing ran after the last edit', v[2])

    def test_edit_then_test_then_claim_passes(self):
        self.assertIsNone(C.judge(turn(tool('Edit', file_path='app.py'), tool('Bash', command='pytest'),
                                       say('The login bug is fixed; 14 tests pass.'))))

    def test_test_then_edit_again_is_blocked(self):
        v = C.judge(turn(tool('Bash', command='pytest'), tool('Edit', file_path='app.py'), say('All fixed.')))
        self.assertEqual(v[0], 'done')

    def test_failed_command_is_not_proof(self):
        v = C.judge(turn(tool('Edit', file_path='app.py'), tool('Bash', error=True, command='pytest'),
                         say('Tests pass now.')))
        self.assertEqual(v[0], 'done')

    def test_rereading_the_file_is_not_proof(self):
        v = C.judge(turn(tool('Edit', file_path='app.py'), tool('Read', file_path='app.py'), say('Deployed and working.')))
        self.assertIsNotNone(v)

    def test_updating_notes_after_the_check_is_fine(self):
        self.assertIsNone(C.judge(turn(tool('Edit', file_path='app.py'), tool('Bash', command='pytest'),
                                       tool('Edit', file_path='NOTES.md'), say('Fixed and verified.'))))

    def test_report_from_memory_needs_cited_proof(self):
        v = C.judge(turn(say('Everything is deployed.')))
        self.assertIn('from memory', v[2])
        self.assertIsNone(C.judge(turn(say('Everything is deployed (commit 3f9a2c1, CI green).'))))

    def test_saying_not_verified_always_passes(self):
        self.assertIsNone(C.judge(turn(tool('Edit', file_path='app.py'),
                                       say('I fixed the handler but have not verified it yet.'))))

    def test_quoted_or_code_claims_do_not_count(self):
        self.assertIsNone(C.judge(turn(tool('Edit', file_path='app.py'),
                                       say('I changed the message to `Done.` and the banner to "All set!"'))))

    def test_only_the_final_message_counts(self):
        # "fixed" in narration before the last tool call is not the answer
        t = turn(say('Looks like it is fixed, let me check.'), tool('Bash', command='pytest'), say('Here is the output.'))
        self.assertIsNone(C.judge(t))

    def test_chinese_claims(self):
        self.assertEqual(C.judge(turn(tool('Edit', file_path='a.py'), say('已修复,已上线。')))[0], 'done')
        self.assertIsNone(C.judge(turn(tool('Edit', file_path='a.py'), say('改好了,还没验证。'))))

    def test_words_that_only_look_like_claims(self):
        for text in ('Use the fixed header.', 'GitHub 主页装修好了', '按已验证的格式写', 'Is it fixed?'):
            self.assertIsNone(C._first(C.DONE, text), text)


class Absent(unittest.TestCase):
    def test_not_found_without_looking_is_blocked(self):
        v = C.judge(turn(say("That function doesn't exist anywhere in the repo.")))
        self.assertEqual(v[0], 'absent')

    def test_not_found_after_two_lookups_passes(self):
        self.assertIsNone(C.judge(turn(tool('Grep', pattern='parse_token'), tool('Glob', pattern='**/*.py'),
                                       say('parse_token is not used anywhere; nothing calls it.'))))

    def test_chinese_first_person_findings(self):
        self.assertEqual(C.judge(turn(say('全仓都没找到这个函数。')))[0], 'absent')
        self.assertIsNone(C._first(C.ABSENT, '如果找不到那个文件夹,看下面的路径'))

    def test_questions_are_not_claims(self):
        self.assertIsNone(C.judge(turn(say('Does the old endpoint still exist? 到底存不存在?'))))


class Turns(unittest.TestCase):
    def test_tool_results_and_injected_notes_do_not_start_a_turn(self):
        entries = (turn(tool('Edit', file_path='a.py'), tool('Bash', command='make test'))
                   + [{'type': 'user', 'isMeta': True, 'message': {'content': 'Stop hook feedback: ...'}},
                      say('Fixed, tests pass.')])
        ts = list(C.turns(entries))
        self.assertEqual(len(ts), 1)
        self.assertIsNone(C.judge(ts[0]))


class Hook(unittest.TestCase):
    def run_hook(self, entries, **extra):
        d = tempfile.mkdtemp()
        path = os.path.join(d, 't.jsonl')
        with open(path, 'w') as f:
            f.write('\n'.join(json.dumps(e) for e in entries) + '\n')
        C.LOG = os.path.join(d, 'blocks.jsonl')
        sys.stdin = io.StringIO(json.dumps(dict({'transcript_path': path, 'session_id': 's1'}, **extra)))
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = C.hook()
        return code, buf.getvalue(), C.LOG

    def test_blocks_once_and_logs(self):
        code, out, log = self.run_hook(turn(tool('Edit', file_path='a.py'), say('Fixed.')))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)['decision'], 'block')
        with open(log) as f:
            self.assertEqual(json.loads(f.readline())['kind'], 'done')

    def test_uses_the_final_message_claude_code_passes_in(self):
        # the transcript may not have the last message yet; the payload does
        _, out, _ = self.run_hook(turn(tool('Edit', file_path='a.py')), last_assistant_message='Fixed.')
        self.assertEqual(json.loads(out)['decision'], 'block')

    def test_second_stop_is_let_through(self):
        _, out, _ = self.run_hook(turn(tool('Edit', file_path='a.py'), say('Fixed.')), stop_hook_active=True)
        self.assertEqual(out, '')

    def test_broken_input_never_blocks(self):
        sys.stdin = io.StringIO('not json')
        self.assertEqual(C.hook(), 0)
        _, out, _ = self.run_hook([], transcript_path='/nope.jsonl')
        self.assertEqual(out, '')


if __name__ == '__main__':
    unittest.main()
