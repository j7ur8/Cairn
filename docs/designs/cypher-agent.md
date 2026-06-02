# Cypher Agent 设计方案

> 目标：以 Cairn 为母版，吸收 Pentest-Swarm-AI 的真实 swarm / stigmergy 思路，以及 CyberStrikeAI 的角色、技能、工具编排、知识库与审计能力，设计一个面向 **自动化 CTF、授权渗透测试、漏洞挖掘** 的 Cypher Agent。

## 1. 一句话定位

**Cypher Agent = Cairn 的事实图搜索内核 + Pentest-Swarm-AI 的信息素式安全发现流 + CyberStrikeAI 的安全角色/技能/工具生态。**

它不是再做一个固定“信息收集 → 扫描 → 利用 → 报告”的流水线，而是在 Cairn 的 Fact / Intent / Hint 黑板上，把每个安全发现转成可追踪的事实节点，把每个攻击假设转成可并行探索的意图节点，由 Dispatcher 持续调度 Agent Worker 逼近目标。

## 2. 三个项目分别贡献什么

### 2.1 Cairn：母版与执行内核

保留 Cairn 的核心机制：

- `Fact`：已确认事实，例如开放端口、HTTP 指纹、PoC 成功、flag、root 权限证明。
- `Intent`：待探索方向，例如“验证 `/api/upload` 是否存在任意文件写入”。
- `Hint`：人类提示、赛题附件说明、ROE、目标范围、禁止项。
- `Bootstrap / Reason / Explore` 三类任务。
- Dispatcher 是唯一协议写入者，Agent 只输出 JSON。
- 每个项目一个隔离 worker container，可挂载附件和项目工作目录。
- Execution Log 记录 prompt、stdout、stderr 和 trace，便于复盘。

### 2.2 Pentest-Swarm-AI：swarm 行为与安全发现分类

借鉴但不照搬 Go 实现：

- Stigmergy：Agent 通过共享黑板间接协作。
- Finding Type：把安全发现归类为 `TARGET_REGISTERED`、`PORT_OPEN`、`HTTP_ENDPOINT`、`TECHNOLOGY`、`CVE_MATCH`、`EXPLOIT_RESULT`、`SESSION` 等。
- Pheromone：对高价值发现加权，随时间衰减，调度优先探索“新鲜且高信号”的路径。
- Trigger Predicate：不同探索方向由事实类型触发，而不是中央 Planner 硬编码阶段。
- Playbook：CTF / bug bounty / external ASM / internal network 等不同 profile 的默认探索模板。
- Scope enforcement 与 cleanup registry：范围约束、清理与可回滚作为一等约束。

### 2.3 CyberStrikeAI：角色、技能和工具生态

借鉴其产品化能力：

- 角色：侦察、漏洞分诊、渗透利用、权限提升、横向移动、报告修复、清理回滚等。
- Skills：SQLi、XSS、SSRF、文件上传、命令注入、IDOR、XXE、云安全、容器安全、代码审计、二进制、取证等 skill pack。
- MCP / Tool catalog：将工具调用能力以目录/配方方式描述，后续可以桥接 MCP。
- Project facts：项目级共享事实，天然对应 Cairn 的 Fact 图。
- Vulnerability management / report：把最终 exploit evidence 转成报告、复现步骤、修复建议。
- HITL / audit：高风险动作、破坏性测试、持久化、C2 等能力需要审计和可选人工确认。

## 3. 设计原则

1. **以 Cairn 为内核，不重写调度器**：第一阶段只新增 prompt group 和 skills，即可运行。
2. **事实优先，工具其次，角色最后**：所有角色都围绕 Fact / Intent 写入，不做信息孤岛。
3. **CTF 与授权测试默认可信范围内执行**：但依然记录 scope、ROE、清理动作与证据链。
4. **输出契约不破坏现有 Cairn**：Agent 仍只返回现有 JSON contract。
5. **先用文本约定表达增强元数据**：在不改数据库的情况下，用结构化前缀表达 finding type、confidence、severity、artifact。
6. **后续再扩 schema**：当第一版稳定后，再为 facts/intents 增加 metadata JSON、priority、tags、pheromone 等字段。
7. **可复现比“看起来聪明”更重要**：每个关键发现要能给出命令、请求、文件、证据路径或复现条件。

## 4. 总体架构

```text
User / API / UI
      |
      v
Cairn Server
  - Projects / Facts / Intents / Hints
  - Capability catalog
  - Execution Log
      ^
      |
Cairn Dispatcher
  - prompt_group = cypher
  - worker selection
  - container lifecycle
  - capability injection
      |
      v
Project Worker Container
  - Codex / Claude Code / Pi
  - Kali / ProjectDiscovery / pwn / reverse / cloud tools
  - /mnt/attachments read-only
  - /mnt/project writable evidence workspace
  - Cypher skills under /tmp/cairn-capabilities/...
```

## 5. Cypher 的三种工作 Profile

Cypher 不固定为单一角色，而是根据 Origin / Goal / Hints 自动推断 profile。

| Profile | 目标形态 | 典型完成条件 | 主要证据 |
| --- | --- | --- | --- |
| `ctf` | CTF / 靶场 / 赛题 | flag、shell、root、题目平台提交成功 | flag 字符串、利用脚本、命令输出、提交回执 |
| `pentest` | 授权渗透测试 / SRC / Bug bounty | 可复现漏洞、影响证明、风险评级、修复建议 | HTTP 请求响应、PoC 输出、截图、日志、payload、清理记录 |
| `vuln_research` | 漏洞挖掘 / 代码审计 / CVE 复现 | root cause、PoC、影响范围、补丁建议 | 代码路径、栈回溯、崩溃样本、PoC、patch diff |

Profile 可在 Hint 中显式指定：

```text
profile: ctf
scope: 10.10.11.42 only
goal: get user.txt and root.txt
attachments: /mnt/attachments/box-src
```

## 6. 兼容当前 Cairn 的结构化文本约定

当前 Cairn 的 `Fact.description` / `Intent.description` 是纯文本。为了不改代码先落地，Cypher 使用一行结构化前缀。

### 6.1 Fact 前缀

```text
[cypher:finding type=HTTP_ENDPOINT confidence=0.86 severity=info tags=web,recon artifacts=/mnt/project/httpx.json cleanup=none] http://10.10.11.42:8080 is alive; title="Admin"; tech="Spring Boot".
```

字段建议：

| 字段 | 含义 |
| --- | --- |
| `type` | 发现类型，见第 7 节 taxonomy |
| `confidence` | 0.0 - 1.0，证据强度 |
| `severity` | info / low / medium / high / critical |
| `tags` | web、ad、cloud、ctf、pwn、reverse、crypto 等 |
| `artifacts` | 证据文件或目录 |
| `cleanup` | none / required / done / tmux:<session> |

### 6.2 Intent 前缀

```text
[cypher:intent lane=web_exploit priority=0.91 triggers=HTTP_ENDPOINT,TECHNOLOGY expected=EXPLOIT_RESULT cost=medium destructiveness=low] Verify whether the Spring Boot actuator exposure can leak credentials or enable RCE.
```

字段建议：

| 字段 | 含义 |
| --- | --- |
| `lane` | 探索泳道，如 recon、web_enum、web_exploit、privesc、report |
| `priority` | 0.0 - 1.0，越高越应优先执行 |
| `triggers` | 由哪些 finding type 触发 |
| `expected` | 期望产出的 finding type |
| `cost` | low / medium / high |
| `destructiveness` | none / low / medium / high |

## 7. Cypher Finding Taxonomy

| Type | 含义 | 触发的典型 Intent |
| --- | --- | --- |
| `TARGET_REGISTERED` | 初始目标 / 范围 | recon、scope parsing |
| `SCOPE_RULE` | 范围、ROE、禁止项 | scope guard、tool config |
| `HOST_ALIVE` | 存活主机 | port scan、web probe |
| `PORT_OPEN` | 端口开放 | service fingerprint、CVE check |
| `SERVICE` | 服务与版本 | CVE match、default creds、protocol exploit |
| `HTTP_ENDPOINT` | HTTP 路径/接口 | spider、parameter discovery、auth bypass |
| `TECHNOLOGY` | 框架、中间件、CMS | CVE / misconfig / source audit |
| `PARAMETER` | 输入点 | SQLi、XSS、SSRF、IDOR、RCE 测试 |
| `VULN_CANDIDATE` | 候选漏洞 | targeted verification |
| `CVE_MATCH` | 版本或指纹命中 CVE | PoC validation |
| `MISCONFIGURATION` | 配置错误 | impact proof |
| `SECRET_LEAK` | token、password、key、config | credential validation、scope check |
| `CREDENTIAL` | 可用凭据 | login、lateral movement、privilege step |
| `EXPLOIT_PRIMITIVE` | 文件写、命令执行、SSRF 等原语 | chain building |
| `EXPLOIT_RESULT` | 利用成功证据 | session stabilize、flag collection、report |
| `SESSION` | shell / webshell / token / implant session | post-exploit、privesc、cleanup |
| `PRIVESC_VECTOR` | 提权线索 | local privesc verification |
| `LATERAL_PATH` | 横向路径 | internal recon、credential reuse |
| `FLAG` | CTF flag | submit / complete |
| `REPO_FINDING` | 代码审计发现 | root cause、PoC |
| `BINARY_FINDING` | 二进制分析发现 | exploit dev |
| `CRYPTO_FINDING` | 密码学中间结论 | transform chain continuation |
| `FORENSIC_ARTIFACT` | 取证/隐写证据 | decode / carve / timeline |
| `OOB_CALLBACK` | DNSLog/HTTP callback | blind vuln confirmation |
| `REPORT_FINDING` | 报告项 | final report |
| `BLOCKER` | 阻塞/失败事实 | reason course-correction |

## 8. 角色不是固定 Agent，而是 Intent Lane

Cairn 原生 Worker 无固定角色。Cypher 保持这一点：角色通过 `lane` 与 prompt 指令动态激活。

| Lane | 借鉴来源 | 主要任务 |
| --- | --- | --- |
| `scope_seed` | Pentest seed + CyberStrike engagement planning | 解析范围、目标、禁止项、完成条件 |
| `recon` | Pentest-Swarm recon / CyberStrike intel | 主机、端口、Web、指纹、目录、JS、源码、附件盘点 |
| `triage` | classifier / vulnerability-triage | 候选漏洞排序、去重、验证路径设计 |
| `web_exploit` | exploit / penetration | Web 漏洞验证、认证绕过、业务逻辑、RCE、SSRF、SQLi |
| `service_exploit` | exploit | SSH/SMB/Redis/数据库/中间件等服务利用 |
| `ctf_specialist` | CTF role | Pwn、Reverse、Crypto、Forensics、Stego 专项 |
| `vuln_research` | secure-code-review / CVE workflow | 代码审计、PoC、root cause、patch diff、fuzz |
| `post_exploit` | privilege-escalation / lateral | 稳定 shell、提权、凭证、横向、flag 收集 |
| `oob_support` | CyberStrike C2/OOB 思路 | DNSLog、callback server、reverse shell 接收、tmux 记录 |
| `report_cleanup` | reporting-remediation / cleanup | 报告、修复建议、清理、复现实验步骤 |

## 9. Reason 策略

Cypher 的 `reason` 不是写长计划，而是根据事实图生成 **少量高价值、可并行、可验证** 的 intent。

优先级：

1. 如果已有 `FLAG` / `EXPLOIT_RESULT` / root proof 足以满足 Goal，立即 `complete`。
2. 若存在高置信 `VULN_CANDIDATE`，优先验证，不继续盲扫。
3. 若只有目标但无资产，生成 recon intent。
4. 若有 Web 资产，生成 endpoint/parameter/tech-specific intents。
5. 若有凭据或 session，生成 post-exploit / privesc intents。
6. 若探索失败，生成 course-correction intent，不重复旧方向。
7. 每轮最多 `{max_intents}` 个，不制造低质量任务。

## 10. Dispatcher 扩展建议

### 10.1 零代码可用版

- 新增 `prompt_group: cypher`。
- 新增 `capabilities/skills/cypher-*`。
- 在 `dispatch.yaml` 里启用这些 skill。
- Agent 在 `Fact.description` / `Intent.description` 使用 Cypher 前缀。

### 10.2 小改版：优先级与去重

在 Dispatcher 选择 open intent 时，解析 `[cypher:intent priority=...]`：

```text
score = priority * pheromone_decay * novelty_bonus - duplicate_penalty - cost_penalty
```

改动点：

- `cairn/src/cairn/dispatcher/scheduler/loop.py`：选择 intent 时从“新建优先”改为“score 优先”。
- 新增 `dispatcher/cypher/metadata.py`：解析结构化前缀。
- 新增 `dispatcher/cypher/scoring.py`：计算 intent score。

### 10.3 中改版：schema 扩展

建议新增字段：

```sql
ALTER TABLE facts ADD COLUMN kind TEXT;
ALTER TABLE facts ADD COLUMN severity TEXT;
ALTER TABLE facts ADD COLUMN confidence REAL;
ALTER TABLE facts ADD COLUMN tags TEXT;       -- JSON array
ALTER TABLE facts ADD COLUMN metadata TEXT;   -- JSON object

ALTER TABLE intents ADD COLUMN lane TEXT;
ALTER TABLE intents ADD COLUMN priority REAL;
ALTER TABLE intents ADD COLUMN tags TEXT;     -- JSON array
ALTER TABLE intents ADD COLUMN metadata TEXT; -- JSON object
```

### 10.4 强化版：真正 swarm trigger

在 Reason 之外增加 trigger scheduler：

- `FindingType -> Lane` 映射。
- 每类 lane 有并发上限。
- 每个 finding 有 pheromone half-life。
- intent 生成可以由 rule + LLM 共同完成。
- 重复 intent 通过 embedding / normalized key 去重。

示例触发规则：

```yaml
triggers:
  - when: [HTTP_ENDPOINT, PARAMETER]
    lane: web_exploit
    min_confidence: 0.5
    templates: [sqli, xss, ssrf, idor]
  - when: [SERVICE]
    lane: service_exploit
    min_confidence: 0.7
  - when: [SESSION]
    lane: post_exploit
    min_confidence: 0.8
  - when: [REPO_FINDING]
    lane: vuln_research
```

## 11. Skill 设计

最小 skill 组：

| Skill | 用途 |
| --- | --- |
| `cypher-ctf` | CTF 类型识别、flag 工作流、Web/Pwn/Reverse/Crypto/Forensics 方法 |
| `cypher-pentest` | 授权渗透测试、scope、证据、漏洞验证、清理与报告 |
| `cypher-vuln-research` | 代码审计、CVE 复现、PoC 改造、fuzz、root cause |
| `cypher-flag-oob` | flag 提交、DNSLog/OOB、反连接收、tmux 长任务记录 |

后续可从 CyberStrikeAI 迁移细分 skill：

- `sql-injection-testing`
- `xss-testing`
- `ssrf-testing`
- `file-upload-testing`
- `command-injection-testing`
- `idor-testing`
- `xxe-testing`
- `network-penetration-testing`
- `container-security-testing`
- `cloud-security-audit`
- `secure-code-review`

## 12. 工具层建议

Worker container 推荐覆盖：

| 类别 | 工具 |
| --- | --- |
| 基础侦察 | `nmap`, `masscan/rustscan`, `naabu`, `httpx`, `subfinder`, `dnsx`, `katana`, `gau` |
| Web 测试 | `ffuf`, `feroxbuster`, `dirsearch`, `nuclei`, `nikto`, `sqlmap`, `dalfox`, `arjun` |
| 服务/内网 | `netexec`, `impacket-*`, `kerbrute`, `bloodhound`, `chisel`, `proxychains` |
| 云/容器 | `trivy`, `checkov`, `kube-hunter`, `prowler` |
| 代码/Secrets | `semgrep`, `gitleaks`, `trufflehog`, `ripgrep`, `jq`, `yq` |
| Pwn/Reverse | `pwntools`, `gdb`, `radare2`, `ropper`, `ROPgadget`, `binwalk`, `strings` |
| Crypto/Forensics | `john`, `hashcat`, `exiftool`, `foremost`, `steghide`, `zsteg`, `volatility3` |
| 浏览器 | `playwright-cli` |

## 13. Evidence Workspace 约定

每个项目使用 `/mnt/project` 保存证据：

```text
/mnt/project/
  recon/
    nmap.xml
    httpx.jsonl
    katana.jsonl
  exploit/
    poc.py
    request.txt
    response.txt
    shell.log
  vuln-research/
    root-cause.md
    crash.bin
    patch.diff
  reports/
    finding-001.md
    final.md
  cleanup/
    actions.md
```

Fact 中只写摘要和路径，避免塞长日志。

## 14. 完成条件定义

### CTF

可以 complete 的条件：

- 找到目标 flag，且格式/来源可信；或
- 平台提交返回成功；或
- Goal 明确要求 shell/root，已取得可复现权限证明。

### Pentest

可以 complete 的条件：

- Goal 是发现漏洞：至少一个漏洞有可复现证据、影响说明和修复建议。
- Goal 是全量评估：完成范围内枚举、验证、报告与清理记录。

### Vuln Research

可以 complete 的条件：

- 已确认 root cause。
- 有最小 PoC 或崩溃/利用证明。
- 有影响范围、利用条件、修复建议或 patch diff。

## 15. Prompt Group 设计

`cypher` prompt group 保持 Cairn JSON contract，但加入以下行为：

- 先识别 profile / scope / goal。
- 优先读 `/mnt/attachments` 与 `/mnt/project`。
- 每个关键命令保存到 evidence workspace。
- 主动生成结构化 cypher 前缀。
- Reason 阶段只提出高价值 intent。
- Explore 阶段只做当前 intent，不漂移。
- Conclude 阶段禁止继续执行，只总结已确认事实。

## 16. `dispatch.yaml` 示例片段

不要直接复制真实 key。示例：

```yaml
runtime:
  prompt_group: "cypher"

tasks:
  bootstrap:
    timeout: 600
    conclude_timeout: 120
  reason:
    timeout: 240
    max_intents: 3
  explore:
    timeout: 900
    conclude_timeout: 120

capabilities:
  skills:
    - id: "cypher-ctf"
      name: "Cypher CTF"
      description: "CTF solving workflows for web/pwn/reverse/crypto/forensics/misc."
      source_path: "./capabilities/skills/cypher-ctf"
      task_types: ["bootstrap", "explore", "reason"]
    - id: "cypher-pentest"
      name: "Cypher Pentest"
      description: "Authorized pentest workflows, evidence, scope, cleanup, reporting."
      source_path: "./capabilities/skills/cypher-pentest"
      task_types: ["bootstrap", "explore", "reason"]
    - id: "cypher-vuln-research"
      name: "Cypher Vuln Research"
      description: "Code audit, CVE reproduction, PoC adaptation, fuzzing and root cause analysis."
      source_path: "./capabilities/skills/cypher-vuln-research"
      task_types: ["bootstrap", "explore", "reason"]
    - id: "cypher-flag-oob"
      name: "Cypher Flag and OOB"
      description: "Flag submission, DNSLog/OOB callback and tmux long-running listener conventions."
      source_path: "./capabilities/skills/cypher-flag-oob"
      task_types: ["bootstrap", "explore"]
```

## 17. 里程碑

### M0：Prompt + Skill 最小可用

- 新增 `cairn/src/cairn/dispatcher/prompts/cypher/`。
- 新增 `capabilities/skills/cypher-*`。
- 修改 `dispatch.yaml` 的 `runtime.prompt_group` 和 `capabilities.skills`。
- 不改数据库、不改 dispatcher。

### M1：结构化前缀解析与优先级探索

- 新增 Cypher metadata parser。
- Dispatcher 选择 intent 时按 priority 排序。
- UI 展示 fact/intents tags。

### M2：Schema 扩展

- Facts / Intents 增加 metadata 字段。
- API / UI 支持查询、过滤、统计。
- Reason 可基于结构化 taxonomy 做更稳的去重。

### M3：Tool/MCP 与报告系统

- 引入 CyberStrikeAI 风格 tool catalog。
- 关键工具输出统一归档到 `/mnt/project`。
- 自动生成 Markdown / JSON / SARIF 报告。

### M4：Pheromone Swarm

- 增加 half-life、decay、trigger predicate。
- 独立 lane 并发限流。
- Budget-aware 调度。
- Duplicate suppression 与 memory graft。

## 18. 推荐的第一版落地方式

最稳路线：

1. 使用本设计附带的 `cypher` prompt group。
2. 在 `dispatch.yaml` 中启用四个 Cypher skills。
3. 新建项目时，在 Origin/Hints 中明确：profile、scope、goal、附件路径、禁止项。
4. 先跑 CTF / 靶场 / 离线源码审计场景验证。
5. 再做授权 Web / SRC 场景。
6. 稳定后再做 dispatcher priority 与 schema 扩展。

## 19. 项目命名解释

`Cypher` 有三层含义：

- **cipher / cypher**：解密未知状态空间，适合 CTF、漏洞挖掘。
- **graph query language**：Cairn 本质是事实图搜索，Cypher 在图上找路径。
- **operator handle**：像一个自动化安全操作员，负责从线索到证据到报告的闭环。

---

## 附录：项目级 Capabilities 与 Role Prompt

关于“创建项目时选择 MCP / Skills”以及“项目主角色 prompt 注入 bootstrap / explore / reason”的详细修订方案，见：

- `docs/designs/cypher-capabilities-roles.md`
