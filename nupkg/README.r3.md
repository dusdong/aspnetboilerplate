# R3 SignalR 与 Log4Net 本地候选包

在框架 Git 检出的根目录运行。需要 Bash、Git、Python 3.9 或更新版本，以及 `global.json` 锁定的 .NET SDK `10.0.404`。先确定源码和未分配的候选版本，准备原 R2 本地源中的 `Du.Abp.10.5.1-r2.1.nupkg`，再指定源码目录之外的新工件目录。

```sh
PATH="/绝对路径/SDK目录:$PATH" bash nupkg/pack-r3-leaf-candidates.sh \
  --version 10.5.1-r3.1 --r2-feed /绝对路径/R2/feed --output /绝对路径/R3候选目录
```

脚本用独立索引捕获当前源码，包括 Git 可见的未跟踪文件。临时对象目录保存候选树，在隔离目录物化该树，并核对从固定框架基线重放的树。已提交的候选也记录实际提交。候选模式在 SignalR 与 Log4Net 的两个项目显式启用，沿用各自的 `net9.0`、程序集和根命名空间。普通模式使用原项目引用和包身份。

生产者按 `r3-r2-core.json` 校验 R2 归档与 `lib/net9.0/Abp.dll`，仅向独占的本地源复制原核心归档。第三方包从 nuget.org 获取。脚本使用新的 NuGet 缓存，核对实际还原的核心资产后，以同一配置和缓存执行 Release pack，并从实际 Csc 命令中核对该 DLL 的引用和摘要。

- `feed/` 保存两份 `.nupkg`，`symbols/` 保存对应的两份 `.snupkg`。消费复验直接使用这批原件。
- `manifest.json` 记录版本、SDK、R2 输入登记、源码树和包、DLL、PDB 的 SHA-256，以及逐项目的证据路径和摘要。
- `du-r3-candidate-source.json` 同时保存在该目录和两份候选包内。用独立 Git 索引从其中的 `baseCommit` 重放 `source.patch`，再将 `git write-tree` 结果与登记的 `tree` 比较。
- `NuGet.Config`、`commands.log` 和 `logs/` 保存实际源映射、命令、退出码、项目求值、还原资产、核心缓存元数据、编译引用及实际 nuspec。临时缓存和源码在脚本退出后清理。

输入核对成功后，脚本会在框架 Git 公共目录的 `du-r3-leaf-candidate-versions/` 原子分配版本。如果后续生产失败，保留已有证据并递增版本号。已生成批次的源码、依赖或包字节有变动时同样分配新版本，原批次继续用于对应的消费复验。
