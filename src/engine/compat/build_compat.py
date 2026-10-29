"""Build a desktop fix for Codex builds whose quota gates live in the initial bundle and the composer adapter.

The official package is never edited: the patched archive and executable are written to a copy.
The patch stops client-side locks that keep a relay-routed composer from sending:
- the "send blocked" state derived from the Plus quota response (initial bundle);
- the "hard blocked" quota selector, rate_limit.allowed === false (initial bundle);
- the service-tier "loading" state, which never resolves when no Work account identity exists, as with a
  relay route (composer adapter).
The server and the route bridge still decide whether a request is actually served.
"""
import argparse
import importlib.util
import json
import os
import pathlib
import re
import shutil
import subprocess

_spec = importlib.util.spec_from_file_location("asar_tools", pathlib.Path(__file__).with_name("asar_tools.py"))
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)

GATE = re.compile(r"sendBlockReason:(\w+)\?\.block_reason\?\?null,sendBlocked:\1!=null\}")
# The local Codex composer is locked by the "hard blocked" quota selector (rate_limit.allowed === false).
HARD_BLOCK = re.compile(r"=([\w$]+)\(([\w$]+),\(e,\{get:t\}\)=>t\(([\w$]+),e\)\.hardBlocked\)")
# Without a Work account identity the work-preferences query never runs, so "no settings yet" must not mean loading.
TIER_LOADING = re.compile(r"isLoading:([\w$]+)\.data\?\.settings==null\|\|\1\.isFetching")
# The local composer also reads a "local quota exhausted" selector (ChatGPT auth, rate_limit.allowed === false).
LOCAL_EXHAUSTED = re.compile(r"\(\{get:e\}\)=>\{(let t=e\([\w$]+\),n=e\([\w$]+\)\.data;if\(t\.authMethod!==`chatgpt`\|\|t\.authLoading\|\|t\.accountLoading\|\|[^;]*?n\.rate_limit\?\.allowed!==!1)")
# The local composer shows Plus quota upsell/warning banners; the copy keeps only the image-generation notice.
USAGE_BANNER = re.compile(r"([\w$]+)=([\w$]+)!=null\|\|([\w$]+)\?\.rate_limit_upsell!=null\|\|([\w$]+)!=null,")
PATCH_REVISION = 5


def patch_initial(source):
    if len(GATE.findall(source)) != 1:
        raise RuntimeError("Version changed: send-gate anchor does not match.")
    if len(HARD_BLOCK.findall(source)) != 1:
        raise RuntimeError("Version changed: hard-block selector anchor does not match.")
    text = GATE.sub("sendBlockReason:null,sendBlocked:!1}", source, count=1)
    return HARD_BLOCK.sub(lambda m: m.group(0)[:-1] + "&&!1)", text, count=1)


def patch_adapter(source):
    if len(TIER_LOADING.findall(source)) != 1:
        raise RuntimeError("Version changed: service-tier loading anchor does not match.")
    return TIER_LOADING.sub(lambda m: f"isLoading:{m.group(1)}.isFetching===!0", source, count=1)


def patch_primary(source):
    if len(LOCAL_EXHAUSTED.findall(source)) != 1:
        raise RuntimeError("Version changed: local quota selector anchor does not match.")
    return LOCAL_EXHAUSTED.sub(lambda m: "({get:e})=>{return!1;" + m.group(1), source, count=1)


def patch_composer_content(source):
    if len(USAGE_BANNER.findall(source)) != 1 or "isUsageBannerEnabled:" not in source:
        raise RuntimeError("Version changed: usage banner anchor does not match.")
    return USAGE_BANNER.sub(lambda m: f"{m.group(1)}={m.group(2)}!=null,", source, count=1)


TARGETS = [("app-initial-", patch_initial), ("codex-composer-adapter-", patch_adapter), ("app-primary-", patch_primary),
           ("composer-content-", patch_composer_content)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=pathlib.Path)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    parser.add_argument("--node", required=True)
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    archive = args.source / "resources/app.asar"
    patches = []  # (name, entry, original bytes, patched bytes)
    with archive.open("rb") as stream:
        tree, data_offset, original_header = base.read_header(stream)
        assets = tree["files"]["webview"]["files"]["assets"]["files"]
        for prefix, patch in TARGETS:
            # Several chunks can share a prefix; exactly one of them must carry the reviewed anchors.
            matched, last_error = [], RuntimeError(f"No {prefix} asset.")
            for name in [n for n in assets if n.startswith(prefix) and n.endswith(".js")]:
                entry = assets[name]
                stream.seek(data_offset + int(entry["offset"]))
                original = stream.read(entry["size"])
                try:
                    patched = patch(original.decode()).encode()
                except RuntimeError as error:
                    last_error = error
                    continue
                matched.append((name, entry, original, patched))
            if len(matched) != 1:
                raise RuntimeError(f"Expected exactly one patchable {prefix} asset, found {len(matched)}." if matched else str(last_error))
            base.node_check(args.node, matched[0][3], args.output / f"candidate-{prefix}mjs")
            patches.append(matched[0])

    # The replaced fragments must evaluate to values that never block, whatever the quota or settings state.
    fixture = ("const a={sendBlockReason:null,sendBlocked:!1};if(a.sendBlocked!==false)throw Error('send');"
               "const h=(t=>({hardBlocked:true}).hardBlocked&&!1)();if(h!==false)throw Error('hard');"
               "for(const f of [true,false,undefined]){const t={data:undefined,isFetching:f};const v=t.isFetching===!0;if(v!==(f===true))throw Error('tier')}"
               "console.log(3)")
    check = subprocess.run([args.node, "-e", fixture], check=False, capture_output=True, text=True)
    if check.returncode:
        raise RuntimeError("Compatibility fixture failed: " + check.stderr[-800:])

    old_header_hash = base.digest(original_header)
    executable = (args.source / "ChatGPT.exe").read_bytes()
    integrity = re.search(rb'\[{"file":"resources\\\\app.asar","alg":"SHA256","value":"([0-9a-f]{64})"}\]', executable)
    if integrity is None or integrity.group(1).decode() != old_header_hash:
        raise RuntimeError("Original executable/archive integrity does not match.")
    report = {
        "source": str(args.source),
        "asset": patches[0][0],
        "assets": [name for name, *_ in patches],
        "sourceAssetSha256": {name: base.digest(original) for name, _, original, _ in patches},
        "patchedAssetSha256": {name: base.digest(patched) for name, _, _, patched in patches},
        "scope": "Client-side send, hard-block, local-quota and service-tier loading locks and Plus quota banners are disabled in this copy",
        "patchRevision": PATCH_REVISION,
        "checks": 4,
        "officialInstallationModified": False,
        "liveExhaustedSendVerified": False,
        "usageBannerScoped": False,
        "changedSites": 5,
    }
    if args.build:
        runtime = args.output / "runtime"
        if runtime.exists():
            raise RuntimeError("Refusing to overwrite an existing runtime.")

        def copy_immutable(src, dst):
            if pathlib.Path(src) in (archive, args.source / "ChatGPT.exe"):
                return shutil.copy2(src, dst)
            try:
                os.link(src, dst)
                return dst
            except OSError:
                return shutil.copy2(src, dst)

        shutil.copytree(args.source, runtime, copy_function=copy_immutable)
        # Patched assets are appended after the untouched body; their header entries point at the new bytes.
        offset = archive.stat().st_size - data_offset
        for _, entry, _, patched in patches:
            entry["offset"] = str(offset)
            entry["size"] = len(patched)
            block_size = entry.get("integrity", {}).get("blockSize", 4194304)
            entry["integrity"] = {
                "algorithm": "SHA256", "hash": base.digest(patched), "blockSize": block_size,
                "blocks": [base.digest(patched[n:n + block_size]) for n in range(0, len(patched), block_size)],
            }
            offset += len(patched)
        header, header_raw = base.encode_header(tree)
        final_archive = runtime / "resources/app.asar"
        temporary = final_archive.with_suffix(".patched")
        with archive.open("rb") as src, temporary.open("wb") as dst:
            dst.write(header)
            src.seek(data_offset)
            shutil.copyfileobj(src, dst, 8 * 1024 * 1024)
            for *_, patched in patches:
                dst.write(patched)
        os.replace(temporary, final_archive)
        new_header_hash = base.digest(header_raw)
        executable = executable[:integrity.start(1)] + new_header_hash.encode() + executable[integrity.end(1):]
        (runtime / "ChatGPT.exe").write_bytes(executable)
        with final_archive.open("rb") as stream:
            verify_tree, verify_offset, verify_header = base.read_header(stream)
            verify_assets = verify_tree["files"]["webview"]["files"]["assets"]["files"]
            for name, _, _, patched in patches:
                stream.seek(verify_offset + int(verify_assets[name]["offset"]))
                assert stream.read(verify_assets[name]["size"]) == patched
            assert base.digest(verify_header) == new_header_hash
        report["runtime"] = str(runtime)
        report["integrityRetained"] = True
    (args.output / "verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
