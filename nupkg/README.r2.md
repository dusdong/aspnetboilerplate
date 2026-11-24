# R2 本地核心候选包

从框架 Git 检出的根目录运行，使用 Bash、Git、Python 3 和 `global.json` 固定的 SDK `10.0.404`。先确定检出中的源码和新候选序号，再指定框架目录以外的新工件目录。

```sh
bash nupkg/pack-r2-candidates.sh --version 10.5.1-r2.1 --output /绝对路径/候选目录
```

入口使用独立索引捕获当前 Git 可见的完整源码，包括未跟踪的源码文件。在临时目录从该树物化源码，以空包缓存和 nuget.org 还原，按项目依赖顺序通过 SDK 打包。五个包统一采用预发布 `PackageVersion`，保留源码项目引用、`net9.0` 和 `net10.0`、原程序集版本及命名空间。普通构建和原 `pack.ps1` 继续使用原包身份。候选模式通过 `DuCoreCandidatePack` 和 `DuCoreCandidatePackageVersion` 在五个项目的引用图上显式启用。

- `feed/` 为五个 `.nupkg` 的本地源，`symbols/` 保存对应的五个 `.snupkg`。
- `manifest.json` 记录版本、SDK、仓库、来源、还原入口和各包、DLL、PDB 的 SHA-256。实际命令、退出码、两目标 MSBuild 求值和项目还原图保留在 `commands.log`、`logs/` 和 `NuGet.Config`。
- `du-core-candidate-source.json` 同时保存在外部目录和每个包。未提交的候选以基线提交、候选树和完整二进制补丁摘要标识。已提交的候选也记录精确提交，nuspec 的仓库 commit 使用同一提交。两种情况均从隔离物化目录构建，其源码来源以包内记录为准。
- 开始还原前将该版本分配记录写入框架 Git 公共目录的 `du-core-candidate-versions/`。若生成中断，保留日志并为下一轮递增版本序号、指定新目录。其他检出也应沿用项目已分配的版本编号。

如需独立核对未提交候选的源码树，可以从框架根目录用新的临时索引回放补丁。以下命令中的 `candidate` 指原候选工件目录，`base` 取自来源记录的 `baseCommit`。

```sh
tmp=$(mktemp -d)
export GIT_INDEX_FILE="$tmp/index"
git read-tree "$base"
git apply --cached "$candidate/source.patch"
git write-tree
unset GIT_INDEX_FILE
rm -rf "$tmp"
```

将输出与来源记录的 `tree` 比较。使用另一个候选版本生成后续包。已验证候选可直接从原 `feed/` 和 `manifest.json` 复跑消费验收。
