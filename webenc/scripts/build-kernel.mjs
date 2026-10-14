import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, copyFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
const root = fileURLToPath(new URL("../", import.meta.url));
const local = path.join(root, ".toolchain/cargo/bin/cargo");
const env = { ...process.env };
if (existsSync(local)) {
  env.RUSTUP_HOME = path.join(root, ".toolchain/rustup");
  env.CARGO_HOME = path.join(root, ".toolchain/cargo");
}
const result = spawnSync(
  existsSync(local) ? local : "cargo",
  [
    "build",
    "--manifest-path",
    path.join(root, "encoder/Cargo.toml"),
    "--release",
    "--target",
    "wasm32-unknown-unknown",
  ],
  { env, stdio: "inherit" },
);
if (result.error)
  throw new Error(
    "Rust is required to build the kernel. Install Rust and the wasm32-unknown-unknown target.",
  );
if (result.status !== 0) process.exit(result.status || 1);
mkdirSync(path.join(root, "public/wasm"), { recursive: true });
copyFileSync(
  path.join(
    root,
    "encoder/target/wasm32-unknown-unknown/release/webenc_kernel.wasm",
  ),
  path.join(root, "public/wasm/webenc-kernel.wasm"),
);
