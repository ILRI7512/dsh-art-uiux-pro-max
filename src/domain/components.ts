/**
 * 组件学习：只写能从仓库真实结构确认的字段，确认不了标 unknown。
 * 比较表只比可观测项，不给“哪个更好”的结论。
 */
import { sha256Hex } from '../core/ids.ts'

export interface ComponentSource {
  key: string
  owner: string
  repo: string
  platform: 'android' | 'web'
  kind: string
  topic?: string
}

export const COMPONENT_SOURCES: ComponentSource[] = [
  { key: 'compose-samples', owner: 'android', repo: 'compose-samples', platform: 'android', kind: 'official_samples' },
  { key: 'nowinandroid', owner: 'android', repo: 'nowinandroid', platform: 'android', kind: 'official_app' },
  { key: 'androidx', owner: 'androidx', repo: 'androidx', platform: 'android', kind: 'official_library' },
  { key: 'koalaplot', owner: 'KoalaPlot', repo: 'koalaplot-core', platform: 'android', kind: 'third_party' },
  { key: 'vico', owner: 'patrykandpatrick', repo: 'vico', platform: 'android', kind: 'third_party' },
  { key: 'landscapist', owner: 'skydoves', repo: 'landscapist', platform: 'android', kind: 'third_party' },
  { key: 'compose-rich-editor', owner: 'halilozercan', repo: 'compose-rich-editor', platform: 'android', kind: 'third_party' },
  { key: 'reorderable', owner: 'Calvin-LL', repo: 'Reorderable', platform: 'android', kind: 'third_party' },
  { key: 'shadcn-ui', owner: 'shadcn-ui', repo: 'ui', platform: 'web', kind: 'third_party' },
  { key: 'ant-design', owner: 'ant-design', repo: 'ant-design', platform: 'web', kind: 'third_party' },
  { key: 'headlessui', owner: 'tailwindlabs', repo: 'headlessui', platform: 'web', kind: 'third_party' },
  { key: 'storybook', owner: 'storybookjs', repo: 'storybook', platform: 'web', kind: 'third_party' },
  { key: 'tremor', owner: 'tremorlabs', repo: 'tremor', platform: 'web', kind: 'third_party' },
  { key: 'simple-icons', owner: 'simple-icons', repo: 'simple-icons', platform: 'web', kind: 'icon_library', topic: 'visual_assets' },
  { key: 'heroicons-repo', owner: 'tailwindlabs', repo: 'heroicons', platform: 'web', kind: 'icon_library', topic: 'visual_assets' },
  { key: 'material-design-icons', owner: 'google', repo: 'material-design-icons', platform: 'web', kind: 'icon_library', topic: 'visual_assets' },
]

export const COMPONENT_CATEGORIES: Record<string, { label: string; members: string[] }> = {
  basic: { label: '基础组件', members: ['button', 'text', 'label', 'icon', 'divider', 'avatar', 'badge', 'chip'] },
  layout: { label: '布局组件', members: ['row', 'column', 'grid', 'list', 'container', 'scroll', 'stack', 'spacer'] },
  navigation: { label: '导航组件', members: ['bottom-nav', 'top-app-bar', 'sidebar', 'tabs', 'breadcrumb', 'nav-rail'] },
  input: { label: '输入组件', members: ['text-field', 'search', 'select', 'switch', 'slider', 'date-picker', 'checkbox', 'radio'] },
  feedback: { label: '反馈组件', members: ['progress', 'spinner', 'banner', 'toast', 'snackbar', 'skeleton'] },
  overlay: { label: '浮层组件', members: ['dialog', 'bottom-sheet', 'popover', 'tooltip', 'dropdown', 'menu'] },
  data: { label: '数据组件', members: ['table', 'stat-card', 'chart', 'data-list', 'pagination', 'sparkline'] },
  advanced: { label: '高级组件', members: ['rich-text-editor', 'drag-reorder', 'gesture', 'custom-drawing', 'image-loader'] },
}

const CATEGORY_PATTERNS: Record<string, string[]> = {
  advanced: ['editor', 'reorder', 'drag', 'gesture', 'canvas', 'render', 'loader', 'rich'],
  data: ['table', 'chart', 'plot', 'stat', 'pagination', 'graph', 'candle', 'sparkline', 'card'],
  overlay: ['dialog', 'sheet', 'popover', 'tooltip', 'dropdown', 'menu', 'modal'],
  input: ['input', 'field', 'search', 'select', 'switch', 'slider', 'picker', 'checkbox', 'radio'],
  navigation: ['nav', 'tab', 'tabs', 'breadcrumb', 'sidebar', 'appbar', 'rail', 'navigation'],
  feedback: ['progress', 'spinner', 'toast', 'snackbar', 'banner', 'skeleton', 'loading'],
  layout: ['layout', 'grid', 'column', 'row', 'list', 'container', 'spacer', 'stack'],
  basic: ['button', 'text', 'label', 'icon', 'divider', 'avatar', 'badge', 'chip'],
}

function words(name: string): Set<string> {
  const parts = name.match(/[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+/g) ?? []
  const out = new Set(parts.map((part) => part.toLowerCase()))
  out.add(name.toLowerCase().replace(/[^a-z0-9]/g, ''))
  return out
}

export function categorize(name: string): string {
  const tokens = words(name)
  for (const [category, keys] of Object.entries(CATEGORY_PATTERNS)) {
    if (keys.some((key) => tokens.has(key))) return category
  }
  return 'unknown'
}

export interface RepositoryInfo {
  repository: string
  platform: string
  framework: string
  license: string
  stars: number | null
  archived: boolean
  last_push: string
  source_version: string
  component_paths: string[]
  component_count_candidates: number
  components_by_category: Record<string, string[]>
  test_files: number
  example_paths: string[]
  knowledge_level: 'L1' | 'L2'
  purpose: string
  limitations: string
  source_key?: string
  fetched_at?: string
}

const UNKNOWN = 'unknown'
const TEST_HINTS = ['test', 'spec', '__tests__', 'androidtest', 'testfixtures']
const EXAMPLE_HINTS = ['example', 'examples', 'demo', 'samples', 'storybook']

export function analyzeRepository(meta: Record<string, unknown>, readme: string, paths: readonly string[], input: { platform: string; sourceKey: string }): RepositoryInfo {
  const name = String(meta.full_name ?? input.sourceKey)
  const license = ((meta.license as Record<string, unknown> | null)?.spdx_id as string | undefined) ?? UNKNOWN
  const archived = Boolean(meta.archived)
  const stars = typeof meta.stargazers_count === 'number' ? meta.stargazers_count : null
  const pushed = String(meta.pushed_at ?? '')
  const language = String(meta.language ?? UNKNOWN)
  const componentPaths = paths.filter((path) => /\/(components?|ui|widgets?|controls?)\//i.test(path)).slice(0, 400)
  const testPaths = paths.filter((path) => TEST_HINTS.some((hint) => path.toLowerCase().includes(hint)))
  const examplePaths = paths.filter((path) => EXAMPLE_HINTS.some((hint) => path.toLowerCase().includes(hint)))
  const names: string[] = []
  for (const path of componentPaths) {
    const stem = (path.split('/').pop() ?? '').replace(/\.[^.]+$/, '')
    if (/^[A-Z][A-Za-z0-9]{2,}$/.test(stem) || /^[a-z][a-z0-9-]{3,}$/.test(stem)) {
      if (!['index', 'types', 'utils', 'styles', 'readme'].includes(stem.toLowerCase())) names.push(stem)
    }
  }
  const unique = [...new Set(names)].sort().slice(0, 60)
  const byCategory: Record<string, string[]> = {}
  for (const name of unique) (byCategory[categorize(name)] ??= []).push(name)
  const level: 'L1' | 'L2' = componentPaths.length > 0 && (testPaths.length > 0 || examplePaths.length > 0) ? 'L2' : 'L1'
  const purpose = (readme || '').replace(/\s+/g, ' ').slice(0, 400) || UNKNOWN
  return {
    repository: name,
    platform: input.platform,
    framework: language,
    license,
    stars,
    archived,
    last_push: pushed,
    source_version: pushed.slice(0, 4) || UNKNOWN,
    component_paths: componentPaths.slice(0, 40),
    component_count_candidates: unique.length,
    components_by_category: Object.fromEntries(Object.entries(byCategory).map(([category, list]) => [category, list.slice(0, 12)])),
    test_files: testPaths.length,
    example_paths: examplePaths.slice(0, 10),
    knowledge_level: level,
    purpose,
    limitations: archived ? '仓库已归档，可能不再维护' : pushed.slice(0, 4) ? `最近推送 ${pushed.slice(0, 4)}，维护活跃度未知` : '维护状态未知',
  }
}

export function comparisons(repos: readonly RepositoryInfo[]): Array<Record<string, unknown>> {
  return repos.map((repo) => ({
    repository: repo.repository,
    license: repo.license,
    framework: repo.framework,
    components: repo.component_count_candidates,
    categories: Object.keys(repo.components_by_category).sort(),
    tests: repo.test_files,
    archived: repo.archived,
    last_push: repo.last_push,
  }))
}

export interface ComponentKnowledge {
  component_id: string
  component_name: string
  component_category: string
  platform: string
  framework: string
  source_repository: string
  source_file: string
  source_version: string
  license: string
  component_purpose: string
  visual_structure: string
  layout_rules: string
  parameters: string[]
  component_states: string[]
  interaction_behavior: string
  theme_customization: string
  responsive_behavior: string
  accessibility: string
  performance_notes: string
  implementation_example: string
  testing_strategy: string
  use_cases: string[]
  limitations: string
  anti_patterns: string[]
  related_components: string[]
  knowledge_level: string
  content_hash: string
  source_url?: string
}

/** 只读源码文本的确定性抽取；未运行、未渲染，等级最多 L2。 */
export function parseComponentSource(name: string, code: string, input: { repo: string; path: string; license: string; testFiles: number }): ComponentKnowledge {
  const props = [...new Set([...code.matchAll(/^\s{2}([a-zA-Z_][A-Za-z0-9_]*)\??:/gm)].map((m) => m[1] as string))].sort()
  const variantBlocks = [...code.matchAll(/(?:variant|size|color|tone)\s*:\s*\{([^}]{0,240})/g)].map((m) => m[1] ?? '')
  const variantKeys = [...new Set(variantBlocks.flatMap((block) => [...block.matchAll(/([a-zA-Z][\w-]*)\s*:/g)].map((m) => m[1] as string)))].sort()
  const aria = [...new Set((code.match(/aria-[a-z]+/g) ?? []))].sort()
  const roles = [...new Set([...code.matchAll(/role="([a-z]+)"/g)].map((m) => m[1] as string))].sort()
  const handlers = [...new Set([...code.matchAll(/on([A-Z][A-Za-z]+)\s*[:=]/g)].map((m) => m[1] as string))].sort()
  const states = [...new Set([...code.matchAll(/data-([a-z-]+)=/g)].map((m) => m[1] as string))].sort()
  const classEntries = (code.match(/className/g) ?? []).length
  const styleHooks = [...new Set((code.match(/cva|clsx|cn|twMerge|styled\./g) ?? []))].sort()
  const codeHash = sha256Hex(code)
  return {
    component_id: `cmp_${codeHash.slice(0, 12)}`,
    component_name: name,
    component_category: categorize(name),
    platform: 'web',
    framework: 'React + TypeScript',
    source_repository: input.repo,
    source_file: input.path,
    source_version: 'HEAD',
    license: input.license,
    component_purpose: aria.length > 0 ? `带 aria 标注的可交互组件：${aria.join(', ')}` : '可复用基础组件；具体语义见组件名与 aria 角色',
    visual_structure: styleHooks.length > 0 ? `样式通过 className 注入（${classEntries} 处），组件不内联布局` : 'unknown（未检出样式工具）',
    layout_rules: 'unknown（未见显式布局约束）',
    parameters: props.slice(0, 40),
    component_states: states.length > 0 ? states : ['disabled', 'loading'].filter((state) => code.toLowerCase().includes(state)),
    interaction_behavior: `事件处理: ${handlers.join(', ') || '未声明'}`,
    theme_customization: `变体键: ${variantKeys.slice(0, 20).join(', ') || '未声明'}；样式工具: ${styleHooks.join(', ') || '未检出'}`,
    responsive_behavior: code.includes('media') ? '含媒体查询' : 'unknown（组件内部无断点逻辑）',
    accessibility: `aria: ${aria.join(', ') || '无'}；role: ${roles.join(', ') || '无'}`,
    performance_notes: 'unknown（未做基准测试）',
    implementation_example: `见源码 ${input.path}`,
    testing_strategy: input.testFiles > 0 ? `仓库存在 ${input.testFiles} 个测试文件；本组件是否有专属测试未逐一确认` : '未发现测试文件',
    use_cases: code.includes('onClick') ? ['表单/操作触发'] : [],
    limitations: '只读源码文本，未运行、未渲染，交互与视觉表现未验证',
    anti_patterns: [],
    related_components: [],
    knowledge_level: 'L2',
    content_hash: codeHash,
  }
}
