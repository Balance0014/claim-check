# claim-check

**AI 说「修好了」,先拿出证据。**

[English](README.md) · MIT · Python 3.9+,不用装任何依赖

![claim-check 在 Claude Code 里拦下一句没有证据的「修好了」,AI 跑完测试后带着结果重新回答](docs/demo.svg)

用 AI 写代码,最坑人的是两句话:一句是「修好了」,其实改完之后什么都没跑;另一句是「这个没地方在用」,其实只搜了一次。两句听着都像办完了,我就接着往下走,等出了问题才发现。

2026 年 10 月 28 日,我拿自己 Claude Code 的 5,429 个回合重放了一遍:有 560 次以「做完了 / 修好了 / 上线了 / 测试通过」收尾,**其中 112 次拿不出证据,每 5 次就有 1 次**:要么改完之后什么都没跑,要么是凭记忆汇报,没给提交号、测试结果或状态码。说「没找到」的 26 次里,有 4 次查了不到两遍。

claim-check 是一个 Stop 钩子(AI 每轮停下时自动运行)。AI 想结束这一轮时,它把 AI 嘴上说的,和你上一句话之后 AI 实际跑过的东西对一遍。缺证据,就把 AI 打回去一次,告诉它具体缺什么:

```text
claim-check: you wrote "is fixed", but nothing ran after the last edit. Run the check
that proves it (tests, the command, a request to the live URL) and show the result,
or say plainly that it is not verified yet.
```

## 怎么判

| AI 说 | 这一轮里必须有 |
| --- | --- |
| 「已修复」「已上线」「测试通过」「fixed」「deployed」 | **最后一次改代码之后**真跑过点东西,而且没报错:一条命令、一次浏览器或接口调用、一次网页请求,或者一个子任务。回头再读一遍改过的文件、更新待办清单都不算;验完之后改笔记、改文档没关系。 |
| 同样的话,但这一轮一个操作都没做(纯汇报) | 回复里带证据:提交号、测试数、状态码、CI 链接。 |
| 「没找到」「没人调用」「doesn't exist」 | 至少读过、搜过或跑过两次。 |
| 「还没验证」「未测试」「not verified yet」 | 什么都不用。老实说没验,一律放行。 |

代码块里、引号里的话和问句不算。它不会连着拦两次,所以不会把 AI 卡死在循环里;它自己出了 bug 也不会拦人。

## 安装

**Claude Code 插件:**

```text
/plugin marketplace add Balance0014/claim-check
/plugin install claim-check@claim-check
```

装完开一个新会话。

**不用插件:** 把 `claim_check.py` 放到任意位置,在 `~/.claude/settings.json` 里加上:

```json
{
  "hooks": {
    "Stop": [{ "hooks": [{ "type": "command", "command": "python3 /path/to/claim_check.py" }] }]
  }
}
```

**Codex 和其他 agent:** `npx skills add Balance0014/claim-check` 装的是同一套规矩的技能版。AI 会读,但没有东西强制它照做。Codex 有自己的钩子机制,这一版还没接。

## 看看你自己的比例

克隆仓库后运行:

```sh
python3 claim_check.py replay
```

它读 `~/.claude/projects` 里的历史会话,算出你的 AI 说「做完了」时有多少次拿不出证据。数据不出你的电脑。

## 查它有没有拦错

每次拦截都记在 `~/.claude/claim-check/blocks.jsonl`,`python3 claim_check.py report` 列出最近十条。拦错了请[提 issue](https://github.com/Balance0014/claim-check/issues),附上被拦的那句话。误拦就是 bug。

## 它做不到的

- 它认的是说法,AI 写「我认为应该可以了」就能绕过去。
- 改完之后跑过命令,只能证明跑了东西,证明不了测对了地方。
- 只认得中文和英文的说法。
- 它只认 Claude Code 自带的改文件工具。用 `sed -i` 这类命令改的文件,它看不出是改动。
- Windows 上如果没有 `python3` 命令,把 `hooks/hooks.json` 或设置里的 `python3` 改成 `python`。
- 只有 Claude Code 能强制;别的 agent 上是技能,照不照做看 AI 自己。

## 为什么做这个

我一个人开公司,同时开着大约 18 个 Claude Code 会话,还有 20 个定时 AI 任务([具体怎么管](https://github.com/Balance0014/one-person-ai-company);这个工具就是其中[第 5 章](https://github.com/Balance0014/one-person-ai-company/blob/main/playbook/zh-CN/05-definition-of-done.md)做成的钩子)。从 5 月起,我电脑上就装着它的早期版本,上周拦了 19 次。

写这一版时,我发现旧版有个 bug:它把工具返回的结果也当成了我新说的话,所以只数 AI 最后一条消息里的查找,前面查过的全都看不见。有一次 AI 明明已经搜过好几遍才说「没找到」,还是被它拦了。新版只把你亲手打的字算作新一轮,每条规则都有两条测试:一条必须拦住,一条必须放行。

---

作者 [Balance Zhao](https://github.com/Balance0014)。[在 X 上关注](https://x.com/balance0014),下一个工具发布时第一时间知道。
