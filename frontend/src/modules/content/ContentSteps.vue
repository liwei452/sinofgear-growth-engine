<template>
  <nav class="content-steps" aria-label="内容生成步骤">
    <ol>
      <li>
        <span class="step-index">1</span>
        <div><strong>让 AI 推荐方向</strong><small>自动组合产品、市场、客户画像、语言与渠道</small></div>
      </li>
      <li>
        <span class="step-index">2</span>
        <div><strong>确认内容需求</strong><small>核对 AI 生成的推广方向后再继续</small></div>
      </li>
      <li>
        <span class="step-index">3</span>
        <div><strong>AI 生成多渠道内容</strong><small>生成目标语言母版与四个平台版本</small></div>
      </li>
      <li>
        <span class="step-index">4</span>
        <div><strong>人工审核结果</strong><small>只提交你批准的内容，不会自动发布</small></div>
      </li>
    </ol>
  </nav>
</template>

<style scoped>
.content-steps {
  border: 1px solid var(--sg-line);
  border-radius: var(--sg-radius-md);
  background: var(--sg-surface);
  padding: 14px 16px;
}
.content-steps ol {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.content-steps li {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}
.step-index {
  display: grid;
  width: 24px;
  height: 24px;
  flex: none;
  place-items: center;
  border-radius: 50%;
  background: var(--sg-brand-soft);
  color: var(--sg-brand);
  font-size: 0.78rem;
  font-weight: 800;
}
.content-steps strong {
  display: block;
  font-size: 0.86rem;
}
.content-steps small {
  display: block;
  margin-top: 3px;
  color: var(--sg-muted);
  font-size: 0.72rem;
  line-height: 1.45;
}
@media (max-width: 760px) {
  .content-steps ol {
    grid-template-columns: 1fr 1fr;
  }
}
</style>
