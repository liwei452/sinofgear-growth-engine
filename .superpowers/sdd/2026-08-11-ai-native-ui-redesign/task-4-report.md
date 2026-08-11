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
