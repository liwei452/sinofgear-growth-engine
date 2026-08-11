# Task 4 报告：推广新手引导流程

## 状态

已完成。普通推广入口改为“选择产品 → 告诉 AI 目标 → 查看可用素材 → 确认方案 → 生成内容 → 批准发布”的六步引导；仅当前步骤展开。专业模式和高级记录入口保留。

## 文件

- 新增 `frontend/src/modules/content/components/GuidedStepCard.vue`
- 新增 `frontend/src/modules/content/components/GuidedStepCard.test.ts`
- 修改 `frontend/src/modules/content/PromotionPage.test.ts`
- 修改 `frontend/src/modules/content/ContentFactoryPage.vue`
- 修改 `frontend/src/modules/content/ContentFactoryPage.test.ts`
- 修改 `frontend/src/modules/content/ContentBriefWizard.vue`
- 修改 `frontend/src/modules/content/ContentBriefWizard.test.ts`
- 修改 `frontend/src/modules/content/ContentReviewDialog.vue`
- 修改 `frontend/src/modules/content/ReviewCenterPage.vue`
- 修改 `frontend/src/modules/content/ReviewCenterPage.test.ts`

`PromotionPage.vue` 已正确绑定 `experience="ordinary"`，无需为本任务制造无行为变化的改动。

## RED / GREEN

- RED：新增引导卡、六步顺序、仅当前步骤展开、普通审核状态和后果式按钮断言后，聚焦套件按预期失败；失败原因分别为组件缺失、旧三步结构、原始状态和旧操作文案。
- RED（契约变异检查）：暂时移除普通流程自动创建推广计划的分支后，真实契约测试只收到 `/api/v1/content-briefs` 写入，按预期失败。
- GREEN：恢复最小实现后，聚焦套件 `5 files / 62 tests passed`。

## 命令结果

- `node node_modules/vitest/vitest.mjs --run ...`：通过，5 个测试文件、62 个测试。
- `vue-tsc --noEmit`：通过。
- `eslint .`：通过，无警告或错误。
- `vite build`：通过，168 个模块完成构建。
- `git diff --check`：通过。

所有命令均使用指定的英文路径 Node 运行时执行。

## 自审

- 普通界面不显示 `Campaign`、`ContentBrief`、`MasterContent`、`PlatformContent` 或原始状态；审核状态复用 `ordinaryStatus`，渠道展示复用 `ordinaryPlatform`。
- 普通向导使用预设市场、客户、目标、行动和语言，补充项保持简短；没有自由聊天输入，也明确说明不会假装已调用模型。
- 创建推广计划、保存方案、确认、生成、修订、批准、驳回和冲突刷新仍调用原有真实 API；权限、当前版本检查、拒绝原因和高级记录均保留。
- 新引导卡复用 `AppIcon` 与 `StatusBadge`，提供 `aria-current`、命名区域、焦点管理、移动端布局和 reduced-motion 处理。
- 改动范围限定在 Task 4 清单文件与本报告。

## 提交

`feat: guide beginners through promotion work`（本任务提交；精确哈希见任务返回）。

## 担忧

- 无已知遗留问题。生成任务仍依赖现有轮询 API，而不是后台推送；普通流程现在会在高级记录收起时持续轮询本次提交的任务。

## 修复轮次 1（评审反馈）

### 修复内容

- 当前推广不再被组织内任意历史结果推进到“批准发布”。最新需求按 `updated_at`、`created_at`、`version` 稳定排序；生成结果只在真实类型字段 `brief_id` 和 `brief_version` 同时匹配当前需求时生效。
- 普通模式提交生成后记录本次 `job_id` 与需求 id/version 的运行时关联。即使高级记录保持收起，也会读取该任务的等待、运行、失败或成功状态；活动任务期间禁用重复提交；成功后刷新生成结果并进入审批步骤；卸载、组织切换和权限撤销会停止轮询并清理状态。
- 普通向导使用独立的字段到步骤映射。落地页属于第 2 步并在离开该步前校验，服务端字段错误会返回真实步骤并聚焦对应控件；素材和知识关联错误归到第 3 步。
- 普通编辑会加载完整产品、素材和知识集合，显示历史已停用、未批准或缺失关联，并允许显式移除；普通新建仍只提供可用/已批准选项。
- 三个普通向导前进按钮改为“保存产品并继续”“保存目标并查看素材”“查看并确认方案”，同步更新推广页与路由测试。

### RED / GREEN

- RED：新增 7 个回归场景后，聚焦套件为 `7 failed / 37 passed`；失败分别对应旧结果污染新草稿、折叠状态不轮询、完整 DRAFT→READY→生成→审批链路、普通字段错误步骤/焦点、落地页校验时机、历史关联恢复和后果式按钮文案。
- GREEN：实现最小修复后，聚焦套件为 `2 files / 44 tests passed`。
- 全量回归：`41 files / 391 tests passed`。

### 修复后验证

- `vitest --run src/modules/content/ContentBriefWizard.test.ts src/modules/content/ContentFactoryPage.test.ts`：44 个测试通过。
- `vitest --run`：41 个测试文件、391 个测试通过。
- `vue-tsc --noEmit`：通过。
- `eslint .`：通过，无警告或错误。
- `vite build`：通过，168 个模块完成构建。
- `git diff --check`：通过。

## 修复轮次 2（跨页面生成恢复）

### 必要性与契约边界

普通页此前只能在同一组件实例中记住刚提交的任务；刷新、路由重进或 remount 后，内存关联会丢失。现有 Job 模型虽持久化了生成输入中的 `brief_id` 与 `brief_version`，公开 API 却没有返回这两个字段，而排队、运行、失败和取消任务的 `result_reference` 均可能为 `null`，因此前端无法可靠区分当前需求任务与同组织内的无关任务。

本轮增加 nullable `source_reference`，但严格限定为：

- 仅 `CONTENT_GENERATE` 任务可派生；其他任务固定返回 `null`。
- 仅从服务端持久化输入中白名单读取 `brief_id` 和 `brief_version`。
- `brief_id` 必须是有效 UUID，`brief_version` 必须是非布尔的正整数；缺失或畸形安全返回 `null`。
- 不返回完整 `input_snapshot`、prompt、用户文本或任何其他键；不改变 `jobs.read` 权限、组织隔离、过滤器或列表范围。

### 前端恢复

- 普通页在高级记录收起时使用独立恢复查询，仅请求 `CONTENT_GENERATE`，每页最多 50 条；若当前页没有严格匹配，会沿服务端 cursor 继续读取，找到最新匹配任务后停止。
- 任务只有在 `source_reference.brief_id === latestBrief.id` 且版本也相等时才可恢复；无引用、畸形引用、其他需求和其他版本均忽略。
- remount 后可恢复排队/运行任务并继续真实轮询，生成按钮保持禁用；恢复最近失败任务时展示“再次尝试”并走原有 retry API；恢复成功任务时刷新 MasterContent，最终步骤仍只由严格匹配 id/version 的 MasterContent 决定。
- 新提交任务仍即时显示，但其运行时对象也携带同样的白名单引用；组织切换、权限撤销和组件卸载继续清理轮询。

### RED / GREEN

- 后端 RED：新增列表、详情、隐私白名单、畸形输入、非内容任务和 OpenAPI 断言后，`12 failed / 5 passed`，失败原因均为 `source_reference` 缺失。
- 后端 GREEN：最小 serializer 派生实现后，聚焦 Job API 为 `17 passed`；完整 jobs 测试为 `37 passed`。
- 前端 RED：新增 remount 恢复和无关任务隔离后，`2 failed / 33 passed`；失败原因是普通页未读取服务端任务。分页分支另独立验证为 `1 failed / 35 passed`。
- 前端 GREEN：实现严格匹配与恢复后，ContentFactoryPage 为 `36 passed`；相关 3 文件为 `59 passed`；全量前端为 `41 files / 394 tests passed`。

### 修改文件

- `backend/apps/jobs/serializers.py`
- `backend/apps/jobs/tests/test_job_api.py`
- `frontend/src/api/generated/schema.ts`（由既有脚本生成）
- `frontend/src/modules/content/api.ts`
- `frontend/src/modules/content/ContentFactoryPage.vue`
- `frontend/src/modules/content/ContentFactoryPage.test.ts`
- `.superpowers/sdd/2026-08-11-ai-native-ui-redesign/task-4-report.md`

### 验证命令与结果

- `python -m pytest apps/jobs/tests/test_job_api.py -q`：17 passed。
- `python -m pytest apps/jobs/tests -q`：37 passed。
- `vitest --run ContentFactoryPage.test.ts ContentBriefWizard.test.ts PromotionPage.test.ts`：3 files / 59 tests passed。
- `vitest --run`：41 files / 394 tests passed。
- `node scripts/generate-api.mjs check`：生成 API artifact 与后端 OpenAPI 一致。
- `ruff check apps/jobs/serializers.py apps/jobs/tests/test_job_api.py`：通过。
- `vue-tsc --noEmit`：通过。
- `eslint .`：通过。
- `vite build`：通过。
- `git diff --check`：通过。
