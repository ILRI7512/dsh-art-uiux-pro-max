/** 仓库根定位：环境变量 > 从模块位置向上查找 resources/seed.json。 */
import { existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
export function findRepositoryRoot(start) {
    let dir = start ? resolve(start) : dirname(fileURLToPath(import.meta.url));
    for (let depth = 0; depth < 10; depth += 1) {
        if (existsSync(join(dir, 'resources', 'seed.json')) || existsSync(join(dir, 'plugins', 'art-uiux', 'cordis.patch.yml')))
            return dir;
        const parent = dirname(dir);
        if (parent === dir)
            break;
        dir = parent;
    }
    return process.cwd();
}
export function resolveArtRoot(env = process.env) {
    return env.ART_UIUX_HOME ? resolve(env.ART_UIUX_HOME) : findRepositoryRoot();
}
