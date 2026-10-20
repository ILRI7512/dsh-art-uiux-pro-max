#!/usr/bin/env node
/** Art UI/UX Pro Max CLI：所有命令与原生工具共用 ArtServices。 */
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { parseArgs } from 'node:util';
import { ArtServices } from "./application/services.js";
import { resolveArtRoot } from "./core/paths.js";
import { asError } from "./core/errors.js";
import { buildDesignSystem, tokensToCss, TASK_TYPES } from "./domain/design-workflow.js";
import { mean } from "./domain/metrics.js";
import { main as mcpMain } from "./mcp/server.js";
function value(values, key) {
    const raw = values[key];
    return typeof raw === 'string' ? raw : undefined;
}
function bool(values, key) {
    return values[key] === true;
}
function numberValue(values, key) {
    const raw = values[key];
    if (raw === undefined)
        return undefined;
    const number = Number(raw);
    return Number.isFinite(number) ? number : undefined;
}
function split(valueText) {
    return valueText ? valueText.split(',').map((item) => item.trim()).filter(Boolean) : [];
}
function write(file, content) {
    mkdirSync(join(file, '..'), { recursive: true });
    writeFileSync(file, content, 'utf8');
}
function fmt(value) {
    return value === undefined || Number.isNaN(value) ? 'n/a' : value.toFixed(3);
}
function printJson(value) {
    process.stdout.write(`${JSON.stringify(value, null, 2)}\n`);
}
async function main() {
    const [command, ...rest] = process.argv.slice(2);
    const root = resolveArtRoot();
    const services = new ArtServices({ root });
    try {
        if (!command || command === 'help' || command === '--help' || command === '-h') {
            process.stdout.write(`Art UI/UX Pro Max (TypeScript)

用法: art-uiux <command> [options]

  taxonomy                     12 个主分类与 16 个字段
  registry [--category C] [--limit N] [--json]
  check [--limit N] [--only a,b] [--json]
  ingest [--limit N] [--only a,b] [--all] [--max-units N]
  case --resource ID [--max-units N]
  search <query> [--category C] [--top N] [--min-level L2] [--json]
  design --task TEXT [--direction KEY] [--no-write]
  components [--keys a,b] [--all] [--limit N]
  component-source --repo KEY --file PATH [--name NAME]
  stats [--json]
  eval [--json]
  mcp                          stdio MCP 兼容层

数据目录: ${services.dataDir}
`);
            return;
        }
        if (command === 'mcp') {
            await mcpMain();
            return;
        }
        if (command === 'taxonomy') {
            printJson(services.taxonomy());
            return;
        }
        if (command === 'registry') {
            const { values } = parseArgs({ args: rest, options: { category: { type: 'string' }, type: { type: 'string' }, status: { type: 'string' }, limit: { type: 'string' }, json: { type: 'boolean' } }, allowPositionals: true });
            const result = services.registryList({ category: value(values, 'category'), type: value(values, 'type'), accessStatus: value(values, 'status'), limit: numberValue(values, 'limit') });
            if (bool(values, 'json')) {
                printJson(result);
                return;
            }
            const resources = result.resources;
            process.stdout.write(`资源 ${result.total} 条（显示 ${resources.length}）\n`);
            for (const item of resources) {
                process.stdout.write(`${String(item.resource_id).padEnd(22)} ${String(item.access_status).padEnd(10)} ${String(item.learn_status).padEnd(12)} chunks=${String(item.learned_chunks).padEnd(4)} ${String(item.name)}\n`);
            }
            return;
        }
        if (command === 'check') {
            const { values } = parseArgs({ args: rest, options: { limit: { type: 'string' }, only: { type: 'string' }, json: { type: 'boolean' }, interval: { type: 'string' } }, allowPositionals: true });
            const only = split(value(values, 'only'));
            if (only.length > 0) {
                const result = await services.registryCheck({ resourceIds: only, minIntervalMs: numberValue(values, 'interval') });
                if (bool(values, 'json')) {
                    printJson(result);
                    return;
                }
                for (const item of result.results) {
                    process.stdout.write(`${String(item.resource_id).padEnd(22)} ${String(item.status).padEnd(10)} http=${String(item.http).padEnd(4)} robots=${String(item.robots)} ${String(item.error ?? '')}\n`);
                }
                return;
            }
            const result = await services.registryCheck({ limit: numberValue(values, 'limit'), minIntervalMs: numberValue(values, 'interval') });
            if (bool(values, 'json')) {
                printJson(result);
                return;
            }
            for (const item of result.results) {
                process.stdout.write(`${String(item.resource_id).padEnd(22)} ${String(item.status).padEnd(10)} http=${String(item.http).padEnd(4)} robots=${String(item.robots)} ${String(item.error ?? '')}\n`);
            }
            process.stdout.write(`\n汇总: ${JSON.stringify(result.stats.access_status)}\n`);
            return;
        }
        if (command === 'ingest') {
            const { values } = parseArgs({ args: rest, options: { limit: { type: 'string' }, only: { type: 'string' }, all: { type: 'boolean' }, 'max-units': { type: 'string' }, interval: { type: 'string' } }, allowPositionals: true });
            const result = await services.ingestBatch({ limit: numberValue(values, 'limit'), only: split(value(values, 'only')), maxUnits: numberValue(values, 'max-units'), minIntervalMs: numberValue(values, 'interval'), all: bool(values, 'all') });
            for (const item of result.results) {
                process.stdout.write(`${item.resource_id.padEnd(22)} ingested=${String(item.ingested).padEnd(3)} sections=${item.sections} skipped=${item.skipped} dupes=${item.duplicates} ${item.warnings[0] ?? ''}\n`);
            }
            process.stdout.write(`\n本次入库片段: ${result.total}\n库内统计: ${JSON.stringify(result.stats)}\n注册表: ${JSON.stringify(services.registry.stats())}\n`);
            return;
        }
        if (command === 'case') {
            const { values } = parseArgs({ args: rest, options: { resource: { type: 'string' }, 'max-units': { type: 'string' } }, allowPositionals: true });
            const resourceId = value(values, 'resource');
            if (!resourceId)
                throw new Error('--resource 必填');
            const result = await services.caseAnalyze({ resourceId, maxUnits: numberValue(values, 'max-units') });
            const dir = join(root, 'docs', 'cases');
            write(join(dir, `${resourceId}.json`), `${JSON.stringify(result, null, 2)}\n`);
            const lines = [`# Design Case: ${result.case}`, '', `- URL: ${result.url}`, `- 抓取时间: ${new Date().toISOString()}`, `- 平台: web`, `- 技术栈指纹: ${result.tech_stack.join(', ') || '未检出'}`, ''];
            for (const [section, items] of Object.entries(result.report.sections ?? {})) {
                lines.push(`## ${section}`);
                for (const item of items)
                    lines.push(`- [${String(item.kind)}, 置信 ${String(item.confidence)}] ${String(item.statement)}`);
                lines.push('');
            }
            if (result.conflicts.length > 0) {
                lines.push('## 与现有知识的潜在冲突（未覆盖，仅登记）');
                for (const conflict of result.conflicts.slice(0, 20))
                    lines.push(`- ${JSON.stringify(conflict)}`);
                lines.push('');
            }
            lines.push('## 能力边界', '- 本分析基于静态 HTML/CSS 文本，未做真实渲染、未采集用户行为数据。', '- 视觉美观、可用性、性能、转化率之间没有因果关系，此处不做任何此类推断。');
            write(join(dir, `${resourceId}.md`), `${lines.join('\n')}\n`);
            process.stdout.write(`${JSON.stringify({ case: result.case, sections: result.sections, ingested: result.ingested, duplicates: result.duplicates, conflicts: result.conflicts.length, report: join(dir, `${resourceId}.md`) }, null, 2)}\n`);
            return;
        }
        if (command === 'search') {
            const { values, positionals } = parseArgs({ args: rest, options: { category: { type: 'string' }, top: { type: 'string' }, 'min-level': { type: 'string' }, rerank: { type: 'string' }, json: { type: 'boolean' } }, allowPositionals: true });
            const query = positionals.join(' ').trim();
            if (!query)
                throw new Error('search 需要查询文本');
            const result = services.search({ query, categories: split(value(values, 'category')), topK: numberValue(values, 'top'), minLevel: value(values, 'min-level'), rerank: value(values, 'rerank') });
            if (bool(values, 'json')) {
                printJson(result);
                return;
            }
            if (result.count === 0) {
                process.stdout.write(`${result.answer_if_empty}\n`);
                return;
            }
            for (const hit of result.hits) {
                process.stdout.write(`${hit.title} [${hit.level} ${hit.topic}] ${hit.final_score.toFixed(4)} ${hit.source.url}\n  ${hit.content.slice(0, 180)}\n`);
                if (hit.warnings.length > 0)
                    process.stdout.write(`  warnings: ${hit.warnings.join('; ')}\n`);
            }
            if (result.warnings.length > 0)
                process.stdout.write(`\n${result.warnings.join('\n')}\n`);
            return;
        }
        if (command === 'design') {
            const { values } = parseArgs({ args: rest, options: { task: { type: 'string' }, direction: { type: 'string' }, top: { type: 'string' }, 'no-write': { type: 'boolean' } }, allowPositionals: true });
            const task = value(values, 'task');
            if (!task)
                throw new Error('--task 必填');
            const result = await services.designTask({ task, direction: value(values, 'direction'), topK: numberValue(values, 'top') });
            const routed = result.routed;
            process.stdout.write(`① 任务类型: ${routed.task_type} | ${TASK_TYPES[routed.task_type]?.label ?? ''} | ${routed.basis}\n`);
            process.stdout.write(`   相关分类: ${routed.categories.join(', ')}\n`);
            process.stdout.write(`② 检索命中: ${result.retrieved.count} | 等级分布: ${JSON.stringify(result.retrieved.level_spread)} | 全部未核验: ${String(result.retrieved.unverified)}\n`);
            for (const hit of result.retrieved.hits.slice(0, 3))
                process.stdout.write(`   - ${hit.title.slice(0, 50)} | ${hit.level} | ${hit.source.url}\n`);
            process.stdout.write(`③ 候选方向: ${result.directions.map((direction) => direction.name).join(' / ')}\n`);
            process.stdout.write(`④ 设计系统: 对比度实算 ${result.design_system.contrast.length} 对，未达标 ${result.design_system.failing_pairs.length} 对\n`);
            for (const item of result.design_system.contrast)
                if (item.measured)
                    process.stdout.write(`   ${String(item.pair).padEnd(14)} ${item.fg} on ${item.bg} = ${Number(item.ratio).toFixed(2)}:1 AA=${String(item.AA_normal)}\n`);
            process.stdout.write(`⑥ 审计: ${JSON.stringify(result.audit.counts)} | 可实测项: ${result.audit.measured_items}\n`);
            process.stdout.write(`⑦ 反馈单元: ${result.feedback.scope} ${result.feedback.partition} ${result.feedback.level}\n`);
            if (!bool(values, 'no-write')) {
                const dir = join(root, 'docs', 'tasks');
                const stem = String(routed.task_type);
                write(join(dir, `${stem}.ds.json`), `${JSON.stringify({ task, task_type: routed.task_type, direction: result.chosen, design_system: result.design_system, audit: result.audit, feedback: result.feedback }, null, 2)}\n`);
                write(join(dir, `${stem}.${String(result.code_ext ?? 'html')}`), String(result.code ?? result.prototype_html));
                const md = [`# 设计任务: ${task}`, '', `- 任务类型: ${routed.task_type}（${TASK_TYPES[routed.task_type]?.label ?? ''}）`, `- 判定依据: ${routed.basis}`, `- 相关分类: ${routed.categories.join(', ')}`, `- 采用方向: ${result.chosen.name}`, '', '## ① 方向说明', ''];
                for (const [key, label] of [['idea', '设计理念'], ['style', '视觉风格'], ['color', '色彩体系'], ['type', '排版体系'], ['layout', '布局方式'], ['background', '背景方案'], ['interaction', '交互特点'], ['fits', '适用场景'], ['drawbacks', '潜在缺点']])
                    md.push(`- ${label}: ${String(result.chosen[key] ?? '')}`);
                md.push('', `## ② 检索到的知识（${result.retrieved.count} 条）`);
                for (const hit of result.retrieved.hits)
                    md.push(`- [${hit.level}] ${hit.title.slice(0, 60)} → ${hit.source.url}`);
                md.push('', '## ③ Design Tokens', '```css', tokensToCss(result.design_system), '```');
                md.push('', '## ④ 对比度实测', '', '| 组合 | 前景 | 背景 | 比值 | AA 正文 | AAA |', '| --- | --- | --- | --- | --- | --- |');
                for (const item of result.design_system.contrast)
                    if (item.measured)
                        md.push(`| ${item.pair} | ${item.fg} | ${item.bg} | ${Number(item.ratio).toFixed(2)}:1 | ${item.AA_normal ? '通过' : '不通过'} | ${item.AAA_normal ? '通过' : '不通过'} |`);
                md.push('', '## ⑤ 审计结果', '');
                for (const item of result.audit.items)
                    md.push(`- **${item.item}** — ${item.status}：${item.detail}`);
                md.push('', '> 注意：`unmeasured` 不等于通过；本任务未做真实设备渲染与用户测试。');
                write(join(dir, `${stem}.md`), `${md.join('\n')}\n`);
                process.stdout.write(`产出: ${join(dir, `${stem}.md`)}\n`);
            }
            return;
        }
        if (command === 'components') {
            const { values } = parseArgs({ args: rest, options: { keys: { type: 'string' }, all: { type: 'boolean' }, limit: { type: 'string' } }, allowPositionals: true });
            const result = await services.componentsLearn({ keys: split(value(values, 'keys')), all: bool(values, 'all'), limit: numberValue(values, 'limit') });
            printJson(result);
            return;
        }
        if (command === 'component-source') {
            const { values } = parseArgs({ args: rest, options: { repo: { type: 'string' }, file: { type: 'string' }, name: { type: 'string' } }, allowPositionals: true });
            const repo = value(values, 'repo');
            const file = value(values, 'file');
            if (!repo || !file)
                throw new Error('--repo 与 --file 必填');
            const result = await services.componentSource({ repo, file, name: value(values, 'name') });
            printJson(result);
            return;
        }
        if (command === 'stats') {
            const result = services.stats();
            if (bool(parseArgs({ args: rest, options: { json: { type: 'boolean' } }, allowPositionals: true }).values, 'json')) {
                printJson(result);
                return;
            }
            const registry = result.registry;
            const knowledge = result.knowledge;
            process.stdout.write(`资源 ${registry.total} · 片段 ${knowledge.chunks} · 项目 ${knowledge.projects}\n`);
            process.stdout.write(`访问: ${JSON.stringify(registry.access_status)}\n学习: ${JSON.stringify(registry.learn_status)}\n等级: ${JSON.stringify(knowledge.levels)}\n未核验: ${knowledge.verification.unverified ?? 0}\n数据库: ${knowledge.db_path}\n`);
            return;
        }
        if (command === 'eval') {
            const result = services.evaluate();
            const dir = join(root, 'eval');
            write(join(dir, 'runs.json'), `${JSON.stringify(result, null, 2)}\n`);
            const lines = ['# 检索评测报告（TypeScript 运行时）', '', `- 查询数：${result.per_query.length}`, `- 知识库片段：${result.chunk_count}`, `- 标注者：${result.annotator}`, `- 交叉编码器：不可用（rerank_ce 未参与）`, ''];
            lines.push('| 系统 | P@1 | P@3 | P@5 | R@10 | MRR@10 | nDCG@5 | 分类纯度@5 |', '| --- | --- | --- | --- | --- | --- | --- | --- |');
            for (const [system, metrics] of Object.entries(result.aggregate)) {
                lines.push(`| ${system} | ${fmt(metrics['P@1'])} | ${fmt(metrics['P@3'])} | ${fmt(metrics['P@5'])} | ${fmt(metrics['R@10'])} | ${fmt(metrics['MRR@10'])} | ${fmt(metrics['nDCG@5'])} | ${fmt(metrics['cat_purity@5'])} |`);
            }
            const delta = result.deltas_rerank_vs_rrf['nDCG@5'];
            lines.push('', `rerank_zh 相对 rrf 的 nDCG@5：${fmt(delta.mean_diff)}，95% 区间 [${fmt(delta.lo)}, ${fmt(delta.hi)}]，n=${delta.n}`);
            if (result.warnings.length > 0)
                lines.push('', `> ${result.warnings.join('；')}`);
            write(join(root, 'docs', 'EVAL-REPORT.md'), `${lines.join('\n')}\n`);
            if (bool(parseArgs({ args: rest, options: { json: { type: 'boolean' } }, allowPositionals: true }).values, 'json'))
                printJson(result);
            else
                process.stdout.write(`${lines.join('\n')}\n`);
            return;
        }
        throw new Error(`未知命令: ${command}（art-uiux help 查看用法）`);
    }
    finally {
        services.close();
    }
}
main().catch((error) => {
    process.stderr.write(`错误: ${asError(error).message}\n`);
    process.exitCode = 1;
});
