window.__ModuleLoader__.load({
    id: '@local/art-uiux',
    factory(require) {
        const React = require('react');
        const h = React.createElement;
        const PACKAGE_NAME = '@local/art-uiux';
        const API = '/art-uiux/api/settings';
        const STATS = '/art-uiux/api/stats';
        const token = (name, fallback) => `var(${name}, ${fallback})`;
        const COLORS = {
            label: token('--dsw-alias-label-primary', 'inherit'),
            secondary: token('--dsw-alias-label-secondary', 'rgba(127,127,127,0.9)'),
            border: token('--dsw-alias-border-l2', 'rgba(127,127,127,0.25)'),
            field: token('--dsw-alias-bg-layer-2', 'rgba(127,127,127,0.10)'),
            accent: token('--dsw-alias-brand-primary', '#4a7cf0'),
            danger: token('--dsw-alias-label-danger', '#d9534f'),
            success: token('--dsw-alias-label-success', '#2e9e5b'),
        };
        const fieldStyle = {
            width: '100%', boxSizing: 'border-box', padding: '8px 10px', borderRadius: 8,
            border: `1px solid ${COLORS.border}`, background: COLORS.field, color: COLORS.label,
            fontSize: 13, fontFamily: 'inherit',
        };
        const cardStyle = {
            border: `1px solid ${COLORS.border}`, borderRadius: 12, padding: 16, marginBottom: 16,
            background: 'transparent',
        };
        function Row(props) {
            return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 16 } }, h('div', { style: { fontSize: 13, fontWeight: 600, color: COLORS.label } }, props.label), props.control, props.hint ? h('div', { style: { fontSize: 12, lineHeight: 1.5, color: COLORS.secondary } }, props.hint) : null);
        }
        function Toggle(props) {
            return h('label', { style: { display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: COLORS.label } }, h('input', { type: 'checkbox', checked: Boolean(props.value), onChange: (event) => props.onChange(event.target.checked) }), props.label);
        }
        function Stat(props) {
            return h('div', { style: { padding: '10px 12px', borderRadius: 8, background: COLORS.field } }, h('div', { style: { fontSize: 11, color: COLORS.secondary } }, props.label), h('div', { style: { fontSize: 18, fontWeight: 650, color: COLORS.label } }, String(props.value)));
        }
        function ConfigCard() {
            const [state, setState] = React.useState({ phase: 'loading' });
            const [draft, setDraft] = React.useState({ dataDir: '', allowNetwork: true, allowPrivateNetworks: false, maxUnits: 10, rerank: 'rules' });
            const [saving, setSaving] = React.useState(false);
            const [message, setMessage] = React.useState('');
            const [stats, setStats] = React.useState(null);
            const load = React.useCallback(() => {
                setState({ phase: 'loading' });
                fetch(API).then((response) => {
                    if (!response.ok)
                        throw new Error(`HTTP ${response.status}`);
                    return response.json();
                }).then((data) => {
                    setDraft({
                        dataDir: data.settings.dataDir || '',
                        allowNetwork: data.settings.allowNetwork,
                        allowPrivateNetworks: data.settings.allowPrivateNetworks,
                        maxUnits: data.settings.maxUnits,
                        rerank: data.settings.rerank,
                    });
                    setState({ phase: 'ready', data });
                    setMessage('');
                }).catch((error) => {
                    setState({ phase: 'error', error: error.message });
                });
                fetch(STATS).then((response) => response.ok ? response.json() : null).then(setStats).catch(() => undefined);
            }, []);
            React.useEffect(load, [load]);
            const save = React.useCallback(() => {
                setSaving(true);
                setMessage('');
                fetch(API, {
                    method: 'POST',
                    headers: { 'content-type': 'application/json' },
                    body: JSON.stringify({
                        dataDir: draft.dataDir.trim(),
                        allowNetwork: Boolean(draft.allowNetwork),
                        allowPrivateNetworks: Boolean(draft.allowPrivateNetworks),
                        maxUnits: Number(draft.maxUnits),
                        rerank: draft.rerank,
                    }),
                }).then(async (response) => {
                    const body = await response.json();
                    if (!response.ok)
                        throw new Error(body.error || `HTTP ${response.status}`);
                    setMessage('已保存，下一次调用生效');
                    setState({ phase: 'ready', data: body });
                    fetch(STATS).then((r) => r.ok ? r.json() : null).then(setStats).catch(() => undefined);
                }).catch((error) => {
                    setMessage(`保存失败：${error.message}`);
                }).finally(() => setSaving(false));
            }, [draft]);
            if (state.phase === 'loading') {
                return h('div', { style: { padding: 16, color: COLORS.secondary, fontSize: 13 } }, '正在读取 Art UI/UX 设置…');
            }
            if (state.phase === 'error') {
                return h('div', { style: { padding: 16, color: COLORS.danger, fontSize: 13 } }, `设置读取失败：${state.error}`);
            }
            const data = state.data;
            return h('div', null, h('div', { style: { marginBottom: 12 } }, h('div', { style: { fontSize: 15, fontWeight: 650, color: COLORS.label } }, 'Art UI/UX · 知识库与网络'), h('div', { style: { fontSize: 12, color: COLORS.secondary, marginTop: 4 } }, `数据目录：${data.effectiveDataDir || '(未设置)'} · 设置文件：${data.settingsPath || '(未找到)'}`)), h('div', { style: cardStyle }, h(Row, {
                label: '数据目录',
                hint: '绝对路径；留空使用 <repo>/data。修改后会切换到该目录下的 knowledge.sqlite3。',
                control: h('input', { style: fieldStyle, value: draft.dataDir, placeholder: '例如 /root/art-data', onChange: (e) => setDraft({ ...draft, dataDir: e.target.value }) }),
            }), h(Row, {
                label: '网络访问',
                hint: '关闭后 check / learn / case / 组件学习全部拒绝（返回 NETWORK_BLOCKED），不会静默降级。',
                control: h(Toggle, { label: '允许抓取公开页面与 GitHub API', value: draft.allowNetwork, onChange: (value) => setDraft({ ...draft, allowNetwork: value }) }),
            }), h(Row, {
                label: '允许私网地址',
                hint: '默认禁止 loopback / RFC1918 / link-local，避免资源 URL 变成 SSRF 入口。只在本机调试时打开。',
                control: h(Toggle, { label: '允许 127.0.0.1、局域网与 IPv6 ULA', value: draft.allowPrivateNetworks, onChange: (value) => setDraft({ ...draft, allowPrivateNetworks: value }) }),
            }), h(Row, {
                label: '单次学习区块上限',
                hint: '1–100；只影响单个资源一次最多处理多少个正文区块。',
                control: h('input', { type: 'number', min: 1, max: 100, style: fieldStyle, value: draft.maxUnits, onChange: (e) => setDraft({ ...draft, maxUnits: Number(e.target.value) }) }),
            }), h(Row, {
                label: '默认重排策略',
                hint: 'rules 可离线运行；ce 需要额外模型，当前 TS 运行时会显式降级并告警。',
                control: h('select', { style: fieldStyle, value: draft.rerank, onChange: (e) => setDraft({ ...draft, rerank: e.target.value }) }, h('option', { value: 'rules' }, 'rules（确定性重排）'), h('option', { value: 'ce' }, 'ce（交叉编码器，可选）')),
            }), h('div', { style: { display: 'flex', gap: 10, alignItems: 'center' } }, h('button', {
                type: 'button',
                disabled: saving,
                onClick: save,
                style: { padding: '8px 16px', borderRadius: 8, border: 'none', background: COLORS.accent, color: '#fff', fontSize: 13, cursor: saving ? 'not-allowed' : 'pointer' },
            }, saving ? '保存中…' : '保存'), h('button', {
                type: 'button',
                onClick: load,
                style: { padding: '8px 14px', borderRadius: 8, border: `1px solid ${COLORS.border}`, background: 'transparent', color: COLORS.label, fontSize: 13, cursor: 'pointer' },
            }, '重新读取'), message ? h('span', { style: { fontSize: 12, color: message.startsWith('保存失败') ? COLORS.danger : COLORS.success } }, message) : null)), stats ? h('div', { style: cardStyle }, h('div', { style: { fontSize: 13, fontWeight: 600, color: COLORS.label, marginBottom: 10 } }, '知识库状态（只读）'), h('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(110px, 1fr))', gap: 8 } }, h(Stat, { label: '资源', value: stats.registry?.total ?? 0 }), h(Stat, { label: '片段', value: stats.knowledge?.chunks ?? 0 }), h(Stat, { label: '已学片段（注册表）', value: stats.registry?.learned_chunks_total ?? 0 }), h(Stat, { label: '可访问资源', value: stats.registry?.access_status?.reachable ?? 0 }), h(Stat, { label: '设计库', value: `${stats.library?.counts?.style ?? 0} 风格` }), h(Stat, { label: '调色板', value: stats.library?.counts?.color ?? 0 })), h('div', { style: { fontSize: 11, lineHeight: 1.6, color: COLORS.secondary, marginTop: 10 } }, `等级分布：${JSON.stringify(stats.knowledge?.levels ?? {})} · 未核验：${stats.knowledge?.verification?.unverified ?? 0} · 设计库 ${stats.library?.counts?.style ?? 0} 风格 / ${stats.library?.counts?.color ?? 0} 调色板 / ${stats.library?.counts?.typography ?? 0} 字体`)) : null, h('div', { style: { fontSize: 11, lineHeight: 1.7, color: COLORS.secondary } }, '资源“可访问”不等于“已学习”；学习等级最高到 L2 时必须经交叉验证或真实任务才可升级。工具调用结果里的 warnings 不得忽略。'));
        }
        return {
            inject: ['slots'],
            apply(ctx) {
                ctx.slots.inject('plugins.bundle.config', function* () {
                    yield ctx.slots.register({ name: 'plugins.bundle.config', key: PACKAGE_NAME }, ConfigCard);
                });
            },
        };
    },
});

