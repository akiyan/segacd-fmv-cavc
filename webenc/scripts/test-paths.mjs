// Fixture storage follows the same runtime options as the native tools.
import path from 'node:path';
import {fileURLToPath} from 'node:url';
export const workspace = path.resolve(process.env.CAVC_WORKSPACE_ROOT ||
  process.env.SEGACD_TMPFS_ROOT || fileURLToPath(new URL('../../tmp/workspace', import.meta.url)));
export const qaRoot = path.resolve(process.env.WEBENC_TEST_OUTPUT || path.join(workspace, 'webenc-qa'));
export const kernelRoot = path.resolve(process.env.WEBENC_KERNEL_OUTPUT || path.join(workspace, 'webenc-kernel-test'));
