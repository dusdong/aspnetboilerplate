"""核对 R3 打包的归档、还原产物、编译输入和包内容。"""

import hashlib
import json
from pathlib import Path
import shlex
import shutil
import sys
from xml.etree import ElementTree as ET
from zipfile import ZipFile


ASSEMBLIES = ("Abp.AspNetCore.SignalR", "Abp.Castle.Log4Net")
NUGET_ORG = "https://api.nuget.org/v3/index.json"
REPOSITORY = "https://github.com/dusdong/aspnetboilerplate.git"
PROOF = "du-r3-candidate-source.json"


def read_json(path):
    return json.loads(path.read_text())


def as_json(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def source(base, tree, commit, patch):
    result = {"baseCommit": base, "tree": tree, "patchSha256": sha256(Path(patch).read_bytes())}
    if commit:
        result["commit"] = commit
    print(as_json(result), end="")


def prepare(feed, output, local):
    feed, output, local = map(Path, (feed, output, local))
    core = read_json(Path(__file__).with_name("r3-r2-core.json"))
    archive_path = feed / core["archiveFile"]
    archive = archive_path.read_bytes()
    actual = sha256(archive)
    require(actual == core["archiveSha256"],
            f"{archive_path} 归档 SHA-256 不符，预期 {core['archiveSha256']}，实际 {actual}")
    local.mkdir()
    copied = local / archive_path.name
    copied.write_bytes(archive)
    with ZipFile(copied) as package:
        require(sha256(package.read(core["assetPath"])) == core["assetSha256"],
                f"{archive_path} 中的 {core['assetPath']} SHA-256 不符")
    (output / "r2-core-input.json").write_text(as_json({"archive": str(archive_path), **core}))

    config = ET.Element("configuration")
    sources = ET.SubElement(config, "packageSources")
    ET.SubElement(sources, "clear")
    ET.SubElement(sources, "add", key="r2-core", value=str(local))
    ET.SubElement(sources, "add", key="nuget.org", value=NUGET_ORG)
    mapping = ET.SubElement(config, "packageSourceMapping")
    ET.SubElement(mapping, "clear")
    ET.SubElement(ET.SubElement(mapping, "packageSource", key="r2-core"), "package", pattern=core["id"])
    ET.SubElement(ET.SubElement(mapping, "packageSource", key="nuget.org"), "package", pattern="*")
    ET.SubElement(ET.SubElement(config, "fallbackPackageFolders"), "clear")
    ET.indent(config)
    ET.ElementTree(config).write(output / "NuGet.Config", encoding="utf-8", xml_declaration=True)
    print(f"已验证 R2 归档和核心资产 {archive_path}")


def assets(name, output, local, cache):
    output, local, cache = map(Path, (output, local, cache))
    core = read_json(output / "r2-core-input.json")
    package_id, version, asset_path = core["id"], core["version"], core["assetPath"]
    package_key = f"{package_id}/{version}"
    path = output / "logs" / f"{name}.project.assets.json"
    data = read_json(path)
    project = data["project"]
    restore = project["restore"]
    require(set(data["targets"]) == {"net9.0"} and
            {Path(folder).resolve() for folder in data["packageFolders"]} == {cache.resolve()} and
            set(restore["sources"]) == {str(local), NUGET_ORG} and
            restore["configFilePaths"] == [str(output / "NuGet.Config")] and
            not restore["frameworks"]["net9.0"]["projectReferences"],
            f"{path} 的目标、全局缓存、还原源或项目引用不符")
    declared = project["frameworks"]["net9.0"]["dependencies"][package_id]
    require(declared["version"] == f"[{version}, {version}]" and "suppressParent" not in declared,
            f"{path} 中 {package_id} 须声明可传播的精确版本 {version}，实际 {declared}")
    target = data["targets"]["net9.0"]
    require([key for key in target if key.split("/")[0].lower() in ("abp", "du.abp")] == [package_key],
            f"{path} 中的框架核心来源应为 {package_key}")
    library = data["libraries"][package_key]
    require(library["type"] == target[package_key]["type"] == "package" and
            all(set(target[package_key][kind]) == {asset_path} for kind in ("compile", "runtime")),
            f"{path} 未选择 {package_key} 的 {asset_path}")
    core_cache = cache / library["path"]
    cache_metadata = core_cache / ".nupkg.metadata"
    metadata = read_json(cache_metadata)
    archive = core_cache / core["archiveFile"].lower()
    dll = (core_cache / asset_path).resolve()
    require(Path(metadata["source"]).resolve() == local.resolve() and
            metadata["contentHash"] == library["sha512"] ==
            (core_cache / f"{archive.name}.sha512").read_text().strip(),
            f"{cache_metadata} 的源或 NuGet 内容哈希不符")
    require(sha256(archive.read_bytes()) == core["archiveSha256"] and
            sha256(dll.read_bytes()) == core["assetSha256"],
            f"{archive} 或 {dll} 的 SHA-256 不符")
    shutil.copyfile(cache_metadata, output / "logs" / f"{name}.r2-core.nupkg.metadata")
    print(as_json({
        "id": package_id, "version": version,
        "declaredRange": declared["version"], "source": metadata["source"],
        "archive": str(archive), "archiveSha256": core["archiveSha256"],
        "nugetContentSha512": library["sha512"],
        "assetPath": asset_path, "asset": str(dll), "assetSha256": core["assetSha256"],
    }), end="")


def compiler(name, output):
    logs = Path(output) / "logs"
    core = read_json(logs / f"{name}.r2-core.json")
    log = logs / f"{name}.pack.log"
    invocations = [
        shlex.split(line)
        for line in log.read_text().splitlines()
        if "/noconfig " in line and f"/out:obj/Release/net9.0/{name}.dll" in line
    ]
    references = [
        str(Path(argument.removeprefix("/reference:")).resolve())
        for arguments in invocations for argument in arguments
        if argument.startswith("/reference:") and argument.endswith("/Abp.dll")
    ]
    require(len(invocations) == 1 and references == [core["asset"]],
            f"{log} 的 Csc 核心引用须为 {core['asset']}，实际 {references}")
    actual = sha256(Path(references[0]).read_bytes())
    require(actual == core["assetSha256"], f"Csc 引用 {references[0]} 的 SHA-256 不符")
    print(as_json({"project": name, "reference": references[0], "sha256": actual}), end="")


def nuspec(package, name, version, source_proof):
    nuspec_path = f"Du.{name}.nuspec"
    raw = package.read(nuspec_path)
    metadata = ET.fromstring(raw).find("{*}metadata")
    require(metadata.findtext("{*}id") == f"Du.{name}" and metadata.findtext("{*}version") == version,
            f"{nuspec_path} 的包 ID 或版本不符")
    repository = metadata.find("{*}repository").attrib
    expected = {"url": REPOSITORY, "type": "git"}
    if commit := source_proof.get("commit"):
        expected["commit"] = commit
    require(repository == expected, f"{nuspec_path} 的仓库来源不符：{repository}")
    groups = list(metadata.find("{*}dependencies"))
    dependencies = [(item.attrib["id"], item.attrib["version"]) for group in groups for item in group]
    expected_deps = [("Du.Abp", "[10.5.1-r2.1]")]
    if name == "Abp.Castle.Log4Net":
        expected_deps.append(("log4net", "3.3.2"))
    require(len(groups) == 1 and groups[0].attrib["targetFramework"] == "net9.0" and
            sorted(dependencies) == sorted(expected_deps), f"{nuspec_path} 的依赖组不符：{dependencies}")
    framework_groups = metadata.findall("{*}frameworkReferences/{*}group")
    frameworks = [
        (group.attrib["targetFramework"], entry.attrib["name"])
        for group in framework_groups for entry in group
    ]
    expected_frameworks = [("net9.0", "Microsoft.AspNetCore.App")] if name == ASSEMBLIES[0] else []
    require(frameworks == expected_frameworks, f"{nuspec_path} 的共享框架不符：{frameworks}")
    require(metadata.find("{*}license").attrib == {"type": "file"} and
            metadata.findtext("{*}license") == "LICENSE.md" and
            metadata.findtext("{*}icon") == "abp_nupkg.png", f"{nuspec_path} 的许可或图标声明不符")
    return raw


def finish(version, sdk, output, packed):
    output, packed = Path(output), Path(packed)
    logs = output / "logs"
    proof = (output / PROOF).read_bytes()
    source_proof = json.loads(proof)
    packages = {}
    production = {}
    for name in ASSEMBLIES:
        package_id = f"Du.{name}"
        package_file = f"{package_id}.{version}.nupkg"
        symbols_file = f"{package_id}.{version}.snupkg"
        evaluation = read_json(logs / f"{name}.net9.0.json")
        properties = evaluation["Properties"]
        require(properties["PackageId"] == package_id and properties["PackageVersion"] == version and
                properties["AssemblyName"] == name and properties["RootNamespace"] == "Abp" and
                properties["TargetFramework"] == "net9.0" and not evaluation["Items"]["ProjectReference"],
                f"{name} 的候选项目求值不符")
        build_dll = Path(properties["TargetPath"])
        dll_path, pdb_path = f"lib/net9.0/{name}.dll", f"lib/net9.0/{name}.pdb"
        package_path, symbols_path = packed / package_file, packed / symbols_file
        with ZipFile(package_path) as package, ZipFile(symbols_path) as symbols:
            raw = nuspec(package, name, version, source_proof)
            (logs / f"{name}.nuspec").write_bytes(raw)
            require(package.read(PROOF) == proof, f"{package_file} 的源码来源记录不一致")
            require(package.read("LICENSE.md") == Path("LICENSE.md").read_bytes() and
                    package.read("abp_nupkg.png") == Path("nupkg/abp_nupkg.png").read_bytes(),
                    f"{package_file} 的许可或图标与源码树不一致")
            lib = {entry for entry in package.namelist() if entry.startswith(("lib/", "ref/"))}
            require(lib == {dll_path, f"lib/net9.0/{name}.xml"} and
                    {entry for entry in symbols.namelist() if entry.startswith(("lib/", "ref/"))} == {pdb_path},
                    f"{package_file} 或 {symbols_file} 的库目标或文件不符")
            dll, pdb = package.read(dll_path), symbols.read(pdb_path)
            require(dll == build_dll.read_bytes() and pdb == build_dll.with_suffix(".pdb").read_bytes() and
                    pdb.startswith(b"BSJB"), f"{package_file} 或 {symbols_file} 与 Release 输出不符")
        packages[package_id] = {
            "assemblyName": name, "rootNamespace": properties["RootNamespace"],
            "package": {"file": package_file, "sha256": sha256(package_path.read_bytes())},
            "symbols": {"file": symbols_file, "sha256": sha256(symbols_path.read_bytes())},
            "targets": {"net9.0": {
                "path": dll_path, "sha256": sha256(dll), "pdbPath": pdb_path, "pdbSha256": sha256(pdb)
            }},
        }
        files = {
            "evaluation": f"{name}.net9.0.json", "assets": f"{name}.project.assets.json",
            "r2Core": f"{name}.r2-core.json", "r2CacheMetadata": f"{name}.r2-core.nupkg.metadata",
            "compiler": f"{name}.compiler.json", "packLog": f"{name}.pack.log",
            "restoreLog": f"{name}.restore.log", "nuspec": f"{name}.nuspec",
        }
        production[package_id] = {
            kind: {"path": f"logs/{file}", "sha256": sha256((logs / file).read_bytes())}
            for kind, file in files.items()
        }

    core = read_json(output / "r2-core-input.json")
    core.pop("archive")
    manifest = {
        "schemaVersion": 1, "version": version, "sdk": sdk, "repositoryUrl": REPOSITORY,
        "sourceProof": source_proof, "r2Core": core, "production": production, "packages": packages,
        "restore": {"config": "NuGet.Config", "source": NUGET_ORG, "commands": "commands.log"},
    }
    superproject = output / "superproject-input.txt"
    if superproject.exists():
        commit, gitlink = superproject.read_text().splitlines()
        manifest["superproject"] = {"commit": commit, "frameworkGitlink": gitlink}

    for directory, kind in (("feed", "package"), ("symbols", "symbols")):
        destination = output / directory
        destination.mkdir()
        for package in packages.values():
            filename = package[kind]["file"]
            shutil.copyfile(packed / filename, destination / filename)
    (output / "manifest.json").write_text(as_json(manifest))


if __name__ == "__main__":
    command, *arguments = sys.argv[1:]
    actions = {"source": source, "prepare": prepare, "assets": assets, "compiler": compiler, "finish": finish}
    try:
        actions[command](*arguments)
    except (ValueError, OSError, KeyError) as error:
        sys.exit(str(error))
