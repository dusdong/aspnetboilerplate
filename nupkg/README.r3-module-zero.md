# R3 Module Zero 本地候选包

从框架 Git 检出运行。环境需要 Bash、Git、Python 3.9 或更新版本，以及 `global.json` 锁定的 .NET SDK `10.0.404`。选择尚未分配的 R3 版本，准备带有原生产清单、补丁及源码证明的 R2 批次目录。将输出指定在框架源码目录之外的新空目录。

```sh
PATH="/绝对路径/SDK目录:$PATH" bash nupkg/pack-r3-module-zero-candidates.sh \
  --version 10.5.1-r3.2 --r2-feed /绝对路径/R2批次/feed --output /绝对路径/R3候选目录
```

入口按下表顺序还原并打包。候选模式将四条原项目引用替换为精确包引用。普通模式继续使用原项目引用、包 ID 和 Release 自动打包。三项目均保留 `net9.0`、程序集身份和根命名空间。

| 项目 | 候选包 | 候选直接框架依赖 |
| --- | --- | --- |
| `Abp.Zero.Common` | `Du.Abp.Zero.Common` | `Du.Abp [10.5.1-r2.1]` |
| `Abp.ZeroCore` | `Du.Abp.ZeroCore` | `Du.Abp.Zero.Common [当轮版本]` |
| `Abp.ZeroCore.EntityFrameworkCore` | `Du.Abp.ZeroCore.EntityFrameworkCore` | `Du.Abp.ZeroCore [当轮版本]`、`Du.Abp.EntityFrameworkCore [10.5.1-r2.1]` |

生产者核对原 R2 清单、补丁重放、包内源码证明、三份归档与各自的 `net9.0` DLL。构建在临时目录物化框架源树，从空 NuGet 包缓存和 HTTP 缓存开始。每步使用映射到本地源的框架归档及 nuget.org 上的第三方包。产出的主包和符号包通过检查后，主包原字节进入同批源。后续项目使用实际还原选中的框架 DLL 编译。

- `feed/` 保存三个正式主包，`symbols/` 保存三个配套符号包。只有全部步骤成功才生成 `manifest.json`。消费复验使用清单和对应的冻结归档。
- `du-r3-candidate-source.json` 同时保存在候选目录和每个主包内。用独立 Git 索引对 `baseCommit` 应用 `source.patch` 后，可核对 `baseTree`、补丁摘要和写出的 `tree`。清单也登记框架检出及可取得的主仓 gitlink。
- `logs/`、`commands.log` 与 `NuGet.Config` 保存求值、还原图、缓存来源、Csc 引用、nuspec 及构建命令等证据。执行结束后清理本次临时物化和缓存。

输入预检后，在框架 Git 公共目录的 `du-r3-leaf-candidate-versions/` 原子分配序号，该目录与 SignalR、Log4Net 入口共用。保留失败批次的分配和日志。重新生产时选择下一未分配版本和新输出目录，保留已冻结实物。
