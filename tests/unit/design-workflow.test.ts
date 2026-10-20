import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  AUDIT_ITEMS, auditHtml, buildDesignSystem, checkPalette, contrastRatio, feedbackUnit,
  proposeDirections, routeTask, tokensToCss,
} from '../../src/domain/design-workflow.ts'

test('WCAG 对比度与参考值一致', () => {
  assert.ok(Math.abs(contrastRatio('#000000', '#ffffff') - 21) < 0.01)
  assert.ok(Math.abs(contrastRatio('#ffffff', '#ffffff') - 1) < 0.001)
  assert.ok(contrastRatio('#999999', '#ffffff') < 4.5)
})

test('配色报告对失败组合明确标 false', () => {
  const [bad, good] = checkPalette([['bad', '#999999', '#ffffff'], ['good', '#111111', '#ffffff']])
  assert.equal(bad?.AA_normal, false)
  assert.equal(bad?.measured, true)
  assert.equal(good?.AA_normal, true)
  assert.ok((good?.ratio ?? 0) > 15)
})

test('任务路由优先专门类型', () => {
  assert.equal(routeTask('给我做一个金融行情终端界面').task_type, 'fintech_terminal')
  assert.equal(routeTask('用 Compose 写一个 Android 首页').task_type, 'android_native')
  assert.ok(['web_page', 'ui_refactor'].includes(routeTask('随便聊聊').task_type))
})

test('方向有实质区别，且不默认陈词滥调', () => {
  const directions = proposeDirections('fintech_terminal', 3)
  assert.equal(directions.length, 3)
  assert.equal(new Set(directions.map((direction) => direction.key)).size, 3)
  assert.equal(new Set(directions.map((direction) => direction.style)).size, 3)
  assert.equal(new Set(directions.map((direction) => direction.layout)).size, 3)
  assert.ok(!directions.map((direction) => direction.idea).join(' ').includes('玻璃拟态'))
})

test('设计系统给实测对比度，且整体未验证', () => {
  const system = buildDesignSystem('industrial_dense')
  assert.equal(system.verified, false)
  assert.ok(system.contrast.length > 0)
  assert.ok(system.contrast.every((item) => item.measured))
  assert.ok(tokensToCss(system).includes('--color-bg'))
  assert.ok(system.ui_component_failures !== undefined)
})

test('审计把不能测的标 unmeasured，不静默通过', () => {
  const html = '<div style="font-size:16px;color:#999999"></div><img src="a.png">'
  const result = auditHtml(html)
  assert.equal(result.items.length, AUDIT_ITEMS.length)
  const statuses = Object.fromEntries(result.items.map((item) => [item.item, item.status]))
  assert.equal(statuses.background_readability, 'unmeasured')
  assert.equal(statuses.accessibility, 'fail')
})

test('带 token 时浅灰正文被判失败', () => {
  const html = '<style>:root{font-size:14px}.x{box-shadow:0 1px 2px}#fff</style><img alt="ok">'
  const system = buildDesignSystem('editorial_light', { fg: '#dddddd' })
  const result = auditHtml(html, system.tokens as unknown as Record<string, unknown>)
  const statuses = Object.fromEntries(result.items.map((item) => [item.item, item.status]))
  assert.equal(statuses.background_readability, 'fail')
})

test('反馈单元区分项目级与通用级', () => {
  const unit = feedbackUnit({ decision: '紧凑行高适用于交易台', evidence: '在 1080p 下实测 8 行可读', scope: 'project', category: 'financial_dashboard' })
  assert.equal(unit.partition, 'project_knowledge')
  assert.equal(unit.level, 'L2')
  assert.throws(() => feedbackUnit({ decision: 'x', evidence: 'y', scope: 'global' as never, category: 'web_ui' }))
})
