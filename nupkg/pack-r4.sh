#!/bin/bash
set -euo pipefail

usage() {
    printf '%s\n' '用法：bash nupkg/pack-r4.sh framework <新输出目录>' \
        '      bash nupkg/pack-r4.sh {automapper|automapper-r5} <新输出目录> <Du.Abp 主包> <Du.AutoMapper 主包> <Du.AutoMapper.Collection 主包>' >&2
    exit 2
}

case "${1:-}" in
    framework) [[ $# -eq 2 ]] || usage ;;
    automapper|automapper-r5) [[ $# -eq 5 ]] || usage ;;
    *) usage ;;
esac

source=$(cd "$(dirname "$0")/.." && pwd -P)
if [[ "$1" != automapper-r5 && -n "$(git -C "$source" status --porcelain=v1 --untracked-files=all)" ]]; then
    echo 'R4 需要干净的生产提交。' >&2
    exit 1
fi
commit=$(git -C "$source" rev-parse HEAD)
dotnet=${DOTNET:-dotnet}
mkdir -- "$2"
output=$(cd "$2" && pwd -P)
trap 'printf "%s\n" "$?" > "$output/exit-code.txt"' EXIT
mkdir "$output/feed" "$output/symbols" "$output/logs" "$output/packed" "$output/readmes"
version=10.5.1
patch_properties=()
if [[ "$1" != framework ]]; then
    mkdir "$output/inputs"
    expected=(Du.Abp.10.5.1.nupkg Du.AutoMapper.14.0.0.nupkg Du.AutoMapper.Collection.11.0.0.nupkg)
    if [[ "$1" == automapper-r5 ]]; then
        version=10.5.2
        patch_properties=(-p:DuR5AutoMapperPack=true)
        expected=(Du.Abp.10.5.1.nupkg Du.AutoMapper.14.0.1.nupkg Du.AutoMapper.Collection.11.0.1.nupkg)
    fi
    index=0
    for archive in "${@:3}"; do
        [[ -f "$archive" && "${archive##*/}" == "${expected[$index]}" ]] || usage
        cp -- "$archive" "$output/inputs/"
        index=$((index + 1))
    done
    (cd "$output"; shasum -a 256 inputs/*.nupkg > inputs.sha256)
    package_source=./inputs
else
    package_source=./feed
fi

cd "$output"
cp "$source/global.json" .
cat > NuGet.Config <<EOF
<configuration>
  <packageSources>
    <clear />
    <add key="candidate" value="$package_source" />
    <add key="nuget.org" value="https://api.nuget.org/v3/index.json" />
  </packageSources>
  <packageSourceMapping>
    <packageSource key="candidate"><package pattern="Du.*" /></packageSource>
    <packageSource key="nuget.org"><package pattern="*" /></packageSource>
  </packageSourceMapping>
  <fallbackPackageFolders><clear /></fallbackPackageFolders>
</configuration>
EOF
printf '%s\n' "$commit" > source-commit.txt
export NUGET_PACKAGES="$output/packages" NUGET_HTTP_CACHE_PATH="$output/http-cache" DOTNET_CLI_HOME="$output/dotnet-home"
export DOTNET_CLI_UI_LANGUAGE=en DOTNET_NOLOGO=1 DOTNET_CLI_TELEMETRY_OPTOUT=1 MSBUILDDISABLENODEREUSE=1

run() {
    local label=$1 rc=0
    shift
    printf '%q ' "$@" >> commands.log
    printf '> logs/%s.log\n' "$label" >> commands.log
    "$@" > "logs/$label.log" 2>&1 || rc=$?
    printf '退出码 %s\n' "$rc" >> commands.log
    if [[ "$rc" -ne 0 ]]; then
        tail -n 30 "logs/$label.log" >&2
    fi
    return "$rc"
}

pack() {
    local project=$1
    local package="Du.$project"
    local project_file="$source/src/$project/$project.csproj"
    local readme="$output/readmes/$project/README.md"
    local properties=(-p:Configuration=Release -p:UseSharedCompilation=false "-p:ArtifactsPath=$output/artifacts"
        -p:DuR4Pack=true "-p:DuR4Readme=$readme" "-p:RepositoryCommit=$commit")
    if [[ ${#patch_properties[@]} -gt 0 ]]; then
        properties+=("${patch_properties[@]}")
    fi
    mkdir "$(dirname "$readme")"
    sed -e "s/@PACKAGE@/$package/g" -e "s/10\.5\.1/$version/g" "$source/nupkg/README.r4-package.md" > "$readme"
    run "$project-restore" "$dotnet" restore "$project_file" "${properties[@]}" \
        --configfile "$output/NuGet.Config" --disable-build-servers
    run "$project-build" "$dotnet" build "$project_file" "${properties[@]}" \
        --no-restore --disable-build-servers --verbosity normal
    run "$project-pack" "$dotnet" pack "$project_file" "${properties[@]}" \
        --no-build --no-restore --disable-build-servers --output "$output/packed"
    mv -- "packed/$package.$version.nupkg" feed/
    mv -- "packed/$package.$version.snupkg" symbols/
}

run sdk "$dotnet" --info
if [[ "$1" == framework ]]; then
    for project in Abp Abp.Web.Common Abp.AspNetCore Abp.EntityFramework.Common Abp.EntityFrameworkCore \
                   Abp.AspNetCore.SignalR Abp.Castle.Log4Net Abp.Zero.Common Abp.ZeroCore Abp.ZeroCore.EntityFrameworkCore; do
        pack "$project"
    done
else
    pack Abp.AutoMapper
fi
shasum -a 256 feed/*.nupkg symbols/*.snupkg > packages.sha256
