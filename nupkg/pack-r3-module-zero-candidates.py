"""生产并核对按拓扑还原的 R3 Module Zero 本地候选。"""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from xml.etree import ElementTree as ET
from zipfile import ZipFile


PROJECTS = {
    "Du.Abp.Zero.Common": ("Du.Abp",),
    "Du.Abp.ZeroCore": ("Du.Abp.Zero.Common",),
    "Du.Abp.ZeroCore.EntityFrameworkCore": ("Du.Abp.ZeroCore", "Du.Abp.EntityFrameworkCore"),
}
WEB_PROJECT = "Du.Abp.ZeroCore"
TFM = "net9.0"
SDK = "10.0.404"
SOURCE = "https://api.nuget.org/v3/index.json"
REPOSITORY = "https://github.com/dusdong/aspnetboilerplate.git"
PROOF = "du-r3-candidate-source.json"
R2_PROOF = "du-core-candidate-source.json"
EVALUATION_PROPERTIES = (
    "PackageId,PackageVersion,Version,AssemblyName,RootNamespace,TargetFramework,TargetPath,"
    "GeneratePackageOnBuild,IsPackable,RepositoryUrl,RepositoryCommit,IncludeSymbols,SymbolPackageFormat"
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def record(path, root):
    return {"path": str(path.relative_to(root)), "sha256": sha256(path.read_bytes())}


def run(cwd, args, log, commands, env=None):
    args = [str(arg) for arg in args]
    with commands.open("a", encoding="utf-8") as transcript:
        transcript.write(f"目录 {cwd}\n命令 {shlex.join(args)}\n日志 {log}\n")
        with log.open("wb") as stream:
            result = subprocess.run(args, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT, env=env)
        transcript.write(f"退出码 {result.returncode}\n")
    require(result.returncode == 0, f"命令退出 {result.returncode}，见 {log}")
    return log


def archive_entries(package, directory):
    return {entry for entry in package.namelist() if entry.startswith(directory)}


def verify_r2(root, feed, local, replay):
    lock = read_json(Path(__file__).with_name("r3-module-zero-r2.json"))
    if root is not None:
        reference = read_json(root / "eng/r3_r2_reference.json")
        require(reference["frameworkTree"] == lock["frameworkTree"] and
                reference["version"] == lock["version"] and
                reference["evidenceSha256"]["manifest"] == lock["manifestSha256"],
                "R2 清单锁定值与主仓登记不符")
        for package_id, expected in lock["packages"].items():
            registered = reference["packages"][package_id]
            target = registered["targets"][TFM]
            require(expected == {
                "archiveSha256": registered["nupkgSha256"], "assetPath": target["assetPath"],
                "assetSha256": target["assetSha256"], "dependencies": target["internalDependencies"],
            }, f"{package_id} 与主仓 R2 登记不符")

    manifest_path, proof_path, patch = (feed.parent / name for name in ("manifest.json", R2_PROOF, "source.patch"))
    require(sha256(manifest_path.read_bytes()) == lock["manifestSha256"],
            f"{manifest_path} 与 R2 清单摘要不符")
    manifest, proof = read_json(manifest_path), read_json(proof_path)
    require(proof == manifest["sourceProof"] and proof["tree"] == lock["frameworkTree"] and
            sha256(patch.read_bytes()) == proof["patchSha256"], f"{proof_path} 与 R2 来源登记不符")
    replay("r2", proof["baseCommit"], patch, lock["frameworkTree"])
    packages = {}
    for package_id, expected in lock["packages"].items():
        name = f"{package_id}.{lock['version']}.nupkg"
        archive = feed / name
        raw = archive.read_bytes()
        require(sha256(raw) == expected["archiveSha256"],
                f"{archive} SHA-256 不符，预期 {expected['archiveSha256']}，实际 {sha256(raw)}")
        copy = local / name
        copy.write_bytes(raw)
        with ZipFile(copy) as package:
            require(package.read(R2_PROOF) == proof_path.read_bytes(), f"{archive} 的包内 R2 源码证明不符")
            require(sha256(package.read(expected["assetPath"])) == expected["assetSha256"],
                    f"{archive} 中 {expected['assetPath']} 的 SHA-256 不符")
        packages[package_id] = {**expected, "archive": str(archive), "version": lock["version"]}
    return {"sourceProof": proof, "manifestSha256": lock["manifestSha256"], "packages": packages}


def write_config(path, r2_source, candidate_source, r2_ids):
    config = ET.Element("configuration")
    sources = ET.SubElement(config, "packageSources")
    mapping = ET.SubElement(config, "packageSourceMapping")
    for element in (sources, mapping, ET.SubElement(config, "fallbackPackageFolders")):
        ET.SubElement(element, "clear")
    for key, source, ids in (
        ("r2-core", r2_source, r2_ids), ("r3-module-zero", candidate_source, PROJECTS),
        ("nuget.org", SOURCE, ("*",)),
    ):
        ET.SubElement(sources, "add", key=key, value=str(source))
        group = ET.SubElement(mapping, "packageSource", key=key)
        for package_id in ids:
            ET.SubElement(group, "package", pattern=package_id)
    ET.indent(config)
    ET.ElementTree(config).write(path, encoding="utf-8", xml_declaration=True)


def framework_package(package_id):
    return package_id.lower().startswith(("abp", "du.abp"))


def check_assets(path, package_id, expected_edges, archives, local_sources, cache, logs):
    data = read_json(path)
    project = data["project"]
    restore = project["restore"]
    require(list(data["targets"]) == [TFM] and not restore["frameworks"][TFM]["projectReferences"],
            f"{path} 的还原目标或项目引用不符")
    folders = [Path(folder).resolve() for folder in data["packageFolders"]]
    require(folders == [cache], f"{path} 的还原缓存不符：{folders}")
    sources = {source if source == SOURCE else str(Path(source).resolve()) for source in restore["sources"]}
    require(sources == {SOURCE, *(str(source) for source in local_sources)}, f"{path} 的还原源不符：{sources}")
    direct = project["frameworks"][TFM]["dependencies"]
    wanted = {f"{dep}/{version}" for dep, version in expected_edges.items()}
    actual_direct = {dep for dep in direct if framework_package(dep)}
    require(actual_direct == set(expected_edges), f"{path} 的直接框架依赖不符：{actual_direct}")
    for dep, version in expected_edges.items():
        require(direct[dep].get("version") == f"[{version}, {version}]" and
                "suppressParent" not in direct[dep], f"{package_id} → {dep} 的传播或版本不符：{direct[dep]}")

    selected = data["targets"][TFM]
    selected_framework = {key for key in selected if framework_package(key.split("/")[0])}
    closure = set()
    while wanted:
        key = wanted.pop()
        if key in closure:
            continue
        dep, version = key.split("/")
        info = archives[dep]
        require(version == info["version"], f"{dep} 的选中版本不符：{version}")
        closure.add(key)
        wanted.update(f"{child}/{archives[child]['version']}" for child in info["dependencies"])
    require(selected_framework == closure, f"{path} 的框架闭包不符：{selected_framework}，预期 {closure}")

    result = {}
    for key, assets in selected.items():
        dep, version = key.split("/")
        library = data["libraries"][key]
        require(library["type"] == assets["type"] == "package", f"{key} 出现非包资产")
        folder = cache / library["path"]
        cache_meta = folder / ".nupkg.metadata"
        nuget_meta = read_json(cache_meta)
        archive = folder / f"{dep.lower()}.{version}.nupkg"
        raw = archive.read_bytes()
        archive_hash = base64.b64encode(hashlib.sha512(raw).digest()).decode("ascii")
        content_hash = nuget_meta["contentHash"]
        require(content_hash == library["sha512"] and
                archive.with_suffix(".nupkg.sha512").read_text().strip() == archive_hash,
                f"{archive} 的 NuGet 内容哈希或实际归档哈希不符")
        result[dep] = {
            "version": version, "source": nuget_meta["source"], "archive": str(archive),
            "archiveSha256": sha256(raw), "nugetContentSha512": content_hash, "archiveSha512": archive_hash,
            "dependencies": assets.get("dependencies", {}),
            "assets": {kind: assets[kind] for kind in ("compile", "runtime", "runtimeTargets", "build") if kind in assets},
            "declaration": direct.get(dep),
        }
        if key not in closure:
            require(nuget_meta["source"] == SOURCE, f"{key} 的第三方包来源不符：{nuget_meta['source']}")
            continue
        expected = archives[dep]
        dll = (folder / expected["assetPath"]).resolve()
        actual_edges = {child: constraint for child, constraint in result[dep]["dependencies"].items()
                        if framework_package(child)}
        require(actual_edges == expected["dependencies"], f"{key} 的框架依赖边不符：{actual_edges}")
        require(Path(nuget_meta["source"]) == expected["source"] and
                result[dep]["archiveSha256"] == expected["archiveSha256"], f"{key} 的缓存归档或来源不符")
        require(all(set(assets.get(kind, {})) == {expected["assetPath"]} for kind in ("compile", "runtime")) and
                sha256(dll.read_bytes()) == expected["assetSha256"], f"{key} 的编译或运行资产不符：{dll}")
        shutil.copyfile(cache_meta, logs / f"{package_id}.{dep}.nupkg.metadata")
        result[dep].update(asset=str(dll), assetPath=expected["assetPath"], assetSha256=expected["assetSha256"])
    return result


def check_compiler(log, name, assets):
    invocations = [shlex.split(line) for line in log.read_text(encoding="utf-8").splitlines()
                   if "/noconfig " in line and f"/out:obj/Release/{TFM}/{name}.dll" in line]
    require(len(invocations) == 1, f"{log} 应含一次生成 {name} 的实际 Csc 调用")
    references = [Path(argument.removeprefix("/reference:")).resolve() for argument in invocations[0]
                  if argument.startswith("/reference:") and argument.endswith(".dll")]
    expected = {Path(entry["asset"]): entry["assetSha256"] for entry in assets.values() if "asset" in entry}
    actual = [path for path in references if framework_package(path.name)]
    require(len(actual) == len(expected) and set(actual) == set(expected),
            f"{log} 的框架编译引用不符：{actual}，预期 {list(expected)}")
    result = {str(path): sha256(path.read_bytes()) for path in actual}
    require(result == {str(path): digest for path, digest in expected.items()}, f"{log} 的编译引用 SHA-256 不符")
    return {"project": name, "frameworkReferences": result, "references": [str(path) for path in references]}


def check_nuspec(archive, package_id, version, dependencies, proof, symbols):
    raw = archive.read(f"{package_id}.nuspec")
    metadata = ET.fromstring(raw).find("{*}metadata")
    required_repository = {"url": REPOSITORY, "type": "git"}
    if "commit" in proof:
        required_repository["commit"] = proof["commit"]
    require(metadata.findtext("{*}id") == package_id and metadata.findtext("{*}version") == version and
            metadata.find("{*}repository").attrib == required_repository, f"{archive.filename} 的身份或仓库不符")
    groups = list(metadata.find("{*}dependencies"))
    actual = [(item.attrib["id"], item.attrib["version"]) for group in groups for item in group]
    require(len(groups) == 1 and groups[0].attrib["targetFramework"] == TFM and
            sorted(actual) == sorted(dependencies.items()), f"{archive.filename} 的框架依赖不符：{actual}")
    frameworks = [(group.attrib["targetFramework"], item.attrib["name"])
                  for group in metadata.findall("{*}frameworkReferences/{*}group") for item in group]
    require(frameworks == ([(TFM, "Microsoft.AspNetCore.App")] if package_id == WEB_PROJECT else []),
            f"{archive.filename} 的共享框架引用不符：{frameworks}")
    if symbols:
        require([item.attrib["name"] for item in metadata.findall("{*}packageTypes/{*}packageType")] ==
                ["SymbolsPackage"], f"{archive.filename} 缺少符号包声明")
    else:
        require(metadata.find("{*}license").attrib == {"type": "file"} and
                metadata.findtext("{*}license") == "LICENSE.md" and metadata.findtext("{*}icon") == "abp_nupkg.png",
                f"{archive.filename} 的许可或图标声明不符")
    return raw


def check_package(package_id, version, dependencies, evaluation, proof_path, source, packed, output):
    name = package_id.removeprefix("Du.")
    package_path, symbols_path = (packed / f"{package_id}.{version}.{extension}" for extension in ("nupkg", "snupkg"))
    dll_path, pdb_path = (f"lib/{TFM}/{name}.{extension}" for extension in ("dll", "pdb"))
    proof = read_json(proof_path)
    build_dll = Path(evaluation["Properties"]["TargetPath"])
    with ZipFile(package_path) as package, ZipFile(symbols_path) as symbols:
        for archive, is_symbols in ((package, False), (symbols, True)):
            raw = check_nuspec(archive, package_id, version, dependencies, proof, is_symbols)
            suffix = "symbols.nuspec" if is_symbols else "nuspec"
            (output / "logs" / f"{package_id}.{suffix}").write_bytes(raw)
        require(package.read(PROOF) == proof_path.read_bytes(), f"{package_path} 的包内源码证明不符")
        for file, path in (("LICENSE.md", "LICENSE.md"), ("abp_nupkg.png", "nupkg/abp_nupkg.png")):
            require(package.read(file) == (source / path).read_bytes(), f"{package_path} 的 {file} 与源码不符")
        for archive, expected in ((package, {dll_path, f"lib/{TFM}/{name}.xml"}), (symbols, {pdb_path})):
            require(archive_entries(archive, ("lib/", "ref/", "runtimes/")) == expected,
                    f"{archive.filename} 的目标资产不符")
        dll, pdb = package.read(dll_path), symbols.read(pdb_path)
        require(dll == build_dll.read_bytes() and pdb == build_dll.with_suffix(".pdb").read_bytes() and
                pdb.startswith(b"BSJB"), f"{package_path} 或 {symbols_path} 与实际 Release 输出不符")

    for path, destination in ((package_path, "feed"), (symbols_path, "symbols")):
        shutil.copyfile(path, output / destination / path.name)
    return {
        "assemblyName": name, "rootNamespace": evaluation["Properties"]["RootNamespace"],
        "package": {"file": package_path.name, "sha256": sha256(package_path.read_bytes())},
        "symbols": {"file": symbols_path.name, "sha256": sha256(symbols_path.read_bytes())},
        "targets": {TFM: {"path": dll_path, "sha256": sha256(dll), "pdbPath": pdb_path, "pdbSha256": sha256(pdb)}},
        "dependencies": dependencies,
    }


def produce(framework, args, scratch, output):
    logs = output / "logs"
    logs.mkdir()
    commands = output / "commands.log"

    def git(name, *command, cwd=framework, env=None):
        return run(cwd, ["git", *command], logs / f"{name}.log", commands, env).read_text(encoding="utf-8").strip()

    common = Path(git("git-dir", "rev-parse", "--path-format=absolute", "--git-common-dir"))
    version_record = common / "du-r3-leaf-candidate-versions" / args.version
    require(not version_record.exists(), f"候选版本已分配：{version_record}")
    head = git("checkout-commit", "rev-parse", "HEAD")
    base_tree = git("base-tree", "rev-parse", f"{head}^{{tree}}")
    superproject = git("superproject", "rev-parse", "--show-superproject-working-tree")
    root = Path(superproject) if superproject else None
    parent = None
    if root:
        commit = git("superproject-commit", "rev-parse", "HEAD", cwd=root)
        link = git("gitlink", "ls-tree", commit, "--", framework.relative_to(root), cwd=root).split()
        require(len(link) >= 4 and link[:2] == ["160000", "commit"], f"{root} 的框架 gitlink 无效")
        parent = {"commit": commit, "frameworkGitlink": link[2]}

    objects = scratch / "objects"
    source = scratch / "source"
    r2_source = scratch / "r2-core"
    packed = scratch / "packed"
    for directory in (objects, source, r2_source, packed, output / "feed", output / "symbols"):
        directory.mkdir()
    git_env = {**os.environ, "GIT_OBJECT_DIRECTORY": str(objects),
               "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(common / "objects")}

    def replay(label, base, patch, expected):
        env = {**git_env, "GIT_INDEX_FILE": str(scratch / f"{label}.index")}
        git(f"{label}-read-tree", "read-tree", base, env=env)
        if patch.stat().st_size:
            git(f"{label}-apply", "-c", "apply.whitespace=nowarn", "apply", "--cached", patch, env=env)
        tree = git(f"{label}-write-tree", "write-tree", env=env)
        require(tree == expected, f"{label} 补丁重放写出 {tree}，预期 {expected}")

    r2 = verify_r2(root, args.r2_feed.resolve(strict=True), r2_source, replay)
    write_json(output / "r2-input.json", r2)
    capture_env = {**git_env, "GIT_INDEX_FILE": str(scratch / "capture.index")}
    git("read-tree", "read-tree", head, env=capture_env)
    git("add-source", "add", "--all", "--", ".", env=capture_env)
    tree = git("write-tree", "write-tree", env=capture_env)
    patch = run(framework, ["git", "diff", "--cached", "--no-color", "--no-ext-diff", "--no-textconv",
                            "--full-index", "--binary", head], output / "source.patch", commands, capture_env)
    replay("candidate", head, patch, tree)
    tar = scratch / "source.tar"
    git("archive", "archive", "--format=tar", f"--output={tar}", tree, env=capture_env)
    run(source, ["tar", "-xf", tar], logs / "extract.log", commands)
    entry = Path(__file__).relative_to(framework)
    for name in (entry.name, "pack-r3-module-zero-candidates.sh", "r3-module-zero-r2.json"):
        file = entry.with_name(name)
        require((framework / file).read_bytes() == (source / file).read_bytes(), f"{file} 与物化源码不符")

    proof = {"baseCommit": head, "baseTree": base_tree, "tree": tree, "patchSha256": sha256(patch.read_bytes())}
    if tree == base_tree:
        proof["commit"] = head
    proof_path = output / PROOF
    write_json(proof_path, proof)

    dotnet = shutil.which("dotnet")
    require(dotnet is not None, "PATH 中找不到 dotnet")
    sdk = run(source, [dotnet, "--version"], logs / "sdk.txt", commands).read_text().strip()
    require(sdk == SDK, f"候选打包需要 SDK {SDK}，实际为 {sdk}")
    run(source, [dotnet, "--info"], logs / "dotnet-info.txt", commands)
    config = output / "NuGet.Config"
    candidate_feed = output / "feed"
    write_config(config, r2_source, candidate_feed, r2["packages"])
    cache = scratch / "packages"
    isolated = {"NUGET_PACKAGES": str(cache), "NUGET_HTTP_CACHE_PATH": str(scratch / "http-cache"),
                "MSBUILDDISABLENODEREUSE": "1"}
    with commands.open("a", encoding="utf-8") as transcript:
        for key, value in isolated.items():
            transcript.write(f"{key}={shlex.quote(value)}\n")

    properties = [
        "-p:Configuration=Release", "-p:DuR3ModuleZeroCandidatePack=true",
        f"-p:DuR3CandidatePackageVersion={args.version}", f"-p:DuR3CandidateSourceProof={proof_path}",
        f"-p:DuR3CandidateCommit={proof.get('commit', '')}", "-p:DisableImplicitNuGetFallbackFolder=true",
        "-p:RestoreFallbackFolders=", "-p:RestoreAdditionalProjectFallbackFolders=",
        "-p:RestoreSources=", "-p:RestoreAdditionalProjectSources=",
    ]
    archives = {package_id: {**info, "source": r2_source} for package_id, info in r2["packages"].items()}
    production = {}
    packages = {}
    version_record.parent.mkdir(parents=True, exist_ok=True)
    version_record.mkdir()
    shutil.copyfile(proof_path, version_record / "source.json")
    (version_record / "output.txt").write_text(f"{output}\n", encoding="utf-8")
    for package_id, dependencies in PROJECTS.items():
        name = package_id.removeprefix("Du.")
        project = Path("src") / name / f"{name}.csproj"
        edges = {dep: archives[dep]["version"] for dep in dependencies}
        ranges = {dep: f"[{version}]" for dep, version in edges.items()}

        def step(label, *command):
            return run(source, [dotnet, *command], logs / f"{package_id}.{label}", commands,
                       {**os.environ, **isolated})

        evaluation_path = step("evaluation.json", "msbuild", project, "-nologo", *properties,
                               f"-getProperty:{EVALUATION_PROPERTIES}", "-getItem:ProjectReference,PackageReference,FrameworkReference")
        evaluation = read_json(evaluation_path)
        expected = {"PackageId": package_id, "PackageVersion": args.version, "Version": "10.5.1",
                    "AssemblyName": name, "RootNamespace": "Abp", "TargetFramework": TFM,
                    "GeneratePackageOnBuild": "false", "IncludeSymbols": "true", "SymbolPackageFormat": "snupkg",
                    "RepositoryUrl": REPOSITORY, "RepositoryCommit": proof.get("commit", "")}
        require(all(evaluation["Properties"].get(key) == value for key, value in expected.items()) and
                not evaluation["Items"]["ProjectReference"], f"{evaluation_path} 的候选属性或项目引用不符")
        package_edges = {ref["Identity"]: ref["Version"] for ref in evaluation["Items"]["PackageReference"]
                         if framework_package(ref["Identity"])}
        require(package_edges == ranges, f"{evaluation_path} 的包引用不符：{package_edges}")
        step("restore.log", "restore", project, *properties, "--configfile", config,
             "--no-http-cache", "--disable-build-servers")
        assets_file = logs / f"{package_id}.project.assets.json"
        shutil.copyfile(source / project.parent / "obj/project.assets.json", assets_file)
        selected = check_assets(assets_file, package_id, edges, archives, (r2_source, candidate_feed), cache, logs)
        write_json(logs / f"{package_id}.restore-inputs.json", selected)
        pack_log = step("pack.log", "pack", project, *properties, "--no-restore", "--disable-build-servers",
                        "-p:UseSharedCompilation=false", "--verbosity", "normal", "--output", packed)
        write_json(logs / f"{package_id}.compiler.json", check_compiler(pack_log, name, selected))
        package = check_package(package_id, args.version, ranges, evaluation, proof_path, source, packed, output)
        packages[package_id] = package
        archives[package_id] = {
            "archiveSha256": package["package"]["sha256"], "assetPath": package["targets"][TFM]["path"],
            "assetSha256": package["targets"][TFM]["sha256"], "source": candidate_feed,
            "version": args.version, "dependencies": ranges,
        }
        production[package_id] = {path.name.removeprefix(f"{package_id}."): record(path, output)
                                  for path in sorted(logs.glob(f"{package_id}.*"))}

    manifest = {
        "schemaVersion": 1, "version": args.version, "sdk": sdk, "repositoryUrl": REPOSITORY,
        "sourceProof": proof, "frameworkCheckout": {"commit": head, "tree": base_tree},
        "r2": r2, "production": production, "packages": packages,
        "restore": {"config": record(config, output), "commands": record(commands, output),
                    "source": SOURCE},
    }
    if parent:
        manifest["superproject"] = parent
    write_json(output / "manifest.json", manifest)
    shutil.copyfile(output / "manifest.json", version_record / "manifest.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--r2-feed", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"10[.]5[.]1-r3[.][1-9][0-9]*", args.version):
        parser.error("--version 需要 10.5.1-r3.<正整数>")
    framework = Path(__file__).resolve().parent.parent
    output = args.output.resolve()
    require(output != framework and framework not in output.parents, "请指定框架源码目录以外的输出位置")
    output.mkdir(parents=True, exist_ok=True)
    require(not any(output.iterdir()), f"候选输出目录须为空：{output}")
    with TemporaryDirectory(prefix="du-abp-r3-module-zero.") as scratch:
        produce(framework, args, Path(scratch).resolve(), output)
    print(f"候选源 {output / 'feed'}\n候选清单 {output / 'manifest.json'}")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, AttributeError) as error:
        sys.exit(str(error))
