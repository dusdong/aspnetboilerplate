using Abp.Domain.Entities;

namespace Abp.EntityFrameworkCore.Tests.Domain;

public class PublicQueryNote : Entity
{
    public string Title { get; set; }
}
