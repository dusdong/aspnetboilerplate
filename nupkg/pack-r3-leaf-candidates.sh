#!/bin/bash
set -euo pipefail

usage() {
    echo '用法：bash nupkg/pack-r3-leaf-candidates.sh --version 10.5.1-r3.<序号> --r2-feed <R2源目录> --output <空目录>' >&2
    exit 2
}

version=
r2_feed=
output=
while [[ $# -gt 0 ]]; do
    case "$1" in
        --version) [[ $# -ge 2 && -z "$version" ]] || usage; version=$2 ;;
        --r2-feed) [[ $# -ge 2 && -z "$r2_feed" ]] || usage; r2_feed=$2 ;;
        --output) [[ $# -ge 2 && -z "$output" ]] || usage; output=$2 ;;
        *) usage ;;
    esac
    shift 2
done
[[ "$version" =~ ^10[.]5[.]1-r3[.][1-9][0-9]*$ && -n "$r2_feed" && -n "$output" ]] || usage

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
r2_feed=$(cd "$r2_feed" && pwd -P)

scratch=$(mktemp -d "${TMPDIR:-/tmp}/du-abp-r3.XXXXXXXX")
trap 'rm -rf -- "$scratch"' EXIT
mkdir "$scratch/source" "$scratch/objects" "$scratch/packed" "$output/logs"
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
base=457be917b46c4fb6237831baac5abb848ffe1c4b
checkout_commit=$(git rev-parse HEAD)
checkout_tree=$(git rev-parse "$checkout_commit^{tree}")

# 独立索引捕获并重放源码，临时对象目录保留真实 Git 对象库。
export GIT_INDEX_FILE="$scratch/index"
export GIT_OBJECT_DIRECTORY="$scratch/objects"
export GIT_ALTERNATE_OBJECT_DIRECTORIES="$common_git_dir/objects"
run "$output/logs/read-tree.log" git read-tree "$checkout_commit"
run "$output/logs/add-source.log" git add --all -- .
run "$output/logs/write-tree.log" git write-tree
tree=$(cat "$output/logs/write-tree.log")
run "$output/source.patch" git diff --cached --no-color --no-ext-diff --no-textconv --full-index --binary "$base"
run "$output/logs/archive.log" git archive --format=tar --output="$scratch/source.tar" "$tree"
run "$output/logs/extract.log" tar -xf "$scratch/source.tar" -C "$scratch/source"
export GIT_INDEX_FILE="$scratch/replay-index"
run "$output/logs/replay-read-tree.log" git read-tree "$base"
if [[ -s "$output/source.patch" ]]; then
    run "$output/logs/replay-apply.log" git -c apply.whitespace=nowarn apply --cached "$output/source.patch"
fi
run "$output/logs/replay-tree.log" git write-tree
if [[ "$(cat "$output/logs/replay-tree.log")" != "$tree" ]]; then
    echo "源码补丁重放未得到候选树 $tree。" >&2
    exit 1
fi
unset GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES
run "$output/logs/entry-match.log" cmp "$framework/nupkg/pack-r3-leaf-candidates.sh" "$scratch/source/nupkg/pack-r3-leaf-candidates.sh"

source_commit=
if [[ "$tree" == "$checkout_tree" ]]; then
    source_commit=$checkout_commit
fi
proof="$output/du-r3-candidate-source.json"
cd "$scratch/source"
verify=(python3 -B nupkg/verify-r3-leaf-candidates.py)
run "$proof" "${verify[@]}" source "$base" "$tree" "$source_commit" "$output/source.patch"
run "$output/logs/r2-core-input.log" "${verify[@]}" prepare "$r2_feed" "$output" "$scratch/r2-core"
dotnet=$(command -v dotnet)
run "$output/logs/sdk.txt" "$dotnet" --version
sdk=$(cat "$output/logs/sdk.txt")
if [[ "$sdk" != 10.0.404 ]]; then
    echo "候选打包需要 SDK 10.0.404，实际为 $sdk。" >&2
    exit 1
fi
run "$output/logs/dotnet-info.txt" "$dotnet" --info

# 版本分配与输出位置无关。输入校验失败时尚未分配版本。
version_record="$common_git_dir/du-r3-leaf-candidate-versions/$version"
mkdir -p "$(dirname "$version_record")"
if ! mkdir "$version_record"; then
    echo "候选版本已分配或无法分配：$version_record" >&2
    exit 2
fi
cp "$proof" "$version_record/source.json"
printf '%s\n' "$output" > "$version_record/output.txt"

export NUGET_PACKAGES="$scratch/packages"
export NUGET_HTTP_CACHE_PATH="$scratch/http-cache"
export MSBUILDDISABLENODEREUSE=1
printf 'NUGET_PACKAGES=%q\nNUGET_HTTP_CACHE_PATH=%q\nMSBUILDDISABLENODEREUSE=1\n' "$NUGET_PACKAGES" "$NUGET_HTTP_CACHE_PATH" >> "$commands"
properties=(-p:Configuration=Release -p:DuR3CandidatePack=true
    "-p:DuR3CandidatePackageVersion=$version"
    "-p:DuR3CandidateSourceProof=$proof"
    "-p:DuR3CandidateCommit=$source_commit")
for name in Abp.AspNetCore.SignalR Abp.Castle.Log4Net; do
    project="src/$name/$name.csproj"
    run "$output/logs/$name.net9.0.json" "$dotnet" msbuild "$project" -nologo "${properties[@]}"         -getProperty:PackageId,PackageVersion,Version,AssemblyName,RootNamespace,TargetFramework,TargetPath,GeneratePackageOnBuild,IsPackable,RepositoryUrl,RepositoryCommit,IncludeSymbols,SymbolPackageFormat         -getItem:ProjectReference,PackageReference,FrameworkReference
    run "$output/logs/$name.restore.log" "$dotnet" restore "$project" "${properties[@]}"         --configfile "$output/NuGet.Config" --no-http-cache --disable-build-servers
    cp "src/$name/obj/project.assets.json" "$output/logs/$name.project.assets.json"
    run "$output/logs/$name.r2-core.json" "${verify[@]}" assets "$name" "$output" "$scratch/r2-core" "$NUGET_PACKAGES"
    run "$output/logs/$name.pack.log" "$dotnet" pack "$project" "${properties[@]}"         --no-restore -c Release --disable-build-servers -p:UseSharedCompilation=false         --verbosity normal --output "$scratch/packed"
    run "$output/logs/$name.compiler.json" "${verify[@]}" compiler "$name" "$output"
done

run "$output/logs/package-check.log" "${verify[@]}" finish "$version" "$sdk" "$output" "$scratch/packed"
cp "$output/manifest.json" "$version_record/manifest.json"
printf '候选源 %s/feed\n候选清单 %s/manifest.json\n' "$output" "$output"
