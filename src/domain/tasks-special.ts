/** 专项能力：三种背景方案 + 多尺寸布局矩阵；不能测的明确 unmeasured。 */
import { checkPalette, contrastRatio } from './design-workflow.ts'

export interface BackgroundSpec {
  key: string
  name: string
  idea: string
  css: string[]
  perf: string
  cost: 'low' | 'medium' | 'high'
  dark_safe: boolean
}

export const BACKGROUNDS: Record<string, Omit<BackgroundSpec, 'key'>> = {
  mesh_gradient: {
    name: 'Mesh Gradient（多层径向渐变）',
    idea: '用 2–3 个低透明度径向渐变叠加出空间纵深，纯 CSS、无额外资源',
    css: [
      'background-color: #0b0d12;',
      'background-image:',
      '  radial-gradient(60% 50% at 15% 20%, rgba(76,154,255,.22), transparent 70%),',
      '  radial-gradient(50% 45% at 85% 10%, rgba(255,120,80,.16), transparent 70%),',
      '  radial-gradient(80% 60% at 50% 110%, rgba(120,255,200,.10), transparent 70%);',
    ],
    perf: '一次性绘制的渐变层，通常只有 1 次 paint；滚动时不重绘。风险最低。',
    cost: 'low',
    dark_safe: true,
  },
  noise_overlay: {
    name: 'Noise Overlay（噪点叠加）',
    idea: '在纯色或渐变上叠一层极低透明度噪点，消除塑料感并掩盖渐变断层（banding）',
    css: [
      'background-color: #101318;',
      'background-image: url("data:image/svg+xml;utf8,<svg xmlns=\'http://www.w3.org/2000/svg\' width=\'120\' height=\'120\'>',
      "  <filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.8' numOctaves='2'/></filter>",
      "  <rect width='120' height='120' filter='url(%23n)' opacity='0.06'/></svg>\");",
      'background-size: 120px 120px;',
    ],
    perf: 'SVG 滤镜在首次栅格化时较贵；平铺后为位图缓存，滚动开销低。避免对大尺寸元素动态重算。',
    cost: 'medium',
    dark_safe: true,
  },
  conic_sweep: {
    name: 'Conic Sweep（锥形旋光）',
    idea: '锥形渐变制造方向性光带，适合强调区块；必须给 reduced-motion 兜底',
    css: [
      'background: conic-gradient(from 210deg at 50% 50%,',
      '  rgba(76,154,255,.28), rgba(180,120,255,.16), rgba(76,154,255,.28));',
      'animation: sweep 18s linear infinite;',
      '@media (prefers-reduced-motion: reduce) { .sweep { animation: none } }',
    ],
    perf: '旋转动画会持续合成（compositor）层；大区域 + 低端设备可能掉帧，建议限制在卡片级尺寸。',
    cost: 'high',
    dark_safe: true,
  },
}

export interface BackgroundResult extends BackgroundSpec {
  css_block: string
  contrast: Record<string, unknown>
  verdict: 'pass' | 'unmeasured'
  note: string
}

export function generateBackgrounds(input: { textColor?: string; count?: number } = {}): BackgroundResult[] {
  const textColor = input.textColor ?? '#e6e9ee'
  const count = Math.min(Math.max(input.count ?? 3, 1), Object.keys(BACKGROUNDS).length)
  const worst: Record<string, string> = { mesh_gradient: '#141821', noise_overlay: '#101318', conic_sweep: '#1a1f2b' }
  return Object.entries(BACKGROUNDS).slice(0, count).map(([key, spec]) => {
    const bg = worst[key] as string
    const ratio = contrastRatio(textColor, bg)
    return {
      key,
      ...spec,
      css_block: spec.css.join('\n'),
      contrast: {
        pair: '正文/最坏背景', fg: textColor, bg, ratio: Math.round(ratio * 100) / 100,
        AA_normal: ratio >= 4.5, measured: true, basis: '取渐变叠层中偏亮的一档作为最坏情况，公式实算',
      },
      verdict: ratio < 4.5 ? 'unmeasured' : 'pass',
      note: '对比度为实算；绘制耗时与设备掉帧未测。',
    }
  })
}

export const BREAKPOINTS = [320, 375, 414, 768, 1024, 1440]

export function responsiveMatrix(html: string, breakpoints: readonly number[] = BREAKPOINTS): Record<string, unknown> {
  const fixedWidths = [...html.matchAll(/(?<!max-)(?<!min-)width\s*:\s*(\d{3,4})px/g)].map((m) => Number(m[1]))
  const maxWidths = [...html.matchAll(/max-width\s*:\s*(\d{3,4})px/g)].map((m) => Number(m[1]))
  const media = html.match(/@media[^{]{0,120}\{/g) ?? []
  const tapTargets = [...html.matchAll(/(?:height|min-height)\s*:\s*(\d{1,3})px/g)].map((m) => Number(m[1]))
  const smallTargets = tapTargets.filter((target) => target < 44)
  const fonts = [...new Set([...html.matchAll(/font-size\s*:\s*([\d.]+)px/g)].map((m) => Number(m[1])))].sort((a, b) => a - b)
  const tinyFonts = fonts.filter((font) => font < 12)

  const rows = breakpoints.map((width) => {
    const overflow = fixedWidths.filter((value) => value > width)
    let status: 'pass' | 'warn' | 'fail'
    let detail: string
    if (overflow.length > 0) {
      status = 'fail'
      detail = `固定宽 ${overflow.slice(0, 3).map((value) => `${value}px`).join(', ')} 超过视口 ${width}`
    } else if (fixedWidths.length > 0 && maxWidths.length === 0 && media.length === 0) {
      status = 'warn'
      detail = '有固定宽但无 max-width 与媒体查询，窄屏可能横向滚动'
    } else {
      status = 'pass'
      detail = '未发现固定宽溢出风险'
    }
    return { width, status, detail, overflow_candidates: overflow.slice(0, 5) }
  })

  return {
    breakpoints: [...breakpoints],
    rows,
    signals: {
      fixed_widths: [...new Set(fixedWidths)].sort((a, b) => a - b),
      max_widths: [...new Set(maxWidths)].sort((a, b) => a - b),
      media_queries: media.length,
      tap_targets: [...new Set(tapTargets)].sort((a, b) => a - b),
      tap_targets_below_44: smallTargets,
      fonts_below_12px: tinyFonts,
    },
    counts: Object.fromEntries(['pass', 'warn', 'fail'].map((status) => [status, rows.filter((row) => row.status === status).length])),
    measured: false,
    note: '静态推断，未做真实设备渲染；实际重排与溢出需浏览器验证。',
  }
}
