# Third-Party Notices

## Design intelligence data

`resources/design-library.json` and `resources/design-aliases.json` are a static,
subset snapshot of the design database shipped with
[dsh-ui-ux-pro-max](https://github.com/ChenYiming-aaa/dsh-ui-ux-pro-max) v1.4.1
(MIT), which in turn packages
[nextlevelbuilder/ui-ux-pro-max-skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill)
at commit `56ea9cf174ed86786187daa9de0e6247cb0747e4`.

| Field | Value |
| --- | --- |
| Upstream | `nextlevelbuilder/ui-ux-pro-max-skill` (MIT) |
| Snapshot ref | `56ea9cf174ed86786187daa9de0e6247cb0747e4` |
| Snapshot date | 2026-10-15 |
| Included domains | style (88), color (192), chart (25), landing (34), product (192), ux (119), typography (74), react (44), web (32), reasoning (192) |
| Excluded | icon / GSAP / stack guideline / Google Fonts tables and all font binaries |

The TypeScript search, recommendation, review and token-mapping code in
`src/domain/design-library.ts` is our own implementation; it does not copy the
upstream Python or JavaScript source. Data rows are used as reference material
under the upstream MIT license. The bundled snapshot is static: this plugin does
not fetch or sync it at runtime.
