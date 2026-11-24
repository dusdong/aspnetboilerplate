using System.IO;
using System.Linq;
using Abp.AspNetCore.EmbeddedResources;
using Microsoft.AspNetCore.Mvc.Razor.RuntimeCompilation;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Options;
using Shouldly;
using Xunit;

namespace Abp.AspNetCore.Tests;

public class EmbeddedRazorView_Tests : AppTestBase
{
    [Fact]
    public void Should_Read_Embedded_View_From_Registered_Razor_File_Provider()
    {
#pragma warning disable ASPDEPR003
        var options = ServiceProvider.GetRequiredService<IOptions<MvcRazorRuntimeCompilationOptions>>().Value;
#pragma warning restore ASPDEPR003
        var provider = options.FileProviders.OfType<EmbeddedResourceViewFileProvider>().ShouldHaveSingleItem();
        var file = provider.GetFileInfo("/Views/EmbeddedView.cshtml");

        file.Exists.ShouldBeTrue();
        using var reader = new StreamReader(file.CreateReadStream());
        reader.ReadToEnd().Trim().ShouldBe("<p>Embedded Razor view</p>");
    }
}
