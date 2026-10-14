import { unzip, zipSync } from "fflate";
const MAX_DISC_BYTES = 800 * 1024 * 1024;
export async function readDisc(input) {
  let disc = input;
  if (/\.zip$/i.test(input.name)) {
    let oversized = false;
    if (input.size > MAX_DISC_BYTES) throw new Error("Disc ZIP is too large.");
    const bytes = new Uint8Array(await input.arrayBuffer());
    const files = await new Promise((resolve, reject) =>
      unzip(
        bytes,
        {
          filter: (entry) => {
            const accept = /\.iso$/i.test(entry.name);
            if (accept && entry.originalSize > MAX_DISC_BYTES) {
              oversized = true;
              return false;
            }
            return accept;
          },
        },
        (error, result) =>
          error
            ? reject(new Error("Could not read this ZIP archive."))
            : resolve(result),
      ),
    );
    if (oversized) throw new Error("An ISO in this ZIP exceeds 800 MiB.");
    const names = Object.keys(files);
    if (names.length !== 1)
      throw new Error("Choose a ZIP containing exactly one Sega CD ISO.");
    disc = new File([files[names[0]]], names[0].split("/").pop(), {
      type: "application/octet-stream",
    });
  }
  return validateDisc(disc);
}
export async function validateDisc(disc) {
  if (
    !(disc instanceof Blob) ||
    disc.size < 32768 ||
    disc.size > MAX_DISC_BYTES ||
    disc.size % 2048
  )
    throw new Error(
      "Choose a Sega CD ISO with 2048-byte sectors (up to 800 MiB).",
    );
  const header = new Uint8Array(await disc.slice(0, 512).arrayBuffer());
  const text = new TextDecoder().decode(header);
  if (!text.startsWith("SEGADISCSYSTEM"))
    throw new Error("This file is not a Sega CD disc image.");
  const regionField = new TextDecoder().decode(header.slice(0x1f0, 0x200));
  const region = regionField.includes("J")
    ? "jp"
    : regionField.includes("U")
      ? "us"
      : null;
  if (!region) throw new Error("Choose a Japan or North America NTSC disc.");
  const name = (disc.name || "encoded.iso").replace(/[^a-zA-Z0-9_.-]/g, "_");
  return {
    file: new File([disc], name.endsWith(".iso") ? name : `${name}.iso`, {
      type: "application/octet-stream",
    }),
    region,
  };
}
export async function prepareBios(file, region) {
  if (file.size !== 131072)
    throw new Error("Choose an uncompressed 128 KiB Sega CD BIOS (.bin).");
  const bytes = new Uint8Array(await file.arrayBuffer());
  const archive = zipSync({
    [region === "jp" ? "bios_CD_J.bin" : "bios_CD_U.bin"]: bytes,
  });
  return new File([archive], "bios.zip", { type: "application/zip" });
}
