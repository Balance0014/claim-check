# claim-check

**AI 说「修好了」,先拿出证据。**

[English](README.md) · MIT · Python 3.9+,不用装任何依赖

![claim-check blocking an unproven "is fixed" in Claude Code, then the agent runs the tests and answers with the result](docs/demo.svg)

用 AI 写代码,最坑人的是两句话:一句是「修好了」,其实改完之后什么都没跑过;另一句是「这个没地方在用」,其实只搜了一次。两句听起来都像办完了,你就接着往下走,出了事才发现。

我拿自己 Claude Code 的 6,673 个回合重放了一遍:有 480 次以「做完了 / 修好了 / 上线了 / 测试通过」收尾,**其中 80 次拿不出证据,差不多每 6 次就有 1 次**:要么改完之后什么都没跑,要么是凭记忆汇报,没给提交号、测试结果或状态码。

claim-check 是一个收工钩子。AI 要结束这一轮的时候,它看 AI 嘴上说了什么,再对照你上一句话之后 AI 实际做了什么。缺证据,就把 AI 打回去一次,告诉它具体缺哪样。

## 怎么判

| AI 说 | 这一轮里必须有 |
| --- | --- |
| 「已修复」「已上线」「测试通过」「fixed」「deployed」 | **最后一次改代码之后**,至少跑过一条命令,而且没报错。回头再读一遍改过的文件不算;验完之后改笔记、改文档不影响。 |
| 同样的话,但这一轮一个操作都没做(纯汇报) | 回复里带证据:提交号、测试数、状态码、CI 链接。 |
| 「没找到」「没人调用」「doesn't exist」 | 至少查过两次。 |
| 「还没验证」「未测试」「not verified yet」 | 什么都不用。老实说没验,一律放行。 |

代码块里、引号里的话和问句不算。同一处最多拦一次,不会把 AI 卡死在循环里;它自己出错时一律放行。

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

```sh
python3 claim_check.py replay
```

读 `~/.claude/projects` 里的历史会话,算出你的 AI 说「做完了」时有多少次拿不出证据。数据不出你的电脑。

## 查它有没有拦错

每次拦截都记在 `~/.claude/claim-check/blocks.jsonl`,`python3 claim_check.py report` 列出最近几条。拦错了请[提 issue](https://github.com/Balance0014/claim-check/issues),附上被拦的那句话。误拦就是 bug。

## 它做不到的

- 它看的是句子,不是意图。AI 写「我认为应该可以了」就能绕过去。它是安全带,不是审计员。
- 改完之后跑过命令,只能证明跑了东西,不能证明测对了地方。
- 只认中文和英文。
- 只有 Claude Code 能强制;别的 agent 上是技能,照不照做看 AI 自己。

## 为什么做这个

我一个人开公司,手下大约 18 个 Claude Code 会话和 20 个定时 AI 任务([具体怎么管](https://github.com/Balance0014/one-person-ai-company);这个工具就是[第 5 章](https://github.com/Balance0014/one-person-ai-company/blob/main/playbook/zh-CN/05-definition-of-done.md)做成的钩子)。从 5 月起,我电脑上就装着这个钩子的早期版本,上周拦了 19 次。

写这一版时,我发现旧版有个 bug:它把工具返回的结果当成了我新说的话,所以只数 AI 最后一条消息里的查找,前面查过的全都看不见。我明明搜过好几遍的「没找到」,也被它拦了。新版按你真正打字的消息切分回合,每条规则都有两条测试:一条必须拦住,一条必须放行。

---

作者 [Balance Zhao](https://github.com/Balance0014)。[在 X 上关注](https://x.com/balance0014),下一个工具发布时第一时间知道。
