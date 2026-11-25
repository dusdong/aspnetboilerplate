# R3 AutoMapper 适配器候选

候选保留 `net9.0`、`Abp.AutoMapper` 程序集和 `Abp` 根命名空间。候选显式从包引用固定 R2 内核和本批两份映射上游。普通入口沿用 `Abp` 项目引用、两份原版映射包以及 `Abp.AutoMapper` 包名。

在框架源码根目录使用 SDK `10.0.404`。从主仓批次分配记录确定版本，从各已冻结主包清单取得 `ENGINE_SHA256`、`COLLECTION_SHA256`，并把 `OUT` 指向尚不存在的目录。

```sh
bash nupkg/pack-r3-automapper-candidate.sh 10.5.1-r3.4 \
  "$ENGINE_NUPKG" "$ENGINE_SHA256" "$COLLECTION_NUPKG" "$COLLECTION_SHA256" \
  "$R2_CORE_NUPKG" "$OUT"
```

入口从 `nupkg/r3-r2-core.json` 取得 R2 原包的固定归档摘要。隔离缓存只从本地输入源还原三个维护包，实际 Release 编译后从同一输出生成主包和符号包。证据目录保留 `feed/`、`symbols/`、实际还原图、编译和打包日志及 SHA-256。复跑沿用已分配的同批输入并使用新目录。

普通源码验证在 SDK `10.0.404` 与 .NET 9 上运行。使用单独的输出目录保存包和 TRX。

```sh
dotnet build src/Abp.AutoMapper/Abp.AutoMapper.csproj -c Release
dotnet pack src/Abp.AutoMapper/Abp.AutoMapper.csproj -c Release --no-build -o "$ORDINARY_PACKAGES"
dotnet test test/Abp.AutoMapper.Tests/Abp.AutoMapper.Tests.csproj -c Release \
  --logger 'trx;LogFileName=abp-automapper.trx' --results-directory "$TEST_RESULTS"
```
