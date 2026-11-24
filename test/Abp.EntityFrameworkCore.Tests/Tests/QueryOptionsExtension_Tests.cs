using System;
using System.Linq;
using Abp.EntityFrameworkCore.Extensions;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.EntityFrameworkCore.Query;
using Microsoft.EntityFrameworkCore.Storage;
using Microsoft.Extensions.DependencyInjection;
using Shouldly;
using Xunit;

namespace Abp.EntityFrameworkCore.Tests.Tests;

public class QueryOptionsExtension_Tests
{
    [Fact]
    public void Should_Reject_Database_Replacement_When_Extension_Is_Enabled()
    {
        var options = new DbContextOptionsBuilder()
            .UseSqlite("Data Source=:memory:")
            .ReplaceService<IDatabase, CustomRelationalDatabase>()
            .AddAbpDbContextOptionsExtension()
            .Options;

        ShouldRejectServiceReplacement(options);
    }

    [Fact]
    public void Should_Reject_Cache_Key_Replacement_When_Extension_Is_Enabled()
    {
        var options = new DbContextOptionsBuilder()
            .UseSqlite("Data Source=:memory:")
            .ReplaceService<ICompiledQueryCacheKeyGenerator, RelationalCompiledQueryCacheKeyGenerator>()
            .AddAbpDbContextOptionsExtension()
            .Options;

        ShouldRejectServiceReplacement(options);
    }

    [Fact]
    public void Should_Keep_InMemory_Provider_Database_Service()
    {
        var options = new DbContextOptionsBuilder()
            .UseInMemoryDatabase(Guid.NewGuid().ToString())
            .AddAbpDbContextOptionsExtension()
            .Options;

        using var db = new DbContext(options);
        db.GetService<IDatabase>().ShouldNotBeOfType<AbpEfCoreDatabase>();
        db.Database.EnsureCreated().ShouldBeTrue();
        db.Database.EnsureDeleted().ShouldBeTrue();
    }

    [Fact]
    public void Should_Apply_Registrations_Once_After_Provider_Is_Added()
    {
        var services = new ServiceCollection();
        var extension = new AbpDbContextOptionsExtension();
        extension.ApplyServices(services);
        services.AddEntityFrameworkSqlite();
        extension.ApplyServices(services);
        extension.ApplyServices(services);

        services.Count(service => service.ServiceType == typeof(IDatabase) && service.IsKeyedService).ShouldBe(1);
        services.Count(service => service.ServiceType == typeof(ICompiledQueryCacheKeyGenerator) && service.IsKeyedService).ShouldBe(1);
        services.Count(service => service.ServiceType == typeof(AbpEfCoreCurrentDbContext)).ShouldBe(1);
    }

    private static void ShouldRejectServiceReplacement(DbContextOptions options)
    {
        var exception = Should.Throw<AbpException>(() =>
        {
            using var db = new DbContext(options);
            _ = db.Model;
        });

        exception.Message.ShouldContain("ReplaceService");
    }
}

public class CustomRelationalDatabase : RelationalDatabase
{
    public CustomRelationalDatabase(DatabaseDependencies dependencies, RelationalDatabaseDependencies relationalDependencies)
        : base(dependencies, relationalDependencies)
    {
    }
}
