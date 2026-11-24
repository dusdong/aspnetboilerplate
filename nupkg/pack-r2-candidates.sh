#!/bin/bash
set -euo pipefail

usage() {
    echo '用法：bash nupkg/pack-r2-candidates.sh --version 10.5.1-r2.<序号> --output <空目录>' >&2
    exit 2
}

version=
output=
while [[ $# -gt 0 ]]; do
    case "$1" in
        --version) [[ $# -ge 2 && -z "$version" ]] || usage; version=$2 ;;
        --output) [[ $# -ge 2 && -z "$output" ]] || usage; output=$2 ;;
        *) usage ;;
    esac
    shift 2
done
[[ "$version" =~ ^10[.]5[.]1-r2[.][1-9][0-9]*$ && -n "$output" ]] || usage

framework=$(cd "$(dirname "$0")/.." && pwd -P)
common_git_dir=$(git -C "$framework" rev-parse --path-format=absolute --git-common-dir)
mkdir -p -- "$output"
output=$(cd "$output" && pwd -P)
case "$output/" in
    "$framework/"*) echo '请指定框架源码目录以外的输出位置。' >&2; exit 2 ;;
esac
if [[ -n "$(find "$output" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
    echo "候选输出目录须为空：$output" >&2
    exit 2
fi

scratch=$(mktemp -d "${TMPDIR:-/tmp}/du-abp-candidate.XXXXXXXX")
trap 'rm -rf -- "$scratch"' EXIT
mkdir "$scratch/source" "$scratch/packed"
mkdir "$output/logs"
commands="$output/commands.log"

run() {
    local logfile=$1 rc=0
    shift
    printf '目录 %q\n命令 ' "$PWD" >> "$commands"
    printf '%q ' "$@" >> "$commands"
    printf '\n日志 %q\n' "$logfile" >> "$commands"
    "$@" > "$logfile" 2>&1 || rc=$?
    printf '退出码 %s\n' "$rc" >> "$commands"
    if [[ "$rc" -ne 0 ]]; then
        tail -n 30 "$logfile" >&2
    fi
    return "$rc"
}

cd "$framework"
superproject=$(git rev-parse --show-superproject-working-tree)
if [[ -n "$superproject" ]]; then
    superproject_commit=$(git -C "$superproject" rev-parse HEAD)
    gitlink=$(git -C "$superproject" ls-tree "$superproject_commit" -- "${framework#"$superproject"/}")
    read -r mode type framework_gitlink path <<< "$gitlink"
    printf '%s\n%s\n' "$superproject_commit" "$framework_gitlink" > "$output/superproject-input.txt"
fi
base=$(git rev-parse HEAD)
base_tree=$(git rev-parse "$base^{tree}")
# 独立索引捕获当前源码，包括未跟踪的实现文件。
export GIT_INDEX_FILE="$scratch/index"
run "$output/logs/read-tree.log" git read-tree "$base"
run "$output/logs/add-source.log" git add --all -- .
run "$output/logs/write-tree.log" git write-tree
tree=$(cat "$output/logs/write-tree.log")
run "$output/source.patch" git diff --cached --no-color --no-ext-diff --no-textconv --full-index --binary "$base"
unset GIT_INDEX_FILE
run "$output/logs/archive.log" git archive --format=tar --output="$scratch/source.tar" "$tree"
run "$output/logs/extract.log" tar -xf "$scratch/source.tar" -C "$scratch/source"

source_commit=
if [[ "$tree" == "$base_tree" ]]; then
    source_commit=$base
fi
proof="$output/du-core-candidate-source.json"
python3 - "$base" "$tree" "$source_commit" "$output/source.patch" > "$proof" <<'PY'
import hashlib
import json
import pathlib
import sys

base, tree, commit, patch = sys.argv[1:]
proof = {"baseCommit": base, "tree": tree, "patchSha256": hashlib.sha256(pathlib.Path(patch).read_bytes()).hexdigest()}
if commit:
    proof["commit"] = commit
print(json.dumps(proof, indent=2))
PY
cp "$proof" "$scratch/du-core-candidate-source.json"

cd "$scratch/source"
run "$output/logs/sdk.txt" dotnet --version
sdk=$(cat "$output/logs/sdk.txt")
if [[ "$sdk" != 10.0.404 ]]; then
    echo "候选打包需要 SDK 10.0.404，实际为 $sdk。" >&2
    exit 1
fi

cat > "$output/NuGet.Config" <<'XML'
<configuration>
  <packageSources>
    <clear />
    <add key="nuget.org" value="https://api.nuget.org/v3/index.json" />
  </packageSources>
  <fallbackPackageFolders>
    <clear />
  </fallbackPackageFolders>
</configuration>
XML
export NUGET_PACKAGES="$scratch/packages"
export NUGET_HTTP_CACHE_PATH="$scratch/http-cache"
printf 'NUGET_PACKAGES=%q\nNUGET_HTTP_CACHE_PATH=%q\n' "$NUGET_PACKAGES" "$NUGET_HTTP_CACHE_PATH" >> "$commands"
cp "$output/NuGet.Config" "$scratch/NuGet.Config"

assemblies=(Abp Abp.Web.Common Abp.AspNetCore Abp.EntityFramework.Common Abp.EntityFrameworkCore)
properties=(-p:Configuration=Release -p:DuCoreCandidatePack=true
    "-p:DuCoreCandidatePackageVersion=$version"
    "-p:DuCoreCandidateSourceProof=$scratch/du-core-candidate-source.json"
    "-p:DuCoreCandidateCommit=$source_commit")
for name in "${assemblies[@]}"; do
    for target in net9.0 net10.0; do
        run "$output/logs/$name.$target.json" dotnet msbuild "src/$name/$name.csproj" -nologo \
            "${properties[@]}" -p:TargetFramework="$target" \
            -getProperty:PackageId,PackageVersion,Version,AssemblyName,RootNamespace,TargetFrameworks,TargetFramework,TargetPath,GeneratePackageOnBuild,IsPackable,RepositoryUrl,RepositoryCommit,IncludeSymbols,SymbolPackageFormat \
            -getItem:ProjectReference,PackageReference,FrameworkReference
    done
done

# 版本记录与输出位置无关，避免同一检出并发或换目录重用版本。
version_record="$common_git_dir/du-core-candidate-versions/$version"
mkdir -p "$(dirname "$version_record")"
if ! mkdir "$version_record"; then
    echo "候选版本已分配或无法分配：$version_record" >&2
    exit 2
fi
cp "$proof" "$version_record/source.json"
printf '%s\n' "$output" > "$version_record/output.txt"

for name in "${assemblies[@]}"; do
    project="src/$name/$name.csproj"
    run "$output/logs/$name.restore.log" dotnet restore "$project" "${properties[@]}" \
        --configfile "$scratch/NuGet.Config" --no-http-cache --disable-build-servers
done
for name in "${assemblies[@]}"; do
    cp "src/$name/obj/project.assets.json" "$output/logs/$name.project.assets.json"
    run "$output/logs/$name.pack.log" dotnet pack "src/$name/$name.csproj" "${properties[@]}" \
        --no-restore -c Release --disable-build-servers --output "$scratch/packed"
done

python3 - "$version" "$sdk" "$output" "$scratch/packed" "${assemblies[@]}" <<'PY'
import hashlib
import json
import pathlib
import shutil
import sys
import zipfile

version, sdk, output, packed, *assemblies = sys.argv[1:]
output, packed = pathlib.Path(output), pathlib.Path(packed)
targets = ("net9.0", "net10.0")
repository = "https://github.com/dusdong/aspnetboilerplate.git"
proof = (output / "du-core-candidate-source.json").read_bytes()
packages = {}

def sha256(data):
    return hashlib.sha256(data).hexdigest()

for name in assemblies:
    package_id = f"Du.{name}"
    package_file = f"{package_id}.{version}.nupkg"
    symbols_file = f"{package_id}.{version}.snupkg"
    with zipfile.ZipFile(packed / package_file) as package, zipfile.ZipFile(packed / symbols_file) as symbols:
        if package.read("du-core-candidate-source.json") != proof:
            raise ValueError(f"{package_file} 的源码来源记录不一致")
        assets = {}
        for target in targets:
            evaluation = json.loads((output / "logs" / f"{name}.{target}.json").read_text())
            build_dll = pathlib.Path(evaluation["Properties"]["TargetPath"]).read_bytes()
            path = f"lib/{target}/{name}.dll"
            pdb = f"lib/{target}/{name}.pdb"
            if package.read(path) != build_dll:
                raise ValueError(f"{package_file} 内的 {path} 与构建产物不一致")
            assets[target] = {"path": path, "sha256": sha256(build_dll), "pdbPath": pdb, "pdbSha256": sha256(symbols.read(pdb))}
    packages[package_id] = {
        "assemblyName": name,
        "package": {"file": package_file, "sha256": sha256((packed / package_file).read_bytes())},
        "symbols": {"file": symbols_file, "sha256": sha256((packed / symbols_file).read_bytes())},
        "targets": assets,
    }

manifest = {
    "schemaVersion": 1,
    "version": version,
    "sdk": sdk,
    "repositoryUrl": repository,
    "sourceProof": json.loads(proof),
    "restore": {"config": "NuGet.Config", "source": "https://api.nuget.org/v3/index.json", "commands": "commands.log"},
    "packages": packages,
}
superproject = output / "superproject-input.txt"
if superproject.exists():
    commit, gitlink = superproject.read_text().splitlines()
    manifest["superproject"] = {"commit": commit, "frameworkGitlink": gitlink}

for directory, kind in (("feed", "package"), ("symbols", "symbols")):
    destination = output / directory
    destination.mkdir()
    for entry in packages.values():
        filename = entry[kind]["file"]
        shutil.copyfile(packed / filename, destination / filename)
(output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
PY
cp "$output/manifest.json" "$version_record/manifest.json"
printf '候选源 %s/feed\n候选清单 %s/manifest.json\n' "$output" "$output"
