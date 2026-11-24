using System;
using System.Linq.Expressions;
using Abp.EntityFrameworkCore.Tests.Domain;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.EntityFrameworkCore.Query.SqlExpressions;

namespace Abp.EntityFrameworkCore.Tests.Ef;

public class QueryCacheDbContext : AbpDbContext
{
    public const string OrganizationUnitFilterName = "MayHaveOrganizationUnit";

    public DbSet<TenantNote> TenantNotes { get; set; }

    public DbSet<TenantOrder> TenantOrders { get; set; }

    public DbSet<TenantMemo> TenantMemos { get; set; }

    public DbSet<IntSoftDeleteNote> IntSoftDeleteNotes { get; set; }

    public DbSet<OrganizationUnitNote> OrganizationUnitNotes { get; set; }

    public DbSet<PublicQueryNote> PublicQueryNotes { get; set; }

    private int? CurrentOrganizationUnitId => 7;

    private bool IsOrganizationUnitFilterEnabled =>
        CurrentUnitOfWorkProvider?.Current?.IsFilterEnabled(OrganizationUnitFilterName) == true;

    public QueryCacheDbContext(DbContextOptions<QueryCacheDbContext> options)
        : base(options)
    {

    }

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        base.OnModelCreating(modelBuilder);

        modelBuilder.Entity<IntSoftDeleteNote>()
            .Property(note => note.IsDeleted)
            .HasConversion(
                isDeleted => isDeleted ? IntSoftDeleteNote.DeletedValue : IntSoftDeleteNote.NotDeletedValue,
                value => value == IntSoftDeleteNote.DeletedValue);

        if (!UseAbpQueryCompiler())
        {
            modelBuilder.Entity<OrganizationUnitNote>()
                .HasQueryFilter(note => !IsOrganizationUnitFilterEnabled || note.OrganizationUnitId == CurrentOrganizationUnitId);
            return;
        }

        var currentDbContext = this.GetService<AbpEfCoreCurrentDbContext>();
        modelBuilder.Entity<OrganizationUnitNote>()
            .HasQueryFilter(note => MayHaveOrganizationUnitFilter(note.OrganizationUnitId, CurrentOrganizationUnitId, true));
        modelBuilder.HasDbFunction(typeof(QueryCacheDbContext).GetMethod(nameof(MayHaveOrganizationUnitFilter))!)
            .HasTranslation(args =>
            {
                var organizationUnitId = args[0];
                var currentOrganizationUnitId = args[1];
                var boolParam = args[2];
                var db = (QueryCacheDbContext)currentDbContext.GetRequiredContext();

                return db.IsOrganizationUnitFilterEnabled
                    ? new SqlBinaryExpression(ExpressionType.Equal, organizationUnitId, currentOrganizationUnitId, boolParam.Type, boolParam.TypeMapping)
                    : new SqlConstantExpression(true, boolParam.Type, boolParam.TypeMapping);
            });
    }

    public override string GetCompiledQueryCacheKey() =>
        UseAbpQueryCompiler() ? $"{base.GetCompiledQueryCacheKey()}:{IsOrganizationUnitFilterEnabled}" : base.GetCompiledQueryCacheKey();

    public static bool MayHaveOrganizationUnitFilter(int? organizationUnitId, int? currentOrganizationUnitId, bool boolParam)
    {
        throw new NotSupportedException(DbFunctionNotSupportedExceptionMessage);
    }
}
