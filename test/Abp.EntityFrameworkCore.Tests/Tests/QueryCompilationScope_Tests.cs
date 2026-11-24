using System;
using System.Linq.Expressions;
using Abp.EntityFrameworkCore.Tests.Ef;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.EntityFrameworkCore.Query;
using Microsoft.EntityFrameworkCore.Storage;
using NSubstitute;
using Shouldly;
using Xunit;

namespace Abp.EntityFrameworkCore.Tests.Tests;

public class QueryCompilationScope_Tests
{
    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void Should_Require_Independent_Filter_Context_For_Nested_Compilation(bool async)
    {
        using var db = new QueryCacheDbContext(new DbContextOptionsBuilder<QueryCacheDbContext>().Options);
        var current = new AbpEfCoreCurrentDbContext();
        var providerDatabase = Substitute.For<IDatabase>();
        var efCurrentContext = Substitute.For<ICurrentDbContext>();
        efCurrentContext.Context.Returns(db);
        var guardedDatabase = new AbpEfCoreDatabase(providerDatabase, current, efCurrentContext);
        var outer = Expression.Constant(1);
        var nested = Expression.Constant(2);
        Func<QueryContext, int> outerPlan = _ => 1;

        // 提供程序替身只模拟过滤翻译需要上下文的契约。
        providerDatabase.CompileQuery<int>(nested, async).Returns(_ =>
        {
            current.Context.ShouldBeNull();
            current.GetRequiredContext();
            return queryContext => throw new InvalidOperationException("嵌套编译未拒绝缺失的上下文。");
        });
        providerDatabase.CompileQuery<int>(outer, async).Returns(_ =>
        {
            current.GetRequiredContext().ShouldBeSameAs(db);
            var exception = Should.Throw<AbpException>(() => guardedDatabase.CompileQuery<int>(nested, async));
            exception.Message.ShouldContain(nameof(EF.CompileQuery));
            current.GetRequiredContext().ShouldBeSameAs(db);
            return outerPlan;
        });

        using (current.BeginQuery(db))
        {
            current.AuthorizeQueryCompilation(db, outer);
            guardedDatabase.CompileQuery<int>(outer, async).ShouldBeSameAs(outerPlan);
        }

        current.Context.ShouldBeNull();
    }
}
