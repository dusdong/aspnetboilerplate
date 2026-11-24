using System.Linq;
using Abp.Domain.Repositories;
using Abp.Domain.Uow;
using Abp.EntityFrameworkCore.Repositories;
using Abp.EntityFrameworkCore.Tests.Domain;
using Abp.EntityFrameworkCore.Tests.Ef;
using Abp.Modules;
using Abp.TestBase;
using Microsoft.EntityFrameworkCore;
using Shouldly;
using Xunit;

namespace Abp.EntityFrameworkCore.Tests.Tests;

public class SoftDeleteValueConverter_WithoutAbpQueryCompiler_Tests
    : SoftDeleteValueConverter_Tests<CompiledQueryCacheWithoutAbpQueryCompilerTestModule>
{
}

public class SoftDeleteValueConverter_WithAbpQueryCompiler_Tests
    : SoftDeleteValueConverter_Tests<CompiledQueryCacheWithAbpQueryCompilerTestModule>
{
}

[Collection("Clock.Provider")]
public abstract class SoftDeleteValueConverter_Tests<TStartupModule> : AbpIntegratedTestBase<TStartupModule>
    where TStartupModule : AbpModule
{
    [Fact]
    public void Should_Apply_SoftDelete_Filter_To_Converted_Column()
    {
        using (var db = Resolve<IDbContextResolver>().Resolve<QueryCacheDbContext>(null, null))
        {
            db.IntSoftDeleteNotes.AddRange(
                new IntSoftDeleteNote { Id = 10, Title = "first" },
                new IntSoftDeleteNote { Id = 20, Title = "second" },
                new IntSoftDeleteNote { Id = 30, Title = "removed", IsDeleted = true }
            );
            db.SaveChanges();

            db.Database.SqlQueryRaw<int>("SELECT IsDeleted FROM IntSoftDeleteNotes ORDER BY Id").ToArray()
                .ShouldBe(new[] { IntSoftDeleteNote.NotDeletedValue, IntSoftDeleteNote.NotDeletedValue, IntSoftDeleteNote.DeletedValue });
        }

        var unitOfWorkManager = Resolve<IUnitOfWorkManager>();
        using var uow = unitOfWorkManager.Begin();
        var dbContext = (QueryCacheDbContext)Resolve<IRepository<IntSoftDeleteNote>>().GetDbContext();
        var notes = dbContext.IntSoftDeleteNotes.OrderBy(note => note.Id).Select(note => note.Id);
        notes.ToArray().ShouldBe(new[] { 10, 20 });

        using (unitOfWorkManager.Current.DisableFilter(AbpDataFilters.SoftDelete))
        {
            notes.ToArray().ShouldBe(new[] { 10, 20, 30 });
        }

        uow.Complete();
    }
}
