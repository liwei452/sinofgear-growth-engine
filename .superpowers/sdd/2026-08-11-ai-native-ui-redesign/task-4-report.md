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

- 生成任务异步完成后，普通流程需要重新进入页面或打开高级记录触发已有的任务刷新机制，之后才会进入“批准发布”；没有新增后台推送或伪造即时完成状态。
