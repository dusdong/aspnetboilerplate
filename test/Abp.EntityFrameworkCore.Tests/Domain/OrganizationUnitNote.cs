using Abp.Domain.Entities;

namespace Abp.EntityFrameworkCore.Tests.Domain;

public class OrganizationUnitNote : Entity
{
    public int? OrganizationUnitId { get; set; }

    public string Title { get; set; }
}
