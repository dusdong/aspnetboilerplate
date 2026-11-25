#!/bin/bash
set -euo pipefail

usage() {
    echo '用法：bash nupkg/pack-r3-automapper-candidate.sh <10.5.1-r3.N> <引擎 nupkg> <引擎 SHA-256> <Collection nupkg> <Collection SHA-256> <R2 Du.Abp nupkg> <新输出目录>' >&2
    exit 2
}

[[ $# -eq 7 && "$1" =~ ^10[.]5[.]1-r3[.]([1-9][0-9]*)$ ]] || usage
version=$1
batch=${BASH_REMATCH[1]}
engine_version="14.0.0-r3.$batch"
collection_version="11.0.0-r3.$batch"
source=$(cd "$(dirname "$0")/.." && pwd -P)
dotnet=${DOTNET:-dotnet}
r2="$source/nupkg/r3-r2-core.json"
read -r core_name core_sha < <(python3 -c '
import json, sys
with open(sys.argv[1]) as config:
    data = json.load(config)
print(data["archiveFile"], data["archiveSha256"])
' "$r2")

check_input() {
    local file=$1 expected_name=$2 expected_sha=$3 actual_sha
    [[ -f "$file" && "${file##*/}" == "$expected_name" && "$expected_sha" =~ ^[a-f0-9]{64}$ ]] || usage
    actual_sha=$(shasum -a 256 < "$file")
    if [[ "${actual_sha%% *}" != "$expected_sha" ]]; then
        echo "依赖包 SHA-256 不符：$file" >&2
        exit 1
    fi
}

check_input "$2" "Du.AutoMapper.$engine_version.nupkg" "$3"
check_input "$4" "Du.AutoMapper.Collection.$collection_version.nupkg" "$5"
check_input "$6" "$core_name" "$core_sha"
mkdir -- "$7"
output=$(cd "$7" && pwd -P)
trap 'printf "%s\n" "$?" > "$output/exit-code.txt"' EXIT
mkdir "$output/inputs" "$output/logs" "$output/packed"
cp -- "$2" "$4" "$6" "$output/inputs/"
cd "$output"
cp "$source/global.json" global.json
cat > NuGet.Config <<'EOF'
<configuration>
  <packageSources>
    <clear />
    <add key="inputs" value="./inputs" />
    <add key="nuget.org" value="https://api.nuget.org/v3/index.json" />
  </packageSources>
  <packageSourceMapping>
    <packageSource key="inputs">
      <package pattern="Du.Abp" />
      <package pattern="Du.AutoMapper" />
      <package pattern="Du.AutoMapper.Collection" />
    </packageSource>
    <packageSource key="nuget.org"><package pattern="*" /></packageSource>
  </packageSourceMapping>
</configuration>
EOF

export NUGET_PACKAGES="$output/packages" NUGET_HTTP_CACHE_PATH="$output/http-cache" DOTNET_CLI_HOME="$output/dotnet-home"
export DOTNET_CLI_UI_LANGUAGE=en DOTNET_NOLOGO=1 DOTNET_CLI_TELEMETRY_OPTOUT=1 MSBUILDDISABLENODEREUSE=1
run() {
    local label=$1 rc=0
    shift
    printf '%q ' "$@" >> commands.log
    printf '> %s\n' "logs/$label.log" >> commands.log
    "$@" > "logs/$label.log" 2>&1 || rc=$?
    printf '退出码 %s\n' "$rc" >> commands.log
    if [[ "$rc" -ne 0 ]]; then
        tail -n 30 "logs/$label.log" >&2
    fi
    return "$rc"
}

project="$source/src/Abp.AutoMapper/Abp.AutoMapper.csproj"
properties=(-p:Configuration=Release -p:UseSharedCompilation=false "-p:ArtifactsPath=$output/artifacts"
    -p:DuR3AutoMapperCandidate=true "-p:DuR3AutoMapperCandidateVersion=$version"
    "-p:DuR3AutoMapperEngineVersion=$engine_version" "-p:DuR3AutoMapperCollectionVersion=$collection_version")
run sdk "$dotnet" --info
run restore "$dotnet" restore "$project" "${properties[@]}" --configfile "$output/NuGet.Config" --disable-build-servers
run build "$dotnet" build "$project" "${properties[@]}" --no-restore --disable-build-servers --verbosity normal "-bl:$output/build.binlog"
run pack "$dotnet" pack "$project" "${properties[@]}" --no-build --no-restore --disable-build-servers \
    --output "$output/packed" "-bl:$output/pack.binlog"

package="Du.Abp.AutoMapper.$version"
test -f "packed/$package.nupkg" && test -f "packed/$package.snupkg"
mkdir feed symbols
mv "packed/$package.nupkg" feed/
mv "packed/$package.snupkg" symbols/
shasum -a 256 "feed/$package.nupkg" "symbols/$package.snupkg" inputs/*.nupkg > packages.sha256
