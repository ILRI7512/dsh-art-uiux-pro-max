# 三种背景方案（实测对比度）

## Mesh Gradient（多层径向渐变）

用 2–3 个低透明度径向渐变叠加出空间纵深，纯 CSS、无额外资源

```css
background-color: #0b0d12;
background-image:
  radial-gradient(60% 50% at 15% 20%, rgba(76,154,255,.22), transparent 70%),
  radial-gradient(50% 45% at 85% 10%, rgba(255,120,80,.16), transparent 70%),
  radial-gradient(80% 60% at 50% 110%, rgba(120,255,200,.10), transparent 70%);
```

- 对比度（正文 #e6e9ee 对最坏背景 #141821）：**14.59:1** → AA 通过
- 性能代价：一次性绘制的渐变层，通常只有 1 次 paint；滚动时不重绘。风险最低。（low）
- 结论：对比度为实算；绘制耗时与设备掉帧未测。

## Noise Overlay（噪点叠加）

在纯色或渐变上叠一层极低透明度噪点，消除塑料感并掩盖渐变断层（banding）

```css
background-color: #101318;
background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='120' height='120'>
  <filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.8' numOctaves='2'/></filter>
  <rect width='120' height='120' filter='url(%23n)' opacity='0.06'/></svg>");
background-size: 120px 120px;
```

- 对比度（正文 #e6e9ee 对最坏背景 #101318）：**15.29:1** → AA 通过
- 性能代价：SVG 滤镜在首次栅格化时较贵；平铺后为位图缓存，滚动开销低。避免对大尺寸元素动态重算。（medium）
- 结论：对比度为实算；绘制耗时与设备掉帧未测。

## Conic Sweep（锥形旋光）

锥形渐变制造方向性光带，适合强调区块；必须给 reduced-motion 兜底

```css
background: conic-gradient(from 210deg at 50% 50%,
  rgba(76,154,255,.28), rgba(180,120,255,.16), rgba(76,154,255,.28));
animation: sweep 18s linear infinite;
@media (prefers-reduced-motion: reduce) { .sweep { animation: none } }
```

- 对比度（正文 #e6e9ee 对最坏背景 #1a1f2b）：**13.54:1** → AA 通过
- 性能代价：旋转动画会持续合成（compositor）层；大区域 + 低端设备可能掉帧，建议限制在卡片级尺寸。（high）
- 结论：对比度为实算；绘制耗时与设备掉帧未测。
