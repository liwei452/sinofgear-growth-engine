# Task 6 实施报告

## 状态

- 实现提交：`feat: clarify results and company knowledge`（本报告随该提交）
- 范围：效果页、我的公司页、`NextStepPanel`，以及为中止信号、状态筛选和安全游标翻页所需的最小 API helper 改动。

## RED

命令：

```text
cd frontend
C:\tmp\task-10b-node\node-v22.21.1-win-x64\node.exe node_modules/vitest/vitest.mjs --run src/modules/analytics/AnalyticsPage.test.ts src/modules/company/CompanyProfilePage.test.ts
```

首次结果：失败 4 项，原因均为预期缺失行为：没有“效果”与“AI 结论”结构、仍显示内部标识、没有八类公司理解与真实覆盖、公司查询只有 3 个且未透传中止信号。

自审追加 RED：失败 3 项，分别证明不同日期窗口被错误比较、加载期间过早声称完整度、能力重试会请求无权限的产品来源。

独立审查追加 RED：先失败 4 项，分别证明不完整的汇总页被当作完整结果比较、平台并列时仍声称有领先者、名称只解析列表第一页、未审核或非启用记录被计入公司理解；复审再失败 1 项，证明已审核概念关联的非审核证据仍会被错误计入覆盖。

## GREEN

聚焦命令：

```text
C:\tmp\task-10b-node\node-v22.21.1-win-x64\node.exe node_modules/vitest/vitest.mjs --run src/modules/analytics/AnalyticsPage.test.ts src/modules/company/CompanyProfilePage.test.ts
```

结果：2 个测试文件、25 项测试全部通过。

API 回归命令：

```text
C:\tmp\task-10b-node\node-v22.21.1-win-x64\node.exe node_modules/vitest/vitest.mjs --run src/modules/analytics/AnalyticsPage.test.ts src/modules/company/CompanyProfilePage.test.ts src/modules/products/api.test.ts src/modules/assets/api.test.ts src/modules/knowledge/api.test.ts src/modules/content/api.test.ts
```

结果：6 个测试文件、43 项测试全部通过。

静态与构建验证（因默认 `node.cmd` 指向不存在的英文路径，直接使用可用英文 Node 执行对应入口）：

```text
C:\tmp\task-10b-node\node-v22.21.1-win-x64\node.exe node_modules/vue-tsc/bin/vue-tsc.js --noEmit
C:\tmp\task-10b-node\node-v22.21.1-win-x64\node.exe node_modules/eslint/bin/eslint.js .
C:\tmp\task-10b-node\node-v22.21.1-win-x64\node.exe node_modules/vite/bin/vite.js build
```

结果：类型检查、Lint、生产构建均退出 0。

独立复审结论：`Ready: yes`，未发现新的 Critical 或 Important 问题。

## 关键实现结论

- 效果页固定为结论、关键指标、趋势、下一步、折叠运营详情；筛选、追踪链接、短链接和发布记录仍保留原权限、分页与创建边界。
- 只有完整汇总页中的至少两个平台拥有相同的多个日期窗口时才比较；并列时明确报告持平，任何情况下都不从点击汇总推断因果。
- 活动、平台、产品能解析时显示真实名称；活动和产品名称会沿安全游标读取后续页，不能解析时显示“名称暂不可用”，不把 UUID 作为主标签。
- 我的公司按真实组织、产品、能力、行业、工艺、标准、证据和素材计算八项覆盖；加载失败或无权限来源不会被误报为缺失。
- 公司理解只采用启用产品与素材，以及已审核知识概念与证据；证据覆盖只依据已审核证据接口结果，客户端仍会再次过滤异常状态，避免把无效记录算入覆盖。
- 产品、知识概念、知识证据和素材查询都透传 Vue Query 的 `AbortSignal`；组织切换测试确认旧请求被中止且旧响应不回写当前页面。

## 担忧与边界

- 名称解析会沿现有列表接口返回的安全游标读取后续页；循环游标会停止，解析失败会安全降级为“名称暂不可用”。
- 产品会沿安全同源游标读取最多 100 页，并按完成状态诚实显示“已读取全部”或“已安全加载前”；素材数量仍明确写为“当前页”。效果汇总存在后续页时不会做跨平台结论，并明确标记当前页维度。
- 平台比较门槛刻意保守，点击数据不满足共同日期窗口时只报告数据不足。
- 名称解析会串行读取安全游标页，并以规范化游标判重、最多读取 100 页；超过上限的名称安全降级为“名称暂不可用”。后续仍可用按 ID 查询进一步降低延迟。
- 全量前端套件并行运行时，范围外 `LeadRadarPage` 的 50 条并发水位测试曾出现一次 44/50 的时序失败；该文件隔离重跑 17/17 通过，Task 6 相关回归稳定通过。
- 未新增浏览器端 E2E；组件、API、类型、Lint 与生产构建已覆盖本次变更。

## Fix round 1

### 复审问题与 RED

- 权限撤销：新增双向权限切换与迟到响应测试，先证明已缓存的产品/知识会越过最新权限进入组合能力与覆盖结果。
- 公司知识边界：新增组织知识、产品显式关联系统知识、跨组织知识和证据的混合测试，先证明未关联 SYSTEM 概念与证据会被误计为公司事实。
- 产品全量：新增第二个安全产品页包含能力的测试，先证明首屏会产生错误能力缺口。
- 失败来源：增强来源失败测试，先证明徽标仍显示“仍有可补充项”。
- 名称游标：新增等价查询顺序循环与 100 页唯一游标测试，先证明语义相同游标未判重、唯一游标可无限读取。
- 平台并列：新增三个平台中前两名并列测试，先证明页面会用“全部平台持平”的措辞掩盖第三名更低的事实。

### GREEN 实现

- 所有组合计算都在读取查询缓存前再次检查当前权限；权限撤销后旧缓存和迟到响应均不会进入产品、概念、证据或素材结果。
- 直接公司知识只接受 `APPROVED + ORGANIZATION + 当前组织`；SYSTEM 概念只在当前 ACTIVE 产品的 `concept_links` 显式关联时计入。证据只接受当前组织已审核证据，或由已计入公司概念通过真实 `evidence` 关系显式引用的已审核 SYSTEM 证据。
- 公司页沿同源、同 `/api/v1/products` 端点加载 ACTIVE 产品，传递 `AbortSignal`，用规范化游标键判重并设置 100 页上限；完整与截断计数采用不同文案。
- 失败来源徽标改为“部分资料暂不可用”，缺口继续只由成功来源计算。
- 分析页活动/产品名称解析用规范化游标键判重并设置 100 页硬上限；未解析名称保持“名称暂不可用”。最高点击数并列统一说明“最高点击数并列，暂无唯一领先平台”。

### Fix round 1 验证

```text
公司页 + 分析页：2 个文件，32/32 通过
公司/分析/API 关联集：6 个文件，50/50 通过
受共享游标影响面隔离复验：审核中心 + 推广页，23/23 通过
全量前端：43 个文件，437/437 通过
vue-tsc --noEmit：退出 0
eslint .：退出 0
vite build：退出 0（176 个模块）
git diff --check：退出 0
```

全量验证首次运行揭示共享安全 URL helper 被过度规范化，改变了范围外页面的实际请求参数顺序；实现随后收窄为仅规范化本页循环判重键、保留原请求 URL。受影响页面隔离复验及全量前端复验均通过。

### 剩余边界

- 100 页上限是防御性边界；超过上限的产品计数明确标记为“已安全加载前”，名称则安全降级，不声称完整。
- 仓库没有稳定的产品证据 `source_object_type` 约定，因此本轮没有猜测自由文本关系；SYSTEM 证据只通过概念现有 `evidence` 字段与已计入的公司概念建立关联。

## Fix round 2

### 根因与 RED

公司页原先把查询 `isSuccess` 当成来源完整，产品安全加载返回 `complete: false` 时仍计算精确覆盖和缺口；能力、行业、工艺、标准又没有统一等待产品与知识两个当前可读贡献源。结果是网络失败、无效游标、循环游标或 100 页截断都可能被误报为资料缺失。

新增 10 个用例后，公司文件首次运行 27 项中 9 项按预期失败，覆盖：

- 产品无效游标、初始游标循环和 100 页上限；
- 产品失败 + 知识成功，以及知识失败 + 产品成功；
- 仅产品、仅知识、两者都不可读三种权限组合；
- 初始请求游标循环重复抓取；
- 相同产品 ID 跨页重复计数。

### GREEN 实现

- 为八类覆盖定义 `ready / pending / unknown / unavailable` 分类状态。产品依赖完整产品源；能力、行业、工艺、标准组合所有当前可读的产品与知识贡献源；证据组合知识概念与证据请求；素材依赖素材源；组织身份独立。
- 任一当前可读贡献源失败、截断或循环时，依赖分类成为 `unknown`。顶部显示“已确认 N 项，另有资料暂无法判断”和“部分资料暂不可用”，不会显示精确 `N/8` 覆盖。
- 缺口只在分类为 `ready` 且值为空时生成；网络失败、截断与无权限均不会被转换成缺失。
- 各分类卡片在未知状态明确说明资料暂无法完整读取、当前是否存在缺口无法判断。
- 产品游标集合预置初始 ACTIVE 请求的规范化键，阻止初始游标回环；跨页产品按 ID 保留首个记录并去重。

### Fix round 2 验证

```text
公司页：1 个文件，27/27 通过
公司页 + 分析页：2 个文件，42/42 通过
公司/分析/API 关联集：6 个文件，60/60 通过
全量前端：43 个文件，447/447 通过
vue-tsc --noEmit：退出 0
eslint .：退出 0
vite build：退出 0（176 个模块）
git diff --check：退出 0
```

### 剩余边界

- 产品与名称读取仍采用 100 页防御上限；达到上限后刻意保持未知，不生成缺口。
- 素材接口仍不主动追取后续页；存在 `next` 时该分类现在按未知处理，因此不会把当前页空结果误报为素材缺失。

## Fix round 3

### 根因与 RED

证据分类原先只组合知识概念与证据接口的就绪状态，但真实 SYSTEM 证据链还依赖当前 ACTIVE 产品的 `concept_links`。因此，当产品源可读但挂起、失败、游标异常或达到分页上限时，页面会把知识与证据接口的完整空结果误判为可确认的证据缺口。

- 反转了原先“产品失败仍可生成证据缺口”的错误断言。
- 新增并先验证 5 个失败场景：产品请求挂起、请求失败、无效游标、循环游标和 100 页截断；修复前均会错误显示“补充证据”或精确缺口数。
- 复用并强化产品无权限、产品完整为空、产品关联 SYSTEM 证据、知识源失败和权限组合用例，确保边界没有被放宽。

### GREEN 实现

- 当知识可读时，证据分类现在组合产品、知识概念和证据三个源的就绪状态；任一真实依赖源挂起则保持挂起，失败或不完整则保持未知，只有三个源都完整时才允许生成“补充证据”。
- 当产品不可读时，产品源不参与证据判断；知识与证据均完整为空时仍可诚实生成证据缺口。当知识不可读时，证据分类保持不可用。
- 证据分类未知时仍展示已经成功读取的组织知识和直接组织证据；重试仅触发当前有权读取的产品、知识和证据请求。

### Fix round 3 验证

```text
公司页：1 个文件，28/28 通过
公司页 + 分析页：2 个文件，43/43 通过
公司/分析/API 关联集：6 个文件，61/61 通过
页面级相关集：6 个文件，115/115 通过
全量前端：43 个文件，448/448 通过
vue-tsc --noEmit：退出 0
eslint .：退出 0
vite build：退出 0（176 个模块）
```

### 剩余边界

- SYSTEM 证据仍只通过 ACTIVE 产品的显式 `concept_links` 与已计入概念建立关联；产品源不完整时刻意保持未知，不猜测缺口。
- 产品读取继续采用 100 页防御上限；超过上限时证据和产品相关分类保持未知。

## Fix round 4

### 根因与 RED

证据缺口任务已经只在 `categoryReadiness.evidence === "ready"` 且证据为空时生成，但证据卡片 CTA 仍只按 `concepts.length || evidenceCount` 分支。产品源挂起、失败或截断，以及知识/证据源失败且当前结果为空时，卡片会同时显示“缺口暂无法判断”和“去知识库补充”；同时，有公司知识但没有证据的完整结果会错误显示“管理公司知识”。

- 新增或强化 pending、unknown（请求失败与分页截断）、ready-empty、ready-nonempty、unavailable 和无 `knowledge.create` 权限的证据 CTA 用例。
- RED 命令：

```text
C:\tmp\task-10b-node\node-v22.21.1-win-x64\node.exe node_modules/vitest/vitest.mjs --run src/modules/company/CompanyProfilePage.test.ts
```

- RED 结果：1 个文件共 34 项，6 项按预期失败、28 项通过。失败场景证明 pending、失败与截断仍错误显示“去知识库补充”，ready-empty 受知识概念数量干扰，ready-nonempty 仍显示管理文案；unavailable 与只读权限用例作为既有正确边界保持通过。

### GREEN 实现

- 证据卡片 CTA 现在只在证据分类为 `ready`、已知证据数为 0 且用户拥有 `knowledge.create` 时显示“去知识库补充”。
- 其他可读状态统一显示中性的“查看知识库”：包括 pending、unknown、已有已知证据，以及没有创建权限的只读用户。
- 没有 `knowledge.read` 权限时继续隐藏 CTA 并显示只读权限说明；证据缺口任务原有 readiness 门槛保持不变，未修改其他分类。

### Fix round 4 验证

```text
公司页：1 个文件，34/34 通过
Task 6（公司页 + 分析页）：2 个文件，49/49 通过
公司/分析/API 关联集：6 个文件，67/67 通过
全量前端：43 个文件，454/454 通过
vue-tsc --noEmit：退出 0
eslint .：退出 0
vite build：退出 0（176 个模块）
git diff --check：退出 0
```

验证命令：

```text
C:\tmp\task-10b-node\node-v22.21.1-win-x64\node.exe node_modules/vitest/vitest.mjs --run src/modules/company/CompanyProfilePage.test.ts
C:\tmp\task-10b-node\node-v22.21.1-win-x64\node.exe node_modules/vitest/vitest.mjs --run src/modules/analytics/AnalyticsPage.test.ts src/modules/company/CompanyProfilePage.test.ts
C:\tmp\task-10b-node\node-v22.21.1-win-x64\node.exe node_modules/vitest/vitest.mjs --run src/modules/analytics/AnalyticsPage.test.ts src/modules/company/CompanyProfilePage.test.ts src/modules/products/api.test.ts src/modules/assets/api.test.ts src/modules/knowledge/api.test.ts src/modules/content/api.test.ts
C:\tmp\task-10b-node\node-v22.21.1-win-x64\node.exe node_modules/vitest/vitest.mjs --run
C:\tmp\task-10b-node\node-v22.21.1-win-x64\node.exe node_modules/vue-tsc/bin/vue-tsc.js --noEmit
C:\tmp\task-10b-node\node-v22.21.1-win-x64\node.exe node_modules/eslint/bin/eslint.js .
C:\tmp\task-10b-node\node-v22.21.1-win-x64\node.exe node_modules/vite/bin/vite.js build
git diff --check
```

### 文件与提交

- `frontend/src/modules/company/CompanyProfilePage.vue`
- `frontend/src/modules/company/CompanyProfilePage.test.ts`
- `.superpowers/sdd/2026-08-11-ai-native-ui-redesign/task-6-report.md`
- 提交：`fix: align evidence CTA with readiness`

### 剩余边界

- pending/unknown 状态仍允许用户进入知识库查看已经可见的部分资料，但不会使用补充或管理文案，也不会生成证据缺口任务。
