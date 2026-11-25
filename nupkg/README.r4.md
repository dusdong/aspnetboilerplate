# R4 维护版框架打包

在干净的生产提交使用仓库固定的 .NET SDK `10.0.404`。输出路径须尚未创建。每个入口使用自己的 NuGet 包缓存，将 `Du.*` 映射到本地包源。第三方依赖由 nuget.org 提供。

```sh
DOTNET="$DOTNET" bash nupkg/pack-r4.sh framework "$FRAMEWORK_OUT"
```

入口按依赖顺序生成十对主包和符号包。五个核心包为 `net9.0` 和 `net10.0`，SignalR、Log4Net 和三个 Module Zero 包为 `net9.0`。每次还原读取已生成的内部依赖实包，再复用 Release 编译结果打包。核心之间使用最低版本，集成包及 Module Zero 使用精确版本。

用同批框架、引擎和 Collection 主包生成映射适配器。确认输入摘要对应各生产入口的 `packages.sha256`。

```sh
DOTNET="$DOTNET" bash nupkg/pack-r4.sh automapper "$ADAPTER_OUT" \
    "$FRAMEWORK_OUT/feed/Du.Abp.10.5.1.nupkg" \
    "$ENGINE_OUT/feed/Du.AutoMapper.14.0.0.nupkg" \
    "$COLLECTION_OUT/feed/Du.AutoMapper.Collection.11.0.0.nupkg"
```

三个输入包复制到该次适配器生产的隔离本地源，摘要记录在 `inputs.sha256`。两个入口均输出 `feed/`、`symbols/`、生产提交、实际 SDK、命令、阶段日志、还原图及包摘要。普通构建和 R2、R3 候选仍沿用原有入口。
